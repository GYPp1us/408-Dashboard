package com.mutsumi.focus

import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import com.mutsumi.focus.atomic.VivoAtomicPayload
import org.json.JSONObject

class FocusService : Service() {
    private lateinit var store: FocusStateStore
    private lateinit var publisher: OriginOsAtomicPublisher
    private lateinit var notifications: NotificationManager
    private lateinit var overlay: ApplicationOverlay
    private val handler = Handler(Looper.getMainLooper())
    private val network = FocusNetworkTasks()
    private var reminderToken = ""
    private var lastSyncAt = 0L
    private var syncing = false
    private val refreshPolicy = AtomicRefreshPolicy()
    private var foregroundStarted = false
    private var islandVisible = false
    private var wakeLock: PowerManager.WakeLock? = null
    private var destroyed = false
    @Volatile private var busy = false
    @Volatile private var messageSince = 0L
    @Volatile private var message = ""
        set(value) { field = value; messageSince = System.currentTimeMillis() }
    @Volatile private var retryAction = ""

    private val tick = object : Runnable {
        override fun run() {
            applyState()
            if (!destroyed) maybeSyncServer()
        }
    }

    override fun onCreate() {
        super.onCreate()
        store = FocusStateStore(this)
        publisher = OriginOsAtomicPublisher(this)
        notifications = getSystemService(NotificationManager::class.java)
        overlay = ApplicationOverlay(this)
        publisher.ensureChannels()
        val previousNotifications = notifications.activeNotifications.filter { it.id == OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID }
        store.seedAtomicRecord(previousNotifications.maxOfOrNull { it.notification.extras.getInt("notification.superx.changedRecord", 0) } ?: 0)
        islandVisible = previousNotifications.any {
            it.id == OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID &&
                it.notification.extras.getInt("notification.superx.operation", -1) in 0..1
        }
        runningService = this
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        pendingStarts.remove(intent?.getLongExtra(EXTRA_START_REQUEST, 0))
        // Discharge every accepted foreground start before any idle teardown.
        if (!publish(store.read())) return START_NOT_STICKY
        val action = intent?.action.orEmpty()
        if (action !in setOf(ACTION_SYNC, ACTION_CHECK, "") && matches(intent)) handleAction(action)
        else applyState()
        return if (store.read().mode == FocusMode.IDLE && !store.islandContext().enabled(System.currentTimeMillis())) START_NOT_STICKY else START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        destroyed = true
        if (runningService === this) runningService = null
        handler.removeCallbacksAndMessages(null)
        dismissSurfaces()
        releaseWakeLock()
        network.close()
        super.onDestroy()
    }

    private fun matches(intent: Intent?): Boolean {
        if (intent == null) return false
        val state = store.read()
        if (intent.hasExtra(EXTRA_SESSION_ID) && intent.getLongExtra(EXTRA_SESSION_ID, -1) != state.sessionId) return false
        if (intent.hasExtra(EXTRA_REVISION) && intent.getLongExtra(EXTRA_REVISION, -1) != store.transitionRevision()) return false
        val token = intent.getStringExtra(EXTRA_REMINDER_TOKEN)
        return token == null || store.due()?.let { store.reminderToken(it.kind) == token } == true
    }

