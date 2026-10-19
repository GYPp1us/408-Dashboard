package com.mutsumi.focus

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.text.SpannableString
import android.text.Spanned
import android.text.style.AbsoluteSizeSpan
import android.text.style.TypefaceSpan
import com.mutsumi.focus.atomic.VivoAtomicPayload

class OriginOsAtomicPublisher(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)
    private val store = FocusStateStore(context)
    private val glyphs = mutableMapOf<Pair<AtomicIslandLayout.Glyph, Int>, Icon>()

    fun ensureChannels() {
        manager.createNotificationChannel(NotificationChannel(CHANNEL_LIVE, "专注与休息实时状态", NotificationManager.IMPORTANCE_LOW).apply {
            description = "静默更新专注、暂停与休息状态"
            setShowBadge(false); enableVibration(false); setSound(null, null)
        })
        manager.createNotificationChannel(NotificationChannel(CHANNEL_REMINDER, "暂停和离开提醒", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "原子岛不可用时的暂停和离开提醒"
        })
    }

    fun usesAtomicIsland(): Boolean {
        if (!isVivoDevice() || !store.atomicEnabled() || BuildConfig.VIVO_HISTORICAL_ISLAND_ONLY) return false
        // Query only our own scene, as documented in doc896; no shell or write.
        return runCatching {
            val query = NotificationManager::class.java.getDeclaredMethod("getSceneStatus", String::class.java, String::class.java)
            query.isAccessible = true
            query.invoke(manager, context.packageName, BuildConfig.VIVO_ATOMIC_SCENE) == true
        }.getOrDefault(false)
    }

    fun palette(state: FocusRuntimeState): IslandPalette {
        val prefs = context.getSharedPreferences("focus_runtime", Context.MODE_PRIVATE)
        val name = prefs.getString("theme_palette", "clay").orEmpty()
        val group = IslandPalette.group(state.mode)
        return if (prefs.getString("theme_runtime_group", "") == group && prefs.getString("theme_runtime_palette", "") == name)
            IslandPalette(prefs.getInt("theme_runtime_accent", IslandPalette.fallback(name, state.mode).accent))
        else IslandPalette.fallback(name, state.mode)
    }

    fun liveNotification(state: FocusRuntimeState, operation: AtomicOperation, retryAction: String = "",
                         forceShowCard: Boolean? = null, now: Long = System.currentTimeMillis(),
                         atomicAvailable: Boolean = usesAtomicIsland(), showSeconds: Int = 0,
                         countdown: IslandContext.Countdown? = null): Notification {
        val due = store.due(now)
        val layout = AtomicIslandLayout.from(if (due != null) store.reminderState(now) else state,
            due, now, store.remindersClosed(state), countdown)
        val colors = palette(state)
        val home = openIntent("home", 1)
        val primary = when (layout.button.action) {
            "resume" -> serviceIntent(FocusService.ACTION_RESUME, 2, state)
            "pause" -> serviceIntent(FocusService.ACTION_PAUSE, 2, state)
            "endRest" -> serviceIntent(FocusService.ACTION_END_REST, 2, state)
            "closeReminders" -> serviceIntent(FocusService.ACTION_CLOSE_REMINDERS, 2, state,
                due?.let { store.reminderToken(it.kind, now) })
            else -> openIntent(layout.button.action, 2)
        }
        val content = if (retryAction.isNotBlank()) {
            if (layout.button.action == "closeReminders") "操作未确认，可关闭本次提醒"
            else "操作未确认，请再次点击${layout.button.label}"
        } else when (layout.template) {
            1 -> "${layout.core} · ${layout.description}"
            3 -> "${layout.leftLabel} ${layout.leftValue} · ${layout.rightLabel} ${layout.rightValue}" +
                if (layout.middleValue.isNotBlank()) " · ${layout.middleValue}" else ""
            else -> layout.subtitle
        }
        val builder = Notification.Builder(context, CHANNEL_LIVE)
            .setSmallIcon(R.drawable.ic_notification).setColor(colors.accent)
            .setContentTitle(layout.title).setContentText(content)
            .setStyle(Notification.BigTextStyle().bigText(content))
            .setContentIntent(home).setOnlyAlertOnce(true).setOngoing(state.mode != FocusMode.IDLE)
            .setShowWhen(false).setVisibility(Notification.VISIBILITY_PUBLIC).setCategory(Notification.CATEGORY_STATUS)
            .addAction(Notification.Action.Builder(null, layout.button.label, primary).build())
        // The vivo template already has a per-second clock. Running a second
        // Android chronometer / ProgressStyle can restart its compact card.
        if (!atomicAvailable && state.mode == FocusMode.FOCUSING) builder.setUsesChronometer(true)
            .setWhen(state.observedAtEpochMs / 1000 * 1000 - state.elapsedSeconds * 1000).setShowWhen(true)
        if (!atomicAvailable && state.mode == FocusMode.PAUSED && state.pausedAtEpochMs > 0) builder.setUsesChronometer(true)
            .setWhen(state.pausedAtEpochMs).setShowWhen(true)
        if (!atomicAvailable && state.mode == FocusMode.REST && state.restStartedAtEpochMs > 0) builder.setUsesChronometer(true)
            .setShowWhen(true).setWhen(state.restStartedAtEpochMs)
        if (!atomicAvailable && Build.VERSION.SDK_INT >= 36 && state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.REST)) {
            val progress = Notification.ProgressStyle().setStyledByProgress(true)
            if (state.mode == FocusMode.FOCUSING && state.plannedSeconds > 0) {
                progress.setProgressSegments(listOf(Notification.ProgressStyle.Segment(state.plannedSeconds.toInt())))
                    .setProgress(state.elapsedNow(now).coerceAtMost(state.plannedSeconds).toInt())
            } else progress.setProgressIndeterminate(true)
            builder.setStyle(progress).setCategory(Notification.CATEGORY_PROGRESS)
                .addExtras(Bundle().apply { putBoolean("android.requestPromotedOngoing", true) })
        }
        if (isVivoDevice()) {
            val extras = VivoAtomicPayload.create(context, R.drawable.ic_atomic, operation.value,
                BuildConfig.VIVO_ATOMIC_SCENE, layout.title, content, layout.rightText, home,
                BuildConfig.VIVO_HISTORICAL_ISLAND_ONLY, store.nextAtomicRecord(), "focus:${state.sessionId}")
            if (operation != AtomicOperation.END && !BuildConfig.VIVO_HISTORICAL_ISLAND_ONLY) {
                extras.putAll(wireBundle(layout.wire(forceShowCard, colors, showSeconds), primary, home, colors))
                // Keep the node stable between genuine mode changes / rounds.
                extras.putInt("notification.superx.newNode", layout.displayNode.takeIf { it != 0 }
                    ?: (state.mode.ordinal * 100_000 + (due?.round ?: 0).coerceAtMost(99_999)))
            }
            builder.addExtras(extras)
        }
        return builder.build()
    }

    private fun glyph(resource: AtomicIslandLayout.Glyph, colors: IslandPalette): Icon = glyphs.getOrPut(resource to colors.accent) {
        if (resource == AtomicIslandLayout.Glyph.BRAND) Icon.createWithResource(context, R.drawable.ic_atomic).setTint(colors.accent)
        else {
            // Padded, opaque node centers keep the progress track out of the
            // visible glyph. Cache the two small images per actual theme color.
            val bitmap = Bitmap.createBitmap(48, 48, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = colors.buttonText }
            canvas.drawCircle(24f, 24f, 12f, paint)
            paint.color = colors.accent
            if (resource == AtomicIslandLayout.Glyph.START) canvas.drawCircle(24f, 24f, 5f, paint)
            else {
                paint.style = Paint.Style.STROKE; paint.strokeWidth = 3f
                paint.strokeCap = Paint.Cap.ROUND; paint.strokeJoin = Paint.Join.ROUND
                canvas.drawPath(Path().apply { moveTo(17f, 24f); lineTo(22f, 29f); lineTo(31f, 19f) }, paint)
            }
            Icon.createWithBitmap(bitmap)
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun wireBundle(values: Map<String, Any>, primary: PendingIntent, home: PendingIntent, colors: IslandPalette): Bundle = Bundle().apply {
        values.forEach { (key, value) -> when (value) {
            is String -> if (key == "island.superx.leftInfo.content" || key == "island.superx.rightInfo.content") {
                // Keep the whole time at the front, with stable narrow numerals.
                // Only state text yields size; no ScaleX or ellipsis on time.
                val timer = value.matches(Regex("\\d+:\\d{2}"))
                val text = SpannableString(value)
                text.setSpan(AbsoluteSizeSpan(if (timer) 16 else 14, true), 0, value.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                if (timer) text.setSpan(TypefaceSpan("monospace"), 0, value.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                putCharSequence(key, text)
            } else putString(key, value)
            is Int -> putInt(key, value)
            is Boolean -> putBoolean(key, value)
            is AtomicIslandLayout.Glyph -> putParcelable(key, glyph(value, colors))
            is AtomicIslandLayout.Click -> putParcelable(key, if (value == AtomicIslandLayout.Click.PRIMARY) primary else home)
            is Map<*, *> -> putBundle(key, wireBundle(value as Map<String, Any>, primary, home, colors))
            is List<*> -> putParcelableArrayList(key, ArrayList(value.map { glyph(it as AtomicIslandLayout.Glyph, colors) }))
            else -> error("Unsupported public atomic field $key")
        } }
    }

    fun reminderNotification(kind: ReminderKind, state: FocusRuntimeState, token: String, silent: Boolean): Notification {
        val open = openIntent("home", 10)
        val label = if (kind == ReminderKind.PAUSED) "继续专注" else "开始专注"
        val primary = if (kind == ReminderKind.PAUSED) serviceIntent(FocusService.ACTION_RESUME, 12, state)
            else openIntent("next", 12)
        return Notification.Builder(context, CHANNEL_REMINDER).setSmallIcon(R.drawable.ic_notification)
            .setColor(palette(state).accent).setContentTitle(if (kind == ReminderKind.PAUSED) "暂停中" else "专注提醒")
            .setContentText(if (kind == ReminderKind.PAUSED) "第 ${store.due()?.round ?: 1} 轮提醒" else FocusPresentation.reminderTitle(kind))
            .setCategory(Notification.CATEGORY_REMINDER).setContentIntent(open).setAutoCancel(false)
            .setOnlyAlertOnce(silent).setShowWhen(false)
            .setDeleteIntent(serviceIntent(FocusService.ACTION_DISMISS, 11, state, token))
            .addAction(Notification.Action.Builder(null, label, primary).build())
            .addAction(Notification.Action.Builder(null, "关闭提醒",
                serviceIntent(FocusService.ACTION_CLOSE_REMINDERS, 13, state, token)).build())
            .apply { if (silent) setGroup("focus_reminder_silent").setGroupAlertBehavior(Notification.GROUP_ALERT_SUMMARY) }
            .build()
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
            if (destination != "home") putExtra("focus_destination", destination)
        }, FLAGS)

    private fun isVivoDevice(): Boolean = Build.MANUFACTURER.equals("vivo", true) || Build.BRAND.equals("vivo", true) || Build.BRAND.equals("iqoo", true)
    enum class AtomicOperation(val value: Int) { CREATE(0), UPDATE(1), END(2) }
    companion object {
        private const val FLAGS = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        const val CHANNEL_LIVE = "focus_live_v1"
        const val CHANNEL_REMINDER = "focus_reminder_v2"
        const val LIVE_NOTIFICATION_ID = 4080
        const val REMINDER_NOTIFICATION_ID = 4081
    }
}
