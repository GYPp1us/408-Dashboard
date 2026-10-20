package com.mutsumi.focus

/** State changes publish immediately; only clock-only updates wait for the next second. */
class AtomicRefreshPolicy {
    data class ReminderPresentation(val expanded: Boolean?, val first: Boolean, val collapse: Boolean = false)
    companion object {
        const val REMINDER_HOLD_MS = 15_000L
        fun reminderPresentation(visible: Boolean, atomicAvailable: Boolean, token: String,
                                 presentedAt: Long?, collapseSent: Boolean, now: Long): ReminderPresentation {
            if (!visible || !atomicAvailable || token.isBlank()) return ReminderPresentation(null, false)
            if (presentedAt == null) return ReminderPresentation(true, true)
            if (!collapseSent && now - presentedAt >= REMINDER_HOLD_MS) return ReminderPresentation(false, false, true)
            return ReminderPresentation(null, false)
        }
    }
    data class StateKey(
        val content: FocusRuntimeState,
        val visible: Boolean,
        val atomicAvailable: Boolean,
        val accent: Int,
        val reminderToken: String,
        val retryAction: String,
        val transitionRevision: Long,
        val displayKey: String = "",
        val reminderExpired: Boolean = false,
    ) {
        companion object {
            fun from(state: FocusRuntimeState, visible: Boolean, atomicAvailable: Boolean, accent: Int,
                     reminderToken: String, retryAction: String, transitionRevision: Long,
                     displayKey: String = "", reminderExpired: Boolean = false): StateKey {
                val live = state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.REST)
                // Re-anchoring a live clock after a heartbeat is not a new state.
                // Settlement corrections, targets, anchors, themes and rounds are.
                val content = state.copy(observedAtEpochMs = 0,
                    elapsedSeconds = if (live) 0 else state.elapsedSeconds,
                    pausedSeconds = if (live) 0 else state.pausedSeconds,
                    todayFocusSeconds = if (live) 0 else state.todayFocusSeconds,
                    todaySessionCount = if (live) 0 else state.todaySessionCount)
                return StateKey(content, visible, atomicAvailable, accent, reminderToken, retryAction, transitionRevision, displayKey, reminderExpired)
            }
        }
    }

    private var lastPublishedAt = Long.MIN_VALUE
    private var lastState: StateKey? = null
    private var lastClockSeconds = 0L
    private var lastSystemTimerKey: String? = null

    fun stateChanged(state: StateKey): Boolean = state != lastState
    fun reminderCleared(token: String): Boolean = lastState?.reminderToken?.isNotBlank() == true && token.isBlank()

    fun shouldPublish(state: StateKey, clockSeconds: Long, nowElapsedMs: Long, foregroundRequired: Boolean,
                      holdingReminder: Boolean = false, systemTimerKey: String? = null, clockDirection: Int = 1): Boolean {
        if (foregroundRequired || stateChanged(state)) return true
        // On the verified ROM even an UPDATE without forceShowCard collapses
        // the expanded card. Keep its snapshot for 15s; real transitions win.
        if (holdingReminder) return false
        if (systemTimerKey != null) {
            if (systemTimerKey != lastSystemTimerKey) return true
            val projected = lastClockSeconds + clockDirection * ((nowElapsedMs - lastPublishedAt).coerceAtLeast(0) / 1000)
            return kotlin.math.abs(clockSeconds - projected) >= 2
        }
        if (clockSeconds == lastClockSeconds) return false
        return nowElapsedMs - lastPublishedAt >= 1_000L
    }

    fun published(state: StateKey, clockSeconds: Long, nowElapsedMs: Long, systemTimerKey: String? = null) {
        lastState = state
        lastClockSeconds = clockSeconds
        lastPublishedAt = nowElapsedMs
        lastSystemTimerKey = systemTimerKey
    }
}
