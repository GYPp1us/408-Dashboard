package com.mutsumi.focus

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle

class OriginOsAtomicPublisher(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)

    fun ensureChannels() {
        manager.createNotificationChannel(NotificationChannel(
            CHANNEL_LIVE,
            "专注实时状态",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "专注计时和 OriginOS 原子岛的本地实时状态"
            setShowBadge(false)
        })
        manager.createNotificationChannel(NotificationChannel(
            CHANNEL_REMINDER,
            "暂停和离开提醒",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "暂停 5 分钟及结束专注 15/30/60 分钟提醒"
            enableVibration(true)
        })
    }

    fun liveNotification(state: FocusRuntimeState, operation: AtomicOperation): Notification {
        val openIntent = PendingIntent.getActivity(
            context,
            1,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val title = when (state.mode) {
            FocusMode.FOCUSING -> state.subject.ifBlank { "正在专注" }
            FocusMode.PAUSED -> "专注已暂停"
            FocusMode.ENDED -> "等待回到专注"
            FocusMode.REST -> "正在休息"
            FocusMode.IDLE -> "专注已结束"
        }
        val content = when (state.mode) {
            FocusMode.FOCUSING -> "计时进行中 · 可暂停或结束"
            FocusMode.PAUSED -> "5 分钟后提醒 · 点此返回继续"
            FocusMode.ENDED -> "将在 15 / 30 / 60 分钟提醒"
            FocusMode.REST -> "休息期间不会触发提醒"
            FocusMode.IDLE -> "点此开始下一次专注"
        }
        val builder = Notification.Builder(context, CHANNEL_LIVE)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(Color.rgb(185, 74, 67))
            .setContentTitle(title)
            .setContentText(content)
            .setCategory(if (Build.VERSION.SDK_INT >= 36) Notification.CATEGORY_PROGRESS else Notification.CATEGORY_STATUS)
            .setContentIntent(openIntent)
            .setOnlyAlertOnce(true)
            .setOngoing(state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.ENDED))
            .setVisibility(Notification.VISIBILITY_PUBLIC)

        if (state.mode == FocusMode.FOCUSING) {
            builder.setUsesChronometer(true)
                .setWhen(System.currentTimeMillis() - state.elapsedNow() * 1000)
        } else {
            builder.setUsesChronometer(false)
        }

        if (state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED)) {
            val toggleAction = if (state.mode == FocusMode.PAUSED) FocusService.ACTION_RESUME else FocusService.ACTION_PAUSE
            val toggleLabel = if (state.mode == FocusMode.PAUSED) "继续" else "暂停"
            builder.addAction(Notification.Action.Builder(
                null,
                toggleLabel,
                serviceIntent(toggleAction, 2),
            ).build())
            builder.addAction(Notification.Action.Builder(
                null,
                "结束",
                serviceIntent(FocusService.ACTION_END, 3),
            ).build())
        }

        attachAndroidLiveUpdate(builder, state)
        if (isVivoDevice()) attachVivoAtomicExtras(builder, state, title, content, openIntent, operation)
        return builder.build()
    }

    fun reminderNotification(kind: ReminderKind): Notification {
        val minutes = when (kind) {
            ReminderKind.PAUSED -> 5
            ReminderKind.ENDED_15 -> 15
            ReminderKind.ENDED_30 -> 30
            ReminderKind.ENDED_60 -> 60
        }
        val title = if (kind == ReminderKind.PAUSED) "暂停已经 $minutes 分钟" else "离开专注已经 $minutes 分钟"
        return Notification.Builder(context, CHANNEL_REMINDER)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(Color.rgb(190, 54, 49))
            .setContentTitle(title)
            .setContentText("点此回到计时器；开启覆盖层权限可获得全屏滑动提醒")
            .setCategory(Notification.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(serviceIntent(FocusService.ACTION_OPEN_FROM_REMINDER, 10 + kind.ordinal))
            .build()
    }

    private fun attachVivoAtomicExtras(
        builder: Notification.Builder,
        state: FocusRuntimeState,
        title: String,
        content: String,
        clickIntent: PendingIntent,
        operation: AtomicOperation,
    ) {
        val baseInfos = Bundle().apply {
            putInt("notification.superx.baseInfos.icon", R.drawable.ic_notification)
            putString("notification.superx.baseInfos.title", title)
            putString("notification.superx.baseInfos.content", content)
        }
        val extras = Bundle().apply {
            putInt("notification.superx.operation", operation.value)
            putBoolean("notification.superx.showNotify", true)
            putInt("notification.superx.template", 1)
            putParcelable("notification.superx.clickResp", clickIntent)
            putString("notification.superx.scene", BuildConfig.VIVO_ATOMIC_SCENE)
            putBundle("notification.superx.baseInfos", baseInfos)
        }
        builder.addExtras(extras)
    }

    @Suppress("NewApi")
    @SuppressLint("WrongConstant")
    private fun attachAndroidLiveUpdate(builder: Notification.Builder, state: FocusRuntimeState) {
        if (Build.VERSION.SDK_INT < 36 || state.mode !in setOf(FocusMode.FOCUSING, FocusMode.PAUSED)) return
        builder.setStyle(Notification.ProgressStyle().setProgressIndeterminate(true).setStyledByProgress(true))
        builder.setFlag(Notification.FLAG_PROMOTED_ONGOING, true)
    }

    private fun serviceIntent(action: String, requestCode: Int): PendingIntent = PendingIntent.getService(
        context,
        requestCode,
        Intent(context, FocusService::class.java).setAction(action),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    private fun isVivoDevice(): Boolean =
        Build.MANUFACTURER.equals("vivo", true) || Build.BRAND.equals("vivo", true) || Build.BRAND.equals("iqoo", true)

    enum class AtomicOperation(val value: Int) { CREATE(0), UPDATE(1), END(2) }

    companion object {
        const val CHANNEL_LIVE = "focus_live_v1"
        const val CHANNEL_REMINDER = "focus_reminder_v1"
        const val LIVE_NOTIFICATION_ID = 4080
        const val REMINDER_NOTIFICATION_ID = 4081
    }
}
