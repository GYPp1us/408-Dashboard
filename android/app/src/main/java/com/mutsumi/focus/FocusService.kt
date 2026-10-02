package com.mutsumi.focus

import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import java.util.concurrent.Executors

class FocusService : Service() {
    private lateinit var store: FocusStateStore
    private lateinit var publisher: OriginOsAtomicPublisher
    private lateinit var notificationManager: NotificationManager
    private lateinit var applicationOverlay: ApplicationOverlay
    private val handler = Handler(Looper.getMainLooper())
    private val networkExecutor = Executors.newSingleThreadExecutor()
    private var currentReminder: ReminderKind? = null
    private var reminderSessionId = 0L
    private var reminderUsesNotification = false
    private var lastServerSyncAt = 0L
    private var serverSyncInFlight = false
    private var liveSessionId = 0L
    private var wakeLock: PowerManager.WakeLock? = null
    private var destroyed = false

    private val tick = object : Runnable {
        override fun run() {
            val state = store.read()
            if (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.ENDED)) {
                refreshWakeLock()
                maybeSyncServer(state)
                checkReminder(state)
                handler.postDelayed(this, TICK_MS)
            } else {
                stopRuntime(removeNotification = true)
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        store = FocusStateStore(this)
        publisher = OriginOsAtomicPublisher(this)
        notificationManager = getSystemService(NotificationManager::class.java)
        applicationOverlay = ApplicationOverlay(this)
        publisher.ensureChannels()
        runningService = this
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // All requests and lifecycle callbacks are serialized on the main
        // thread. A request is no longer pending once this callback owns its
        // foreground promotion; teardown below still follows that promotion.
        pendingStarts.remove(intent?.getLongExtra(EXTRA_START_REQUEST, 0L))
        val state = store.read()
        // A previously accepted foreground start can arrive after an idle
        // sync, or take an action branch that immediately stops the service.
        // Fulfil the platform contract before either dispatch or teardown.
        val operation = when {
            state.mode in setOf(FocusMode.IDLE, FocusMode.REST, FocusMode.ENDED) -> OriginOsAtomicPublisher.AtomicOperation.END
            liveSessionId != state.sessionId -> OriginOsAtomicPublisher.AtomicOperation.CREATE
            else -> OriginOsAtomicPublisher.AtomicOperation.UPDATE
        }
        if (!publishLive(state, operation)) return START_NOT_STICKY
        if (operation == OriginOsAtomicPublisher.AtomicOperation.CREATE) liveSessionId = state.sessionId
        if (state.mode in setOf(FocusMode.IDLE, FocusMode.REST)) {
            stopRuntime(removeNotification = true)
            return START_NOT_STICKY
        }
        when (intent?.action) {
            ACTION_PAUSE -> executeRemoteAction(state, RemoteAction.PAUSE)
            ACTION_RESUME -> executeRemoteAction(state, RemoteAction.RESUME)
            ACTION_END -> executeRemoteAction(state, RemoteAction.END)
            ACTION_OPEN_FROM_REMINDER -> acknowledgeAndOpen(currentReminder ?: dueNow(state)?.kind)
            ACTION_ACK_REMINDER -> {
                applyState(state)
                val kind = ReminderKind.entries.getOrNull(intent.getIntExtra(EXTRA_REMINDER_KIND, -1))
                val sameSession = intent.getLongExtra(EXTRA_SESSION_ID, -1) == state.sessionId
                if (sameSession && kind != null &&
                    ((kind == ReminderKind.PAUSED && state.mode == FocusMode.PAUSED) ||
                        (kind != ReminderKind.PAUSED && state.mode == FocusMode.ENDED))
                ) acknowledgeReminder(kind, openApp = false)
            }
            else -> applyState(state)
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        destroyed = true
        if (runningService === this) runningService = null
        handler.removeCallbacksAndMessages(null)
        dismissReminder()
        releaseWakeLock()
        networkExecutor.shutdownNow()
        super.onDestroy()
    }

    private fun applyState(state: FocusRuntimeState) {
        handler.removeCallbacks(tick)
        if (currentReminder != null &&
            (reminderSessionId != state.sessionId || currentReminder != dueNow(state)?.kind)
        ) dismissReminder()
        if (state.mode in setOf(FocusMode.IDLE, FocusMode.REST)) {
            stopRuntime(removeNotification = true)
            return
        }
        if (state.mode == FocusMode.ENDED && store.endedAcknowledgedCount() >= 3) {
            stopRuntime(removeNotification = true)
            return
        }
        val operation = if (liveSessionId != state.sessionId) {
            liveSessionId = state.sessionId
            OriginOsAtomicPublisher.AtomicOperation.CREATE
        } else {
            OriginOsAtomicPublisher.AtomicOperation.UPDATE
        }
        if (!publishLive(state, if (state.mode == FocusMode.ENDED) OriginOsAtomicPublisher.AtomicOperation.END else operation)) return
        checkReminder(state)
        handler.postDelayed(tick, TICK_MS)
    }

    private fun publishLive(state: FocusRuntimeState, operation: OriginOsAtomicPublisher.AtomicOperation): Boolean {
        try {
            startForeground(OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID, publisher.liveNotification(state, operation))
            return true
        } catch (error: Exception) {
            // A plain notification cannot discharge a foreground-start
            // obligation. Cancel the runtime instead of leaving its watchdog.
            Log.w("FocusService", "Foreground promotion failed; stopping runtime", error)
            stopRuntime(removeNotification = true)
            return false
        }
    }

    private fun maybeSyncServer(state: FocusRuntimeState) {
        val now = System.currentTimeMillis()
        if (serverSyncInFlight || now - lastServerSyncAt < SERVER_SYNC_MS) return
        lastServerSyncAt = now
        serverSyncInFlight = true
        val requestedRevision = store.transitionRevision()
        networkExecutor.execute {
            val heartbeat = if (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED) && state.sessionId > 0) {
                FocusApi.heartbeat(state)
            } else null
            val remote = FocusApi.fetchState(state)
            handler.post {
                serverSyncInFlight = false
                if (destroyed || !FocusStateReducer.canApplyResponse(state, store.read(), requestedRevision, store.transitionRevision())) return@post
                if (heartbeat?.status == 401 || heartbeat?.status == 403 || remote.status == 401 || remote.status == 403) {
                    store.write(FocusRuntimeState())
                    stopRuntime(removeNotification = true)
                    return@post
                }
                val incoming = remote.state
                if (remote.successful && incoming != null) {
                    val reduced = FocusStateReducer.reduce(store.read(), incoming, store.endedAcknowledgedCount())
                    store.write(reduced)
                    applyState(reduced)
                    sendBroadcast(Intent(ACTION_REFRESH_WEB).setPackage(packageName))
                }
            }
        }
    }

    private fun executeRemoteAction(state: FocusRuntimeState, action: RemoteAction) {
        if (state.sessionId <= 0) { applyState(state); return }
        val requestedRevision = store.transitionRevision()
        if (!publishLive(state, OriginOsAtomicPublisher.AtomicOperation.UPDATE)) return
        networkExecutor.execute {
            val result = when (action) {
                RemoteAction.PAUSE -> FocusApi.setPaused(state, true)
                RemoteAction.RESUME -> FocusApi.setPaused(state, false)
                RemoteAction.END -> FocusApi.end(state)
            }
            handler.post {
                if (destroyed || !FocusStateReducer.canApplyResponse(state, store.read(), requestedRevision, store.transitionRevision())) return@post
                if (result.status == 401 || result.status == 403) {
                    store.write(FocusRuntimeState())
                    stopRuntime(removeNotification = true)
                } else if (result.successful) {
                    val now = System.currentTimeMillis()
                    val updated = when (action) {
                        RemoteAction.PAUSE -> state.copy(
                            mode = FocusMode.PAUSED,
                            pausedAtEpochMs = now,
                            elapsedSeconds = state.elapsedNow(now),
                            observedAtEpochMs = now,
                        )
                        RemoteAction.RESUME -> state.copy(
                            mode = FocusMode.FOCUSING,
                            pausedAtEpochMs = 0,
                            observedAtEpochMs = now,
                        )
                        RemoteAction.END -> state.copy(
                            mode = FocusMode.ENDED,
                            endedAtEpochMs = now,
                            elapsedSeconds = state.elapsedNow(now),
                            observedAtEpochMs = now,
                        )
                    }
                    store.write(updated)
                    applyState(updated)
                } else {
                    applyState(store.read())
                }
                sendBroadcast(Intent(ACTION_REFRESH_WEB).setPackage(packageName))
            }
        }
    }

    private fun dueNow(state: FocusRuntimeState): DueReminder? = ReminderPolicy.due(
        state,
        System.currentTimeMillis(),
        store.pausedSnoozeUntil(),
        store.endedAcknowledgedCount(),
    )

    private fun checkReminder(state: FocusRuntimeState) {
        val due = dueNow(state) ?: return
        if (currentReminder == due.kind && reminderSessionId == state.sessionId) {
            // SystemUI can remove a notification while an acknowledgement or
            // lifecycle check posts the next reminder using the same ID.
            // Reconcile the fallback with the actual notification, rather than
            // keeping a due reminder hidden behind stale in-memory state.
            if (!reminderUsesNotification || notificationManager.activeNotifications.any {
                    it.id == OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID
                }) return
        }
        if (currentReminder != null) dismissReminder()
        currentReminder = due.kind
        reminderSessionId = state.sessionId
        val onContinue = { acknowledgeReminder(due.kind, openApp = false) }
        val onOpen = { acknowledgeReminder(due.kind, openApp = true) }
        val shown = applicationOverlay.show(due.kind, onContinue, onOpen) ||
            FocusAccessibilityService.show(due.kind, onContinue, onOpen)
        reminderUsesNotification = !shown
        if (!shown) {
            notificationManager.notify(
                OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID,
                publisher.reminderNotification(due.kind, state.sessionId),
            )
        }
    }

    private fun acknowledgeReminder(kind: ReminderKind, openApp: Boolean) {
        if (kind == ReminderKind.PAUSED) store.snoozePaused(System.currentTimeMillis())
        else store.acknowledgeEnded(kind.endedIndex)
        dismissReminder()
        if (openApp) openTimer()
        val state = store.read()
        if (state.mode == FocusMode.ENDED && store.endedAcknowledgedCount() >= 3) {
            stopRuntime(removeNotification = true)
        }
    }

    private fun acknowledgeAndOpen(kind: ReminderKind?) {
        if (kind != null) acknowledgeReminder(kind, openApp = true) else openTimer()
    }

    private fun openTimer() {
        try {
            startActivity(Intent(this, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            })
        } catch (_: Exception) {
            // The heads-up notification remains a route back if background launch is restricted.
        }
    }

    private fun dismissReminder() {
        FocusAccessibilityService.dismiss()
        applicationOverlay.dismiss()
        notificationManager.cancel(OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID)
        currentReminder = null
        reminderSessionId = 0L
        reminderUsesNotification = false
    }

    private fun refreshWakeLock() {
        val power = getSystemService(PowerManager::class.java)
        val lock = wakeLock ?: power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$packageName:focus-runtime").also {
            it.setReferenceCounted(false)
            wakeLock = it
        }
        if (!lock.isHeld) lock.acquire(WAKE_LOCK_WINDOW_MS)
    }

