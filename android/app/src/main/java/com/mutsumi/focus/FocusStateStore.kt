package com.mutsumi.focus

import android.content.Context

class FocusStateStore(context: Context) {
    private val preferences = context.getSharedPreferences("focus_runtime", Context.MODE_PRIVATE)

    fun read(): FocusRuntimeState = FocusRuntimeState(
        mode = FocusMode.fromWire(preferences.getString("mode", null)),
        sessionId = preferences.getLong("session_id", 0),
        subject = preferences.getString("subject", "").orEmpty(),
        startedAtEpochMs = preferences.getLong("started_at", 0),
        pausedAtEpochMs = preferences.getLong("paused_at", 0),
        endedAtEpochMs = preferences.getLong("ended_at", 0),
        elapsedSeconds = preferences.getLong("elapsed_seconds", 0),
        observedAtEpochMs = preferences.getLong("observed_at", System.currentTimeMillis()),
        baseUrl = preferences.getString("base_url", BuildConfig.DASHBOARD_URL)?.trimEnd('/')
            ?: BuildConfig.DASHBOARD_URL.trimEnd('/'),
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
            .putLong("observed_at", state.observedAtEpochMs)
            .putString("base_url", state.baseUrl)
            .also { editor ->
                if (previous.sessionId != state.sessionId || previous.mode != state.mode) {
                    editor.putLong("paused_snooze_until", 0)
                    if (previous.sessionId != state.sessionId) editor.putInt("ended_acknowledged", 0)
                }
                if (state.mode != FocusMode.ENDED) editor.putInt("ended_acknowledged", 0)
            }
            .apply()
    }

    fun pausedSnoozeUntil(): Long = preferences.getLong("paused_snooze_until", 0)

    fun snoozePaused(nowEpochMs: Long) {
        preferences.edit().putLong("paused_snooze_until", nowEpochMs + ReminderPolicy.PAUSED_DELAY_MS).apply()
    }

    fun endedAcknowledgedCount(): Int = preferences.getInt("ended_acknowledged", 0)

    fun acknowledgeEnded(index: Int) {
        preferences.edit().putInt("ended_acknowledged", index.coerceIn(0, 3)).apply()
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
