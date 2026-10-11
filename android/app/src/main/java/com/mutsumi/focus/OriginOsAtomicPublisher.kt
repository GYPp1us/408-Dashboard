package com.mutsumi.focus

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import com.mutsumi.focus.atomic.VivoAtomicPayload

class OriginOsAtomicPublisher(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)
    private val store = FocusStateStore(context)
    private var record = 0
    data class Action(val label: String, val icon: Int, val intent: PendingIntent)

    fun ensureChannels() {
        manager.createNotificationChannel(NotificationChannel(CHANNEL_LIVE, "专注与休息实时状态", NotificationManager.IMPORTANCE_LOW).apply {
            description = "静默更新有效专注、暂停与休息计时"
            setShowBadge(false)
            enableVibration(false)
            setSound(null, null)
        })
        manager.createNotificationChannel(NotificationChannel(CHANNEL_REMINDER, "暂停和离开提醒", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "暂停满 5 分钟与离开专注 15 / 30 / 60 分钟，每阶段只提示一次"
        })
    }

    fun liveNotification(state: FocusRuntimeState, operation: AtomicOperation,
                         message: String = "", busy: Boolean = false, retryAction: String = ""): Notification {
        val now = System.currentTimeMillis()
        val due = store.due(now)
        val title = FocusPresentation.title(state, due, now)
        val detail = FocusPresentation.detail(state, store.nextReminderAt(state), due, now)
        val content = listOf(state.subject, detail, message).filter { it.isNotBlank() }.joinToString(" · ")
        val open = openIntent("details", 1)
        val actions = if (busy) listOf(Action("返回应用", R.drawable.ic_action_details, open))
            else if (retryAction.isNotBlank()) listOf(
                Action("重试", R.drawable.ic_action_resume, serviceIntent(retryAction, 8, state)),
                Action("返回应用", R.drawable.ic_action_details, open))
            else actionsFor(state, due)
        val builder = Notification.Builder(context, CHANNEL_LIVE)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(Color.rgb(185, 74, 67))
            .setContentTitle(title).setContentText(content)
            .setStyle(Notification.BigTextStyle().bigText(content))
            .setContentIntent(open).setOnlyAlertOnce(true).setOngoing(state.mode != FocusMode.IDLE)
            .setShowWhen(false).setVisibility(Notification.VISIBILITY_PUBLIC)
            .setCategory(Notification.CATEGORY_STATUS)
        if (state.mode == FocusMode.FOCUSING) builder.setUsesChronometer(true)
            .setWhen(now - state.elapsedNow(now) * 1000).setShowWhen(true)
        if (state.mode == FocusMode.REST && state.restStartedAtEpochMs > 0) builder.setUsesChronometer(true).setShowWhen(true).apply {
            if (state.restTargetSeconds > 0 && state.restElapsed(now) < state.restTargetSeconds) {
                setChronometerCountDown(true)
                setWhen(state.restStartedAtEpochMs + state.restTargetSeconds * 1000)
            } else if (state.restTargetSeconds == 0L) setWhen(state.restStartedAtEpochMs)
            else setUsesChronometer(false).setShowWhen(false)
        }
        actions.forEach { builder.addAction(Notification.Action.Builder(
            android.graphics.drawable.Icon.createWithResource(context, it.icon), it.label, it.intent).build()) }
        if (Build.VERSION.SDK_INT >= 36 && state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.REST)) {
            val progress = Notification.ProgressStyle().setStyledByProgress(true)
            if (state.mode == FocusMode.FOCUSING && state.plannedSeconds > 0) {
                progress.setProgressSegments(listOf(Notification.ProgressStyle.Segment(state.plannedSeconds.toInt())))
                    .setProgress(state.elapsedNow(now).coerceAtMost(state.plannedSeconds).toInt())
            } else progress.setProgressIndeterminate(true)
            builder.setStyle(progress).setCategory(Notification.CATEGORY_PROGRESS)
            builder.addExtras(Bundle().apply { putBoolean("android.requestPromotedOngoing", true) })
        }
        if (isVivoDevice()) {
            if (operation == AtomicOperation.CREATE) record = 0
            val extras = VivoAtomicPayload.create(context, R.drawable.ic_atomic, operation.value,
                BuildConfig.VIVO_ATOMIC_SCENE, title, content, FocusPresentation.timer(state, now), open,
                BuildConfig.VIVO_HISTORICAL_ISLAND_ONLY, ++record, "focus:${state.sessionId}")
            if (operation != AtomicOperation.END) VivoAtomicPayload.configureFocus(context, extras,
                if (state.mode == FocusMode.FOCUSING) FocusPresentation.shortName(state.subject.ifBlank { title }) else title,
                title, content + "\n" + actions.joinToString(" · ") { it.label },
                actions.map { it.icon }.toIntArray(), ArrayList(actions.map { it.intent }),
                if (state.mode == FocusMode.FOCUSING && state.plannedSeconds > 0)
                    (state.elapsedNow(now) * 100 / state.plannedSeconds).coerceIn(0, 100).toInt() else -1,
                busy, retryAction.isNotBlank())
            builder.addExtras(extras)
        }
        return builder.build()
    }

    private fun actionsFor(state: FocusRuntimeState, due: DueReminder?): List<Action> = when (state.mode) {
        FocusMode.FOCUSING -> listOf(
            Action("暂停", R.drawable.ic_action_pause, serviceIntent(FocusService.ACTION_PAUSE, 2, state)),
            Action("结束本段", R.drawable.ic_action_end, serviceIntent(FocusService.ACTION_END, 3, state)),
            Action("查看详情", R.drawable.ic_action_details, openIntent("details", 4)))
        FocusMode.PAUSED -> listOf(
            Action("继续专注", R.drawable.ic_action_resume, serviceIntent(FocusService.ACTION_RESUME, 2, state)),
            if (due != null) Action("再等 5 分钟", R.drawable.ic_action_rest, serviceIntent(FocusService.ACTION_SNOOZE, 5, state))
            else Action("查看详情", R.drawable.ic_action_details, openIntent("details", 4)),
            Action("结束本段", R.drawable.ic_action_end, serviceIntent(FocusService.ACTION_END, 3, state)))
        FocusMode.REST -> listOf(
            Action("结束休息", R.drawable.ic_action_end, serviceIntent(FocusService.ACTION_END_REST, 6, state)),
            Action("返回应用", R.drawable.ic_action_details, openIntent("details", 4)))
        FocusMode.ENDED -> listOf(
            Action("查看总结", R.drawable.ic_action_details, openIntent("summary", 4)),
            Action("选择下一段", R.drawable.ic_action_resume, openIntent("next", 7))) +
            if (due != null) listOf(Action("再等 5 分钟", R.drawable.ic_action_rest,
                serviceIntent(FocusService.ACTION_SNOOZE, 5, state))) else emptyList()
        FocusMode.SETTLED -> listOf(Action("查看今日总结", R.drawable.ic_action_details, openIntent("summary", 4)))
        FocusMode.IDLE -> listOf(Action("选择事项", R.drawable.ic_action_resume, openIntent("next", 7)))
    }

    fun reminderNotification(kind: ReminderKind, state: FocusRuntimeState, token: String, silent: Boolean): Notification {
        val open = PendingIntent.getActivity(context, 10, Intent(context, MainActivity::class.java).apply {
            action = FocusService.ACTION_OPEN_FROM_REMINDER
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            putExtra(FocusService.EXTRA_SESSION_ID, state.sessionId)
            putExtra(FocusService.EXTRA_REVISION, store.transitionRevision())
            putExtra(FocusService.EXTRA_REMINDER_TOKEN, token)
        }, FLAGS)
        val builder = Notification.Builder(context, CHANNEL_REMINDER).setSmallIcon(R.drawable.ic_notification)
            .setColor(Color.rgb(185, 74, 67)).setContentTitle(FocusPresentation.reminderTitle(kind))
            .setContentText(if (kind == ReminderKind.PAUSED) "计时仍暂停，可以继续专注，或再等 5 分钟。" else "准备好时，选择事项开始下一段。")
            .setCategory(Notification.CATEGORY_REMINDER).setContentIntent(open).setAutoCancel(false)
            .setOnlyAlertOnce(true).setShowWhen(false)
            .setDeleteIntent(serviceIntent(FocusService.ACTION_DISMISS, 11, state, token))
        if (silent) builder.setGroup("focus_reminder_silent").setGroupAlertBehavior(Notification.GROUP_ALERT_SUMMARY)
        val primary = if (kind == ReminderKind.PAUSED)
            Action("继续专注", R.drawable.ic_action_resume, serviceIntent(FocusService.ACTION_RESUME, 12, state, token))
            else Action("选择下一段", R.drawable.ic_action_resume, openIntent("next", 7))
        listOf(primary, Action("再等 5 分钟", R.drawable.ic_action_rest,
            serviceIntent(FocusService.ACTION_SNOOZE, 13, state, token)), Action("查看提醒", R.drawable.ic_action_details, open))
            .forEach { builder.addAction(Notification.Action.Builder(null, it.label, it.intent).build()) }
        return builder.build()
    }

    private fun serviceIntent(action: String, code: Int, state: FocusRuntimeState, token: String? = null): PendingIntent =
        PendingIntent.getBroadcast(context, code, Intent(context, FocusActionReceiver::class.java).apply {
            this.action = action
            putExtra(FocusService.EXTRA_SESSION_ID, state.sessionId)
            putExtra(FocusService.EXTRA_REVISION, store.transitionRevision())
            if (token != null) putExtra(FocusService.EXTRA_REMINDER_TOKEN, token)
        }, FLAGS)

    private fun openIntent(destination: String, code: Int): PendingIntent = PendingIntent.getActivity(context, code,
        Intent(context, MainActivity::class.java).apply {
            action = "com.mutsumi.focus.OPEN_$destination"
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            putExtra("focus_destination", destination)
        }, FLAGS)

    private fun isVivoDevice(): Boolean = Build.MANUFACTURER.equals("vivo", true) ||
        Build.BRAND.equals("vivo", true) || Build.BRAND.equals("iqoo", true)
    enum class AtomicOperation(val value: Int) { CREATE(0), UPDATE(1), END(2) }
    companion object {
        private const val FLAGS = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        const val CHANNEL_LIVE = "focus_live_v1"
        const val CHANNEL_REMINDER = "focus_reminder_v2"
        const val LIVE_NOTIFICATION_ID = 4080
        const val REMINDER_NOTIFICATION_ID = 4081
    }
}
