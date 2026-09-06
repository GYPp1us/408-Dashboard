package com.mutsumi.focus

import org.junit.Assert.assertEquals
import org.junit.Test

class FocusStateReducerTest {
    @Test
    fun `active to idle becomes ended even when web reload loses the transition`() {
        val previous = FocusRuntimeState(
            mode = FocusMode.FOCUSING,
            sessionId = 8,
            elapsedSeconds = 120,
            observedAtEpochMs = 1_000,
        )

        val result = FocusStateReducer.reduce(previous, FocusRuntimeState(), 0, nowEpochMs = 11_000)

        assertEquals(FocusMode.ENDED, result.mode)
        assertEquals(130, result.elapsedSeconds)
        assertEquals(11_000, result.endedAtEpochMs)
    }

    @Test
    fun `unacknowledged ended schedule survives an idle web reload`() {
        val previous = FocusRuntimeState(mode = FocusMode.ENDED, sessionId = 9, endedAtEpochMs = 20_000)

        assertEquals(previous, FocusStateReducer.reduce(previous, FocusRuntimeState(), 2, 30_000))
        assertEquals(FocusMode.IDLE, FocusStateReducer.reduce(previous, FocusRuntimeState(), 3, 30_000).mode)
    }

    @Test
    fun `rest remains an explicit reminder opt out`() {
        val previous = FocusRuntimeState(mode = FocusMode.ENDED, sessionId = 9, endedAtEpochMs = 20_000)

        assertEquals(FocusMode.REST, FocusStateReducer.reduce(previous, FocusRuntimeState(mode = FocusMode.REST), 0).mode)
    }
}
