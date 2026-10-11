package com.mutsumi.focus

enum class FocusActionOutcome {
    COMPLETED, CHANGED_ELSEWHERE, UNCONFIRMED;

    companion object {
        fun resolve(requested: FocusRuntimeState, actual: FocusRuntimeState?, expectedMode: FocusMode): FocusActionOutcome {
            if (actual == null) return UNCONFIRMED
            if (actual.sessionId == requested.sessionId &&
                (actual.mode == expectedMode || expectedMode == FocusMode.ENDED && actual.mode == FocusMode.SETTLED)) return COMPLETED
            return if (FocusStateReducer.canApplyResponse(requested, actual)) UNCONFIRMED else CHANGED_ELSEWHERE
        }
    }
}