    private fun handleAction(action: String) {
        val state = store.read()
        when (action) {
            ACTION_PAUSE -> if (state.mode == FocusMode.FOCUSING) executeRemoteAction(state, action)
            ACTION_RESUME -> if (state.mode == FocusMode.PAUSED) executeRemoteAction(state, action)
            ACTION_END -> if (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED)) executeRemoteAction(state, action)
            ACTION_END_REST -> if (state.mode == FocusMode.REST) {
                store.write(FocusRuntimeState())
                message = "休息已结束"
                changed()
            }
            ACTION_SNOOZE -> {
                if (store.due() == null) return
                if (state.mode == FocusMode.PAUSED) store.snoozePaused(System.currentTimeMillis())
                else if (state.mode == FocusMode.ENDED) store.snoozeEnded(System.currentTimeMillis())
                message = "已设置 5 分钟后再提醒"
                dismissSurfaces()
                changed()
            }
            ACTION_CLOSE_REMINDERS -> {
                if (store.due() == null) return
                store.closeReminders()
                message = "本次提醒已关闭"
                dismissSurfaces()
                changed()
            }
            ACTION_DISMISS, ACTION_OPEN_FROM_REMINDER -> {
                store.due()?.kind?.let { kind ->
                    if (kind == ReminderKind.PAUSED) store.dismissPaused() else store.acknowledgeEnded(kind.endedIndex)
                }
                dismissSurfaces()
                changed()
            }
        }
        applyState()
    }

    private fun applyState() {
        handler.removeCallbacks(tick)
        val state = store.read()
        val now = System.currentTimeMillis()
        val scheduled = store.islandContext().enabled(now)
        if (!scheduled && (state.mode == FocusMode.IDLE ||
            state.mode == FocusMode.SETTLED && !state.summaryVisible(System.currentTimeMillis()) ||
            state.mode == FocusMode.ENDED && store.endedAcknowledgedCount() >= 3 && !state.summaryVisible(System.currentTimeMillis()))) {
            stopRuntime()
            return
        }
        if (!publish(state)) return
        checkReminder()
        if (state.mode in setOf(FocusMode.IDLE, FocusMode.SETTLED) &&
            !state.summaryVisible(now) && store.islandContext().countdown(state, store.due(now), now) == null) {
            // Keep the authenticated schedule fresh without a per-second
            // wake lock while there is no clock on the island.
            releaseWakeLock()
            handler.postDelayed(tick, (store.islandContext().nextBoundary(now) - now).coerceIn(50L, 15_000L))
            return
        }
        val lock = wakeLock ?: getSystemService(PowerManager::class.java).newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK, "$packageName:focus-runtime").also {
            it.setReferenceCounted(false)
            wakeLock = it
        }
        if (!lock.isHeld) lock.acquire(10 * 60_000L)
        handler.postDelayed(tick, 1_000L)
    }

    private fun publish(state: FocusRuntimeState): Boolean {
        val publishStartedAt = SystemClock.elapsedRealtime()
        val now = System.currentTimeMillis()
        val due = store.due(now)
        val countdown = store.islandContext().countdown(state, due, now)
        val visible = store.atomicEnabled() && (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.REST) ||
            state.summaryVisible(now) || due != null || countdown != null)
        val token = due?.let { store.reminderToken(it.kind, now) }.orEmpty()
        val atomic = publisher.usesAtomicIsland()
        val presentedAt = store.islandPresentedAt(token)
        val presentation = AtomicRefreshPolicy.reminderPresentation(visible, atomic, token,
            presentedAt, store.islandCollapseSent(token), now)
        val forceShowCard = presentation.expanded ?: if (refreshPolicy.reminderCleared(token)) false else null
        val firstPresentation = presentation.first
        val clockBucket = countdown?.remaining(now) ?: when (state.mode) {
            FocusMode.PAUSED -> (now - state.pausedAtEpochMs).coerceAtLeast(0) / 1000
            FocusMode.REST -> state.restElapsed(now)
            FocusMode.FOCUSING -> state.elapsedNow(now)
            else -> if (due != null) (now - state.endedAtEpochMs).coerceAtLeast(0) / 1000 else 0
        }
        val stateKey = AtomicRefreshPolicy.StateKey.from(state, visible, atomic, publisher.palette(state).accent,
            token, retryAction, store.transitionRevision(), countdown?.key.orEmpty(),
            token.isNotBlank() && presentedAt != null && now - presentedAt >= AtomicRefreshPolicy.REMINDER_HOLD_MS)
        val elapsedNow = SystemClock.elapsedRealtime()
        if (!refreshPolicy.shouldPublish(stateKey, clockBucket, elapsedNow, !foregroundStarted)) return true
        val stateChanged = refreshPolicy.stateChanged(stateKey)
        val operation = when {
            !visible -> OriginOsAtomicPublisher.AtomicOperation.END
            !islandVisible -> OriginOsAtomicPublisher.AtomicOperation.CREATE
            else -> OriginOsAtomicPublisher.AtomicOperation.UPDATE
        }
        return try {
            val notification = publisher.liveNotification(state, operation, retryAction = retryAction,
                forceShowCard = forceShowCard, now = now, atomicAvailable = atomic,
                showSeconds = if (firstPresentation) 15 else 0, countdown = countdown)
            if (!foregroundStarted) startForeground(OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID, notification)
            else notifications.notify(OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID, notification)
            foregroundStarted = true
            islandVisible = visible
            refreshPolicy.published(stateKey, clockBucket, elapsedNow)
            if (stateChanged) Log.i("FocusService", "Notification state=${state.mode} operation=${operation.name} " +
                "publishMs=${SystemClock.elapsedRealtime() - publishStartedAt}")
            if (firstPresentation) { store.markIslandPresented(token, now); store.markPresented(token) }
            if (presentation.collapse) store.markIslandCollapsed(token)
            true
        } catch (error: Exception) {
            Log.w("FocusService", "Foreground promotion failed", error)
            stopRuntime()
            false
        }
    }

    private fun maybeSyncServer() {
        val now = System.currentTimeMillis()
        if (busy || syncing || now - lastSyncAt < 15_000 || destroyed ||
            store.read().mode == FocusMode.IDLE && !store.islandContext().enabled(now)) return
        lastSyncAt = now
        syncing = true
        val requested = store.read()
        val revision = store.transitionRevision()
        val requestedAt = SystemClock.elapsedRealtime()
        network.synchronize { generation ->
            val heartbeat = if (requested.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED) && requested.sessionId > 0)
                FocusApi.heartbeat(requested) else null
            val response = FocusApi.fetchState(requested)
            val responseAt = SystemClock.elapsedRealtime()
            handler.post {
                syncing = false
                if (destroyed || busy || !network.isCurrentSync(generation) ||
                    !FocusStateReducer.canApplyResponse(requested, store.read(), revision, store.transitionRevision())) return@post
                if (heartbeat?.status in setOf(401, 403) || response.status in setOf(401, 403)) {
                    clear(this)
                    changed()
                    return@post
                }
                if (response.successful && response.state != null) {
                    response.islandContext?.let(store::writeIslandContext)
                    val updated = FocusStateReducer.reduce(store.read(), response.state, store.endedAcknowledgedCount())
                    val transition = !FocusStateReducer.canApplyResponse(store.read(), updated)
                    store.write(updated)
                    if (transition) {
                        Log.i("FocusService", "Remote transition=${updated.mode} requestMs=${responseAt - requestedAt} " +
                            "handoffMs=${SystemClock.elapsedRealtime() - responseAt}")
                        message = ""; retryAction = ""; changed()
                    }
                    applyState()
                }
            }
        }
    }

    private fun executeRemoteAction(state: FocusRuntimeState, action: String) {
        if (busy || state.sessionId <= 0) return
        busy = true
        message = ""
        retryAction = ""
        val revision = store.transitionRevision()
        val requestedAt = SystemClock.elapsedRealtime()
        Log.i("FocusService", "Action=$action requested")
        changed()
        network.act {
            val networkStartedAt = SystemClock.elapsedRealtime()
            Log.i("FocusService", "Action=$action queueMs=${networkStartedAt - requestedAt}")
            val result = when (action) {
                ACTION_PAUSE -> FocusApi.setPaused(state, true)
                ACTION_RESUME -> FocusApi.setPaused(state, false)
                else -> FocusApi.end(state)
            }
            // A timeout may have committed. Read back before offering retry.
            val reconciled = if (!result.successful) FocusApi.fetchState(state) else null
            val responseAt = SystemClock.elapsedRealtime()
            Log.i("FocusService", "Action=$action responseMs=${responseAt - networkStartedAt} status=${result.status} " +
                "reconciled=${reconciled != null}")
            handler.post {
                busy = false
                if (destroyed) return@post
                if (!FocusStateReducer.canApplyResponse(state, store.read(), revision, store.transitionRevision())) {
                    changed(); applyState(); return@post
                }
                if (result.status in setOf(401, 403) || reconciled?.status in setOf(401, 403)) {
                    clear(this)
                    changed()
                    return@post
                }
                val now = System.currentTimeMillis()
                val updated = result.state ?: if (result.successful) when (action) {
                    ACTION_PAUSE -> state.copy(mode = FocusMode.PAUSED, pausedAtEpochMs = now,
                        elapsedSeconds = state.elapsedNow(now), observedAtEpochMs = now)
                    ACTION_RESUME -> state.copy(mode = FocusMode.FOCUSING, pausedAtEpochMs = 0, observedAtEpochMs = now)
                    else -> state.copy(mode = FocusMode.ENDED, endedAtEpochMs = now, pausedAtEpochMs = 0,
                        elapsedSeconds = state.elapsedNow(now), observedAtEpochMs = now)
                } else reconciled?.state?.let { FocusStateReducer.reduce(state, it, store.endedAcknowledgedCount(), now) }
                if (updated != null) store.write(updated)
                val expected = when (action) {
                    ACTION_PAUSE -> FocusMode.PAUSED
                    ACTION_RESUME -> FocusMode.FOCUSING
                    else -> FocusMode.ENDED
                }
                val outcome = FocusActionOutcome.resolve(state, updated, expected)
                message = when (outcome) {
                    FocusActionOutcome.COMPLETED -> when (action) {
                        ACTION_PAUSE -> "专注已暂停"
                        ACTION_RESUME -> "已继续专注"
                        else -> "本段专注已结束"
                    }
                    FocusActionOutcome.CHANGED_ELSEWHERE -> "状态已在其他设备更新，请返回应用查看"
                    FocusActionOutcome.UNCONFIRMED -> "操作未确认，请检查网络后重试"
                }
                retryAction = if (outcome == FocusActionOutcome.UNCONFIRMED) action else ""
                if (outcome != FocusActionOutcome.UNCONFIRMED) dismissSurfaces()
                changed()
                applyState()
                Log.i("FocusService", "Action=$action appliedMs=${SystemClock.elapsedRealtime() - responseAt} outcome=$outcome")
            }
        }
    }

    private fun checkReminder() {
        val due = store.due()
        if (due == null) { if (reminderToken.isNotEmpty()) dismissSurfaces(); return }
        val token = store.reminderToken(due.kind)
        if (publisher.usesAtomicIsland()) {
            // doc895: the same reminder is one atomic activity, not a second
            // ordinary notification. publish() requests expansion once/round.
            overlay.dismiss()
            FocusAccessibilityService.dismiss()
            notifications.cancel(OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID)
            if (reminderToken != token) { reminderToken = token; changed() }
            return
        }
        if (appVisible) {
            overlay.dismiss()
            FocusAccessibilityService.dismiss()
            notifications.cancel(OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID)
            if (reminderToken != token) { reminderToken = token; changed() }
            return
        }
        if (!store.strongReminders()) { overlay.dismiss(); FocusAccessibilityService.dismiss() }
        if (reminderToken == token && notifications.activeNotifications.any {
                it.id == OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID }) return
        val alreadyPresented = store.wasPresented(token)
        dismissSurfaces()
        reminderToken = token
        store.markPresented(token)
        notifications.notify(OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID,
            publisher.reminderNotification(due.kind, store.read(), token, alreadyPresented))
        if (store.strongReminders() && !alreadyPresented) {
            val snooze = { handleAction(ACTION_SNOOZE) }
            val open = { handleAction(ACTION_OPEN_FROM_REMINDER); openTimer() }
            val resume = { handleAction(ACTION_RESUME) }
            val close = {
                if (store.due()?.let { store.reminderToken(it.kind) } == token) handleAction(ACTION_CLOSE_REMINDERS)
            }
            overlay.show(due.kind, snooze, open, resume, close) ||
                FocusAccessibilityService.show(due.kind, snooze, open, resume, close)
        }
    }

    private fun openTimer() {
        runCatching { startActivity(Intent(this, MainActivity::class.java).addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)) }
    }

    private fun displayMessage(now: Long): String = if (retryAction.isNotBlank() || now - messageSince < 5_000) message else ""

    private fun changed() { sendBroadcast(Intent(ACTION_REFRESH_WEB).setPackage(packageName)) }

    private fun dismissSurfaces() {
        overlay.dismiss()
        FocusAccessibilityService.dismiss()
        notifications.cancel(OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID)
        reminderToken = ""
    }

    private fun releaseWakeLock() { wakeLock?.takeIf { it.isHeld }?.release(); wakeLock = null }

    private fun stopRuntime() {
        handler.removeCallbacks(tick)
        dismissSurfaces()
        releaseWakeLock()
        if (pendingStarts.isNotEmpty()) return
        stopForeground(STOP_FOREGROUND_REMOVE)
        VivoAtomicPayload.cancel(notifications, OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID)
        if (runningService === this) runningService = null
        stopSelf()
    }

    companion object {
        const val ACTION_REFRESH_WEB = "com.mutsumi.focus.REFRESH_WEB"
        const val ACTION_PAUSE = "com.mutsumi.focus.PAUSE"
        const val ACTION_RESUME = "com.mutsumi.focus.RESUME"
        const val ACTION_END = "com.mutsumi.focus.END"
        const val ACTION_END_REST = "com.mutsumi.focus.END_REST"
        const val ACTION_SNOOZE = "com.mutsumi.focus.SNOOZE"
        const val ACTION_DISMISS = "com.mutsumi.focus.DISMISS"
        const val ACTION_CLOSE_REMINDERS = "com.mutsumi.focus.CLOSE_REMINDERS"
        const val ACTION_OPEN_FROM_REMINDER = "com.mutsumi.focus.OPEN_FROM_REMINDER"
        const val EXTRA_SESSION_ID = "focus_session_id"
        const val EXTRA_REVISION = "focus_revision"
        const val EXTRA_REMINDER_TOKEN = "focus_reminder_token"
        private const val ACTION_SYNC = "com.mutsumi.focus.SYNC"
        private const val ACTION_CHECK = "com.mutsumi.focus.CHECK"
        private const val EXTRA_START_REQUEST = "focus_start_request"
        private val main = Handler(Looper.getMainLooper())
        @Volatile private var runningService: FocusService? = null
        private var nextStartRequest = 0L
        private val pendingStarts = mutableSetOf<Long>()
        private var appVisible = false

        fun sync(context: Context, state: FocusRuntimeState) = onMain {
            val store = FocusStateStore(context)
            val previous = store.read()
            store.write(state)
            if (!FocusStateReducer.canApplyResponse(previous, state)) runningService?.let { it.message = ""; it.retryAction = "" }
            if (state.mode == FocusMode.IDLE && !store.islandContext().enabled(System.currentTimeMillis())) stopAndCancel(context)
            else dispatch(context, Intent().setAction(ACTION_SYNC))
        }

        fun updateIslandContext(context: Context, schedule: IslandContext) = onMain {
            FocusStateStore(context).writeIslandContext(schedule)
            dispatch(context, Intent().setAction(ACTION_CHECK))
        }

        fun clear(context: Context) = onMain {
            FocusStateStore(context).also { it.write(FocusRuntimeState()); it.clearIslandContext() }
            stopAndCancel(context)
        }

        fun setAppVisible(context: Context, visible: Boolean) = onMain {
            appVisible = visible
            runningService?.applyState()
        }

        fun requestReminderCheck(context: Context) = onMain {
            val store = FocusStateStore(context)
            if (store.read().mode != FocusMode.IDLE || store.islandContext().enabled(System.currentTimeMillis())) dispatch(context, Intent().setAction(ACTION_CHECK))
        }

        fun action(context: Context, intent: Intent) = onMain { dispatch(context, intent) }

        fun acknowledgeFromNotification(context: Context, intent: Intent) {
            if (intent.action == ACTION_OPEN_FROM_REMINDER) action(context, Intent(intent))
        }

        fun snapshot(context: Context): String {
            val store = FocusStateStore(context)
            val state = store.read()
            val now = System.currentTimeMillis()
            val due = store.due(now)
            return JSONObject().apply {
                put("mode", state.mode.name.lowercase()); put("sessionId", state.sessionId)
                put("subject", state.subject); put("elapsedSeconds", state.elapsedNow(now))
                put("startedAtEpochMs", state.startedAtEpochMs)
                put("accountTimeZone", state.accountTimeZone); put("accountOffsetSeconds", state.accountOffsetSeconds)
                put("pausedAtEpochMs", state.pausedAtEpochMs); put("pausedSeconds", state.pausedSeconds)
                put("todayFocusSeconds", state.todayFocusSeconds); put("todaySessionCount", state.todaySessionCount)
                put("endedAtEpochMs", state.endedAtEpochMs)
                put("restStartedAtEpochMs", state.restStartedAtEpochMs); put("restTargetSeconds", state.restTargetSeconds)
                put("plannedSeconds", state.plannedSeconds); put("nextReminderAt", store.nextReminderAt(state))
                put("remindersClosed", store.remindersClosed(state))
                put("reminder", due?.kind?.name.orEmpty()); put("reminderToken", due?.let { store.reminderToken(it.kind, now) }.orEmpty())
                put("reminderRound", due?.round ?: 0)
                put("title", FocusPresentation.title(state, due, now)); put("detail", FocusPresentation.detail(state, store.nextReminderAt(state), due, now))
                put("timer", FocusPresentation.timer(state, now)); put("busy", runningService?.busy == true)
                put("message", runningService?.displayMessage(now).orEmpty()); put("retryAction", runningService?.retryAction.orEmpty())
                put("revision", store.transitionRevision())
            }.toString()
        }

        fun isBusy(): Boolean = runningService?.busy == true

        private fun dispatch(context: Context, intent: Intent) {
            val service = runningService
            if (service != null) {
                if (service.matches(intent)) service.handleAction(intent.action.orEmpty()) else service.applyState()
                return
            }
            val store = FocusStateStore(context)
            if (store.read().mode == FocusMode.IDLE && !store.islandContext().enabled(System.currentTimeMillis())) { stopAndCancel(context); return }
            val request = ++nextStartRequest
            pendingStarts.add(request)
            intent.setClass(context, FocusService::class.java).putExtra(EXTRA_START_REQUEST, request)
            try {
                if (context.startForegroundService(intent) == null) { pendingStarts.remove(request); stopAndCancel(context) }
            } catch (error: RuntimeException) {
                pendingStarts.remove(request)
                Log.w("FocusService", "Foreground start rejected", error)
                stopAndCancel(context)
            }
        }

        private fun stopAndCancel(context: Context) {
            runningService?.let { it.stopRuntime(); return }
            if (pendingStarts.isNotEmpty()) return
            val manager = context.getSystemService(NotificationManager::class.java)
            VivoAtomicPayload.cancel(manager, OriginOsAtomicPublisher.LIVE_NOTIFICATION_ID)
            manager.cancel(OriginOsAtomicPublisher.REMINDER_NOTIFICATION_ID)
        }

        private fun onMain(action: () -> Unit) {
            if (Looper.myLooper() == Looper.getMainLooper()) action() else main.post { action() }
        }
    }
}
