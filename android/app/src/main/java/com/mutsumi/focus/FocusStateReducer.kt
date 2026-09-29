package com.mutsumi.focus

object FocusStateReducer {
    /** A heartbeat's clock update is safe; a different user transition is not. */
    fun canApplyResponse(
        requested: FocusRuntimeState,
        current: FocusRuntimeState,
        requestedRevision: Long = 0,
        currentRevision: Long = 0,
    ): Boolean =
        requestedRevision == currentRevision &&
            requested.sessionId == current.sessionId && requested.mode == current.mode &&
            requested.startedAtEpochMs == current.startedAtEpochMs &&
            requested.pausedAtEpochMs == current.pausedAtEpochMs &&
            requested.endedAtEpochMs == current.endedAtEpochMs && requested.baseUrl == current.baseUrl

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
