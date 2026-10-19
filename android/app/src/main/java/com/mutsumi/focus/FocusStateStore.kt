package com.mutsumi.focus

import android.content.Context
import android.content.SharedPreferences

class FocusStateStore internal constructor(private val preferences: SharedPreferences) {
    constructor(context: Context) : this(context.getSharedPreferences("focus_runtime", Context.MODE_PRIVATE))
    private var contextRaw: String? = null
    private var cachedContext = IslandContext()

    fun islandContext(): IslandContext {
        val raw = preferences.getString("island_context", "").orEmpty()
        if (raw != contextRaw) {
            contextRaw = raw
            cachedContext = runCatching {
                val data = org.json.JSONObject(raw)
                IslandContext.fromJson(data, data.optLong("received_at"))
            }.getOrNull() ?: IslandContext()
        }
        return cachedContext
    }

    fun writeIslandContext(context: IslandContext) {
        val raw = context.toJson()
        preferences.edit().putString("island_context", raw).apply()
        contextRaw = raw; cachedContext = context
    }

    fun clearIslandContext() {
        preferences.edit().remove("island_context").apply()
        contextRaw = ""; cachedContext = IslandContext()
    }

    fun read(): FocusRuntimeState = FocusRuntimeState(
        mode = FocusMode.fromWire(preferences.getString("mode", null)),
        sessionId = preferences.getLong("session_id", 0),
        subject = preferences.getString("subject", "").orEmpty(),
        startedAtEpochMs = preferences.getLong("started_at", 0),
        pausedAtEpochMs = preferences.getLong("paused_at", 0),
        endedAtEpochMs = preferences.getLong("ended_at", 0),
        elapsedSeconds = preferences.getLong("elapsed_seconds", 0),
        pausedSeconds = preferences.getLong("paused_seconds", 0),
        todayFocusSeconds = preferences.getLong("today_focus_seconds", 0),
        todaySessionCount = preferences.getInt("today_session_count", 0),
        accountTimeZone = preferences.getString("account_time_zone", "").orEmpty(),
        accountOffsetSeconds = preferences.getInt("account_offset_seconds", 28_800),
        plannedSeconds = preferences.getLong("planned_seconds", 0),
        focusItemId = preferences.getLong("focus_item_id", 0),
        restStartedAtEpochMs = preferences.getLong("rest_started_at", 0),
        restTargetSeconds = preferences.getLong("rest_target_seconds", 0),
        observedAtEpochMs = preferences.getLong("observed_at", System.currentTimeMillis()),
        baseUrl = BuildConfig.DASHBOARD_URL.trimEnd('/'),
    )

    fun write(state: FocusRuntimeState) {
        val previous = read()
        preferences.edit()
            .putString("mode", state.mode.name.lowercase())
            .putLong("session_id", state.sessionId)
            .putString("subject", state.subject)
            .putLong("started_at", state.startedAtEpochMs)
            .putLong("paused_at", state.pausedAtEpochMs)
            .putLong("ended_at", state.endedAtEpochMs)
            .putLong("elapsed_seconds", state.elapsedSeconds)
            .putLong("paused_seconds", state.pausedSeconds)
            .putLong("today_focus_seconds", state.todayFocusSeconds)
            .putInt("today_session_count", state.todaySessionCount)
            .putString("account_time_zone", state.accountTimeZone)
            .putInt("account_offset_seconds", state.accountOffsetSeconds)
            .putLong("planned_seconds", state.plannedSeconds)
            .putLong("focus_item_id", state.focusItemId)
            .putLong("rest_started_at", state.restStartedAtEpochMs)
            .putLong("rest_target_seconds", state.restTargetSeconds)
            .putLong("observed_at", state.observedAtEpochMs)
            .putString("base_url", state.baseUrl)
            .also { editor ->
                if (!FocusStateReducer.canApplyResponse(previous, state)) {
                    editor.putLong("transition_revision", transitionRevision() + 1)
                }
                if (previous.sessionId != state.sessionId || previous.mode != state.mode ||
                    previous.pausedAtEpochMs != state.pausedAtEpochMs || previous.endedAtEpochMs != state.endedAtEpochMs) {
                    editor.putLong("paused_snooze_until", 0)
                    editor.putBoolean("paused_dismissed", false)
                    editor.putString("presented_reminder", "")
                    editor.putString("island_presented_reminder", "")
                    editor.remove("island_presented_at").remove("island_collapsed_reminder")
                    editor.putLong("ended_snooze_until", 0)
                    if (previous.sessionId != state.sessionId || previous.mode != state.mode)
                        editor.putInt("ended_acknowledged", 0)
                }
                if (state.mode != FocusMode.ENDED) editor.putInt("ended_acknowledged", 0)
            }
            .apply()
    }

