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
import java.util.concurrent.Executors

class FocusService : Service() {
    private lateinit var store: FocusStateStore
    private lateinit var publisher: OriginOsAtomicPublisher
    private lateinit var notificationManager: NotificationManager
    private lateinit var applicationOverlay: ApplicationOverlay
    private val handler = Handler(Looper.getMainLooper())
    private val networkExecutor = Executors.newSingleThreadExecutor()
    private var currentReminder: ReminderKind? = null
    private var lastServerSyncAt = 0L
    private var serverSyncInFlight = false
    private var liveSessionId = 0L
    private var wakeLock: PowerManager.WakeLock? = null

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
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val state = store.read()
        when (intent?.action) {
            ACTION_PAUSE -> executeRemoteAction(state, RemoteAction.PAUSE)
            ACTION_RESUME -> executeRemoteAction(state, RemoteAction.RESUME)
            ACTION_END -> executeRemoteAction(state, RemoteAction.END)
            ACTION_OPEN_FROM_REMINDER -> acknowledgeAndOpen(currentReminder ?: dueNow(state)?.kind)
            else -> applyState(state)
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        dismissReminder()
        releaseWakeLock()
        networkExecutor.shutdownNow()
        super.onDestroy()
    }

    private fun applyState(state: FocusRuntimeState) {
        handler.removeCallbacks(tick)
        if (state.mode in setOf(FocusMode.IDLE, FocusMode.REST)) {
            publishLive(state, OriginOsAtomicPublisher.AtomicOperation.END)
            handler.postDelayed({ stopRuntime(removeNotification = true) }, 350)
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
        publishLive(state, if (state.mode == FocusMode.ENDED) OriginOsAtomicPublisher.AtomicOperation.END else operation)
        if (
            state.mode == FocusMode.FOCUSING ||
            (state.mode != FocusMode.PAUSED && currentReminder == ReminderKind.PAUSED)
        ) dismissReminder()
        checkReminder(state)
        handler.postDelayed(tick, TICK_MS)
    }

    private fun publishLive(state: FocusRuntimeState, operation: OriginOsAtomicPublisher.AtomicOperation) {
        val notification = publisher.liveNotification(state, operation)
        try {
            startForeground(OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID, notification)
        } catch (_: Exception) {
            notificationManager.notify(OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID, notification)
        }
    }

    private fun maybeSyncServer(state: FocusRuntimeState) {
        val now = System.currentTimeMillis()
        if (serverSyncInFlight || now - lastServerSyncAt < SERVER_SYNC_MS) return
        lastServerSyncAt = now
        serverSyncInFlight = true
        networkExecutor.execute {
            val heartbeat = if (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED) && state.sessionId > 0) {
                FocusApi.heartbeat(state)
            } else null
            val remote = FocusApi.fetchState(state)
            handler.post {
                serverSyncInFlight = false
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
        if (state.sessionId <= 0) return
        publishLive(state, OriginOsAtomicPublisher.AtomicOperation.UPDATE)
        networkExecutor.execute {
            val result = when (action) {
                RemoteAction.PAUSE -> FocusApi.setPaused(state, true)
                RemoteAction.RESUME -> FocusApi.setPaused(state, false)
                RemoteAction.END -> FocusApi.end(state)
            }
            handler.post {
                if (result.successful) {
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
        if (currentReminder == due.kind) return
        currentReminder = due.kind
        val onContinue = { acknowledgeReminder(due.kind, openApp = false) }
        val onOpen = { acknowledgeReminder(due.kind, openApp = true) }
        val shown = applicationOverlay.show(due.kind, onContinue, onOpen) ||
            FocusAccessibilityService.show(due.kind, onContinue, onOpen)
        if (!shown) {
            notificationManager.notify(
                OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID,
                publisher.reminderNotification(due.kind),
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
        stopForeground(if (removeNotification) STOP_FOREGROUND_REMOVE else STOP_FOREGROUND_DETACH)
        stopSelf()
    }

    private enum class RemoteAction { PAUSE, RESUME, END }

    companion object {
        const val ACTION_REFRESH_WEB = "com.mutsumi.focus.REFRESH_WEB"
        const val ACTION_PAUSE = "com.mutsumi.focus.PAUSE"
        const val ACTION_RESUME = "com.mutsumi.focus.RESUME"
        const val ACTION_END = "com.mutsumi.focus.END"
        const val ACTION_OPEN_FROM_REMINDER = "com.mutsumi.focus.OPEN_FROM_REMINDER"
        private const val ACTION_SYNC = "com.mutsumi.focus.SYNC"
        private const val ACTION_CHECK = "com.mutsumi.focus.CHECK"
        private const val TICK_MS = 15_000L
        private const val SERVER_SYNC_MS = 15_000L
        private const val WAKE_LOCK_WINDOW_MS = 10 * 60_000L

        fun sync(context: Context, state: FocusRuntimeState) {
            FocusStateStore(context).write(state)
            start(context, ACTION_SYNC)
        }

        fun requestReminderCheck(context: Context) {
            val state = FocusStateStore(context).read()
            if (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.ENDED)) {
                start(context, ACTION_CHECK)
            }
        }

        private fun start(context: Context, action: String) {
            val intent = Intent(context, FocusService::class.java).setAction(action)
            context.startForegroundService(intent)
        }
    }
}
