package com.mutsumi.focus

object FocusStateReducer {
    fun reduce(
        previous: FocusRuntimeState,
        incoming: FocusRuntimeState,
        endedAcknowledgedCount: Int,
        nowEpochMs: Long = System.currentTimeMillis(),
    ): FocusRuntimeState {
        if (incoming.mode != FocusMode.IDLE) return incoming
        if (previous.mode == FocusMode.ENDED && endedAcknowledgedCount < 3) return previous
        if (previous.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED)) {
            return previous.copy(
                mode = FocusMode.ENDED,
                pausedAtEpochMs = 0,
                endedAtEpochMs = nowEpochMs,
                elapsedSeconds = previous.elapsedNow(nowEpochMs),
                observedAtEpochMs = nowEpochMs,
            )
        }
        return incoming
    }
}
