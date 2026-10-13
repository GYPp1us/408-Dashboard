package com.mutsumi.focus

/** State changes publish immediately; only clock-only updates wait for the next second. */
class AtomicRefreshPolicy {
    data class ReminderPresentation(val expanded: Boolean, val first: Boolean)
    companion object {
        fun reminderPresentation(visible: Boolean, atomicAvailable: Boolean, token: String, alreadyPresented: Boolean): ReminderPresentation {
            val expanded = visible && atomicAvailable && token.isNotBlank()
            return ReminderPresentation(expanded, expanded && !alreadyPresented)
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
    ) {
        companion object {
            fun from(state: FocusRuntimeState, visible: Boolean, atomicAvailable: Boolean, accent: Int,
                     reminderToken: String, retryAction: String, transitionRevision: Long): StateKey {
                val live = state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.REST)
                // Re-anchoring a live clock after a heartbeat is not a new state.
                // Settlement corrections, targets, anchors, themes and rounds are.
                val content = state.copy(observedAtEpochMs = 0,
                    elapsedSeconds = if (live) 0 else state.elapsedSeconds,
                    pausedSeconds = if (live) 0 else state.pausedSeconds,
                    todayFocusSeconds = if (live) 0 else state.todayFocusSeconds,
                    todaySessionCount = if (live) 0 else state.todaySessionCount)
                return StateKey(content, visible, atomicAvailable, accent, reminderToken, retryAction, transitionRevision)
            }
        }
    }

    private var lastPublishedAt = Long.MIN_VALUE
    private var lastState: StateKey? = null
    private var lastClockSeconds = 0L

    fun stateChanged(state: StateKey): Boolean = state != lastState

    fun shouldPublish(state: StateKey, clockSeconds: Long, nowElapsedMs: Long, foregroundRequired: Boolean): Boolean {
        if (foregroundRequired || stateChanged(state)) return true
        if (clockSeconds == lastClockSeconds) return false
        return nowElapsedMs - lastPublishedAt >= 1_000L
    }

    fun published(state: StateKey, clockSeconds: Long, nowElapsedMs: Long) {
        lastState = state
        lastClockSeconds = clockSeconds
        lastPublishedAt = nowElapsedMs
    }
}
