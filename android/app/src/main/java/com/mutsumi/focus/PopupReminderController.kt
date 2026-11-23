package com.mutsumi.focus

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import android.view.MotionEvent

internal class PopupReminderController(private val context: Context) {
    private val prefs = PopupReminderStore(context)
    private val manager = context.getSystemService(NotificationManager::class.java)
    private val screen = context.getSystemService(PowerManager::class.java)
    private val lockScreen = context.getSystemService(KeyguardManager::class.java)
    private val edge = ReminderEdgeWindow(context) { FocusService.reminderSettingsChanged(context) }
    private var lastLaunch: Long? = null
    private var fallbackShowing = false
    var nextUpdateAt = Long.MAX_VALUE
        private set

    fun open(challenge: Boolean, duration: Int = 0) {
        runCatching { context.startActivity(ReminderActivity.intent(context, challenge, duration)) }
    }

    private fun edgeDismiss() { edge.dismiss() }

    fun trackDashboardEdge(event: MotionEvent): Boolean = edge.trackDashboardTouch(event)

    fun update(state: FocusRuntimeState, schedule: IslandContext, now: Long, accent: Int, appVisible: Boolean) {
        val window = if (prefs.enabled) PopupReminderPolicy.window(state, schedule, now,
            prefs.muteUntil, prefs.pauseMinutes, prefs.idleMinutes) else null
        window?.let { prefs.beginPhase(it.key) }
        nextUpdateAt = window?.dueAt?.let { due ->
            when { now < due - PopupReminderPolicy.LEAD_MS -> due - PopupReminderPolicy.LEAD_MS
                now < due -> due
                else -> Long.MAX_VALUE }
        } ?: Long.MAX_VALUE
        val interactive = screen.isInteractive && !lockScreen.isKeyguardLocked
        if (prefs.pending.isNotBlank() && (window == null || prefs.pending != window.key || !window.due)) {
            prefs.resolve(); ReminderActivity.resolved(); lastLaunch = null
        }
        if (window?.due == true && prefs.pending.isBlank()) {
            prefs.trigger(window.key)
            lastLaunch = null
        }
        val pending = prefs.pending.isNotBlank()
        val surfaceKey = window?.key?.takeIf { !pending && interactive && !ReminderActivity.visible() }
        edge.update(surfaceKey, if (window?.imminent == true) PopupReminderPolicy.IMMINENT_COLOR else PopupReminderPolicy.WAITING_COLOR, accent)
        if (!pending || ReminderActivity.visible() || (prefs.returning && appVisible)) {
            clearFallback()
            return
        }
        val elapsed = SystemClock.elapsedRealtime()
        val mayLaunch = interactive && (appVisible || Settings.canDrawOverlays(context))
        val waitForActivity = mayLaunch && (lastLaunch == null || elapsed - lastLaunch!! < 2_000)
        if (mayLaunch && (lastLaunch == null || elapsed - lastLaunch!! >= 7_000)) {
            lastLaunch = elapsed
            open(challenge = false)
        }
        if (!fallbackShowing && !waitForActivity) {
            val pi = PendingIntent.getActivity(context, 31, ReminderActivity.intent(context),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "弹出式专注提醒", NotificationManager.IMPORTANCE_HIGH))
            val title = if (state.mode == FocusMode.PAUSED) "准备好，继续专注" else "回到下一段专注"
            val notification = Notification.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_notification)
                .setColor(accent).setContentTitle(title).setContentText("待处理 · 点按回到提醒")
                .setVisibility(Notification.VISIBILITY_PRIVATE).setContentIntent(pi).setOnlyAlertOnce(true).build()
            if (PermissionStatus.notifications(context)) runCatching { manager.notify(NOTIFICATION, notification) }.onSuccess { fallbackShowing = true }
        }
    }

    fun clearSurfaces() { edgeDismiss(); clearFallback() }

    private fun clearFallback() {
        if (fallbackShowing) manager.cancel(NOTIFICATION)
        fallbackShowing = false
    }

    companion object {
        private const val CHANNEL = "focus_popup_v1"
        const val NOTIFICATION = 4082
        fun cancel(context: Context) = context.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION)
    }
}