    private fun releaseWakeLock() {
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    private fun stopRuntime(removeNotification: Boolean) {
        handler.removeCallbacksAndMessages(null)
        dismissReminder()
        releaseWakeLock()
        // startForegroundService() is a synchronous Binder request, but its
        // onStartCommand() arrives later. Android can crash us immediately if
        // we stop while any accepted request still awaits foreground promotion.
        // Drain those callbacks instead; each reads the latest stored state.
        if (pendingStarts.isNotEmpty()) return
        stopForeground(if (removeNotification) STOP_FOREGROUND_REMOVE else STOP_FOREGROUND_DETACH)
        if (removeNotification) notificationManager.cancel(OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID)
        if (runningService === this) runningService = null
        stopSelf()
    }

    private enum class RemoteAction { PAUSE, RESUME, END }

    companion object {
        const val ACTION_REFRESH_WEB = "com.mutsumi.focus.REFRESH_WEB"
        const val ACTION_PAUSE = "com.mutsumi.focus.PAUSE"
        const val ACTION_RESUME = "com.mutsumi.focus.RESUME"
        const val ACTION_END = "com.mutsumi.focus.END"
        const val ACTION_OPEN_FROM_REMINDER = "com.mutsumi.focus.OPEN_FROM_REMINDER"
        private const val ACTION_ACK_REMINDER = "com.mutsumi.focus.ACK_REMINDER"
        const val EXTRA_REMINDER_KIND = "reminder_kind"
        const val EXTRA_SESSION_ID = "reminder_session_id"
        private const val ACTION_SYNC = "com.mutsumi.focus.SYNC"
        private const val ACTION_CHECK = "com.mutsumi.focus.CHECK"
        private const val EXTRA_START_REQUEST = "focus_start_request"
        private const val TICK_MS = 15_000L
        private const val SERVER_SYNC_MS = 15_000L
        private const val WAKE_LOCK_WINDOW_MS = 10 * 60_000L
        private val mainHandler = Handler(Looper.getMainLooper())
        private var runningService: FocusService? = null
        private var nextStartRequest = 0L
        private val pendingStarts = mutableSetOf<Long>()

        fun sync(context: Context, state: FocusRuntimeState) = onMainThread {
            FocusStateStore(context).write(state)
            if (state.mode in setOf(FocusMode.IDLE, FocusMode.REST)) {
                stopAndCancel(context)
                return@onMainThread
            }
            start(context, ACTION_SYNC)
        }

        fun clear(context: Context) = onMainThread {
            // Identity loss is not a completed session and must not schedule
            // ended reminders or restart an idle foreground service.
            FocusStateStore(context).write(FocusRuntimeState())
            stopAndCancel(context)
        }

        private fun stopAndCancel(context: Context) {
            val service = runningService
            if (service != null) {
                service.stopRuntime(removeNotification = true)
                return
            }
            // With no instance yet, an accepted foreground launch must be
            // allowed to reach onStartCommand(), promote, then read IDLE/REST
            // and stop itself. stopService() would violate that contract.
            if (pendingStarts.isNotEmpty()) return
            val notifications = context.getSystemService(NotificationManager::class.java)
            notifications.cancel(OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID)
            notifications.cancel(OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID)
        }

        fun requestReminderCheck(context: Context) = onMainThread {
            val state = FocusStateStore(context).read()
            if (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.ENDED)) {
                start(context, ACTION_CHECK)
            }
        }

        fun acknowledgeFromNotification(context: Context, notificationIntent: Intent) = onMainThread {
            if (notificationIntent.action != ACTION_OPEN_FROM_REMINDER) return@onMainThread
            val state = FocusStateStore(context).read()
            if (state.mode !in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.ENDED)) return@onMainThread
            start(context, Intent(context, FocusService::class.java).apply {
                action = ACTION_ACK_REMINDER
                putExtra(EXTRA_REMINDER_KIND, notificationIntent.getIntExtra(EXTRA_REMINDER_KIND, -1))
                putExtra(EXTRA_SESSION_ID, notificationIntent.getLongExtra(EXTRA_SESSION_ID, -1))
            })
        }

        private fun start(context: Context, action: String) {
            start(context, Intent(context, FocusService::class.java).setAction(action))
        }

        private fun start(context: Context, intent: Intent) {
            // Reminder/action dispatch may race a newer idle bridge sync.
            if (FocusStateStore(context).read().mode in setOf(FocusMode.IDLE, FocusMode.REST)) {
                stopAndCancel(context)
                return
            }
            val request = ++nextStartRequest
            pendingStarts.add(request)
            intent.putExtra(EXTRA_START_REQUEST, request)
            try {
                if (context.startForegroundService(intent) == null) {
                    pendingStarts.remove(request)
                    stopAndCancel(context)
                }
            } catch (error: IllegalStateException) {
                pendingStarts.remove(request)
                Log.w("FocusService", "Foreground start rejected; stopping runtime", error)
                stopAndCancel(context)
            } catch (error: SecurityException) {
                pendingStarts.remove(request)
                Log.w("FocusService", "Foreground start denied; stopping runtime", error)
                stopAndCancel(context)
            }
        }

        private fun onMainThread(action: () -> Unit) {
            if (Looper.myLooper() == Looper.getMainLooper()) action()
            else mainHandler.post { action() }
        }
    }
}