    fun transitionRevision(): Long = preferences.getLong("transition_revision", 0)

    fun pausedSnoozeUntil(): Long = preferences.getLong("paused_snooze_until", 0)

    fun snoozePaused(nowEpochMs: Long) {
        preferences.edit().putLong("paused_snooze_until", nowEpochMs + ReminderPolicy.PAUSED_DELAY_MS)
            .putBoolean("paused_dismissed", false).apply()
    }

    fun pausedDismissed(): Boolean = preferences.getBoolean("paused_dismissed", false)
    fun dismissPaused() { preferences.edit().putBoolean("paused_dismissed", true).apply() }
    fun closeReminders(now: Long = System.currentTimeMillis()) {
        openingReminderState(now)?.let { acknowledgeOpening(it.endedAtEpochMs, 3); return }
        when (read().mode) {
            FocusMode.PAUSED -> dismissPaused()
            FocusMode.ENDED -> acknowledgeEnded(3)
            else -> Unit
        }
    }
    fun remindersClosed(state: FocusRuntimeState = read()): Boolean = when (state.mode) {
        FocusMode.PAUSED -> pausedDismissed()
        FocusMode.ENDED -> endedAcknowledgedCount() >= 3
        else -> false
    }
    fun endedSnoozeUntil(): Long = preferences.getLong("ended_snooze_until", 0)
    fun snoozeEnded(nowEpochMs: Long) {
        openingReminderState(nowEpochMs)?.let {
            preferences.edit().putLong("opening_snooze_anchor", it.endedAtEpochMs)
                .putLong("opening_snooze_until", nowEpochMs + ReminderPolicy.PAUSED_DELAY_MS).apply()
            return
        }
        preferences.edit().putLong("ended_snooze_until", nowEpochMs + ReminderPolicy.PAUSED_DELAY_MS).apply()
    }
    fun nextReminderAt(state: FocusRuntimeState = read()): Long {
        val now = System.currentTimeMillis()
        val opening = openingReminderState(now)
        if (opening != null) {
            if (islandContext().countdown(state, null, now)?.kind != IslandContext.Countdown.Kind.WAITING) return 0
            return ReminderPolicy.nextAt(opening, 0, openingAcknowledged(opening.endedAtEpochMs), false, openingSnooze(opening.endedAtEpochMs))
        }
        return ReminderPolicy.nextAt(state, pausedSnoozeUntil(), endedAcknowledgedCount(), pausedDismissed(), endedSnoozeUntil())
    }
    private fun openingReminderState(now: Long): FocusRuntimeState? {
        val state = read()
        val display = islandContext().openingWait(state, now) ?: return null
        return state.copy(mode = FocusMode.ENDED, endedAtEpochMs = display.end, elapsedSeconds = 0)
    }
    fun reminderState(now: Long): FocusRuntimeState = openingReminderState(now) ?: read()
    private fun openingAcknowledged(anchor: Long): Int = if (preferences.getLong("opening_ack_anchor", 0) == anchor)
        preferences.getInt("opening_acknowledged", 0) else 0
    private fun openingSnooze(anchor: Long): Long = if (preferences.getLong("opening_snooze_anchor", 0) == anchor)
        preferences.getLong("opening_snooze_until", 0) else 0
    private fun acknowledgeOpening(anchor: Long, index: Int) {
        preferences.edit().putLong("opening_ack_anchor", anchor)
            .putInt("opening_acknowledged", ReminderPolicy.acknowledgedCount(openingAcknowledged(anchor), index)).apply()
    }
    fun due(now: Long = System.currentTimeMillis()): DueReminder? {
        val opening = openingReminderState(now)
        if (opening != null) {
            if (islandContext().countdown(read(), null, now)?.kind != IslandContext.Countdown.Kind.WAITING) return null
            return ReminderPolicy.due(opening, now, 0, openingAcknowledged(opening.endedAtEpochMs),
                endedSnoozeUntilEpochMs = openingSnooze(opening.endedAtEpochMs))
        }
        return ReminderPolicy.due(read(), now, pausedSnoozeUntil(), endedAcknowledgedCount(), pausedDismissed(), endedSnoozeUntil())
    }
    fun reminderToken(kind: ReminderKind, now: Long = System.currentTimeMillis()): String {
        openingReminderState(now)?.let { return "opening:${it.endedAtEpochMs}:${kind.name}:${openingSnooze(it.endedAtEpochMs)}" }
        val state = read()
        val round = if (kind == ReminderKind.PAUSED) due(now)?.round ?: 0 else kind.endedIndex
        return "${state.sessionId}:${state.pausedAtEpochMs}:${state.endedAtEpochMs}:${kind.name}:${nextReminderAt(state)}:$round"
    }
    fun wasPresented(token: String): Boolean = preferences.getString("presented_reminder", "") == token
    fun markPresented(token: String) { preferences.edit().putString("presented_reminder", token).apply() }
    fun wasIslandPresented(token: String): Boolean = preferences.getString("island_presented_reminder", "") == token
    fun islandPresentedAt(token: String): Long? = if (wasIslandPresented(token)) preferences.getLong("island_presented_at", 0) else null
    fun islandCollapseSent(token: String): Boolean = preferences.getString("island_collapsed_reminder", "") == token
    fun markIslandPresented(token: String, now: Long = System.currentTimeMillis()) {
        preferences.edit().putString("island_presented_reminder", token).putLong("island_presented_at", now)
            .remove("island_collapsed_reminder").apply()
    }
    fun markIslandCollapsed(token: String) { preferences.edit().putString("island_collapsed_reminder", token).apply() }
    fun nextAtomicRecord(): Int {
        val next = (preferences.getInt("atomic_record", 0).toLong() + 1).coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
        // Persist before notify so a process restart cannot send a lower record.
        @Suppress("ApplySharedPref")
        val saved = preferences.edit().putInt("atomic_record", next).commit()
        return next
    }
    fun seedAtomicRecord(existingRecord: Int) {
        if (existingRecord <= preferences.getInt("atomic_record", 0)) return
        @Suppress("ApplySharedPref")
        val saved = preferences.edit().putInt("atomic_record", existingRecord).commit()
    }
    fun strongReminders(): Boolean = preferences.getBoolean("strong_reminders", false)
    fun setStrongReminders(enabled: Boolean) { preferences.edit().putBoolean("strong_reminders", enabled).apply() }
    fun atomicEnabled(): Boolean = preferences.getBoolean("atomic_enabled", true)
    fun setAtomicEnabled(enabled: Boolean) { preferences.edit().putBoolean("atomic_enabled", enabled).apply() }

    fun endedAcknowledgedCount(): Int = preferences.getInt("ended_acknowledged", 0)

    fun acknowledgeEnded(index: Int, now: Long = System.currentTimeMillis()) {
        openingReminderState(now)?.let { acknowledgeOpening(it.endedAtEpochMs, index); return }
        preferences.edit().putInt("ended_acknowledged", ReminderPolicy.acknowledgedCount(endedAcknowledgedCount(), index)).apply()
    }

    fun onboardingSeen(): Boolean = preferences.getBoolean("onboarding_seen", false)

    fun setOnboardingSeen() {
        preferences.edit().putBoolean("onboarding_seen", true).apply()
    }

    fun lastPageUrl(): String? = preferences.getString("last_page_url", null)

    fun setLastPageUrl(url: String) {
        preferences.edit().putString("last_page_url", url).apply()
    }
}
