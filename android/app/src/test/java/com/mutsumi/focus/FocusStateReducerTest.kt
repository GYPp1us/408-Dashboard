package com.mutsumi.focus

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FocusStateReducerTest {
    @Test
    fun `late server response cannot overwrite a pause end or replacement session`() {
        val requested = FocusRuntimeState(mode = FocusMode.FOCUSING, sessionId = 8, startedAtEpochMs = 100)
        assertFalse(FocusStateReducer.canApplyResponse(requested, requested.copy(mode = FocusMode.PAUSED, pausedAtEpochMs = 500)))
        assertFalse(FocusStateReducer.canApplyResponse(requested, requested.copy(mode = FocusMode.ENDED, endedAtEpochMs = 500)))
        assertFalse(FocusStateReducer.canApplyResponse(requested, requested.copy(sessionId = 9)))
        assertFalse(FocusStateReducer.canApplyResponse(requested, requested.copy(mode = FocusMode.REST)))
    }

    @Test
    fun `new pause after pause resume cycle rejects an old pending request`() {
        val requested = FocusRuntimeState(mode = FocusMode.PAUSED, sessionId = 8, pausedAtEpochMs = 100)
        assertFalse(FocusStateReducer.canApplyResponse(requested, requested.copy(pausedAtEpochMs = 500)))
    }

    @Test
    fun `focus pause focus cycle still rejects response from before the cycle`() {
        val requested = FocusRuntimeState(mode = FocusMode.FOCUSING, sessionId = 8, startedAtEpochMs = 100)
        // Mode and timestamps return to their original values after resume.
        // The persisted transition revision retains the intervening changes.
        assertFalse(FocusStateReducer.canApplyResponse(requested, requested.copy(), 2, 4))
        assertTrue(FocusStateReducer.canApplyResponse(requested, requested.copy(elapsedSeconds = 5), 4, 4))
    }

    @Test
    fun `clock refresh of the same transition accepts the authoritative response`() {
        val requested = FocusRuntimeState(mode = FocusMode.FOCUSING, sessionId = 8, elapsedSeconds = 10, observedAtEpochMs = 100)
        assertTrue(FocusStateReducer.canApplyResponse(requested, requested.copy(elapsedSeconds = 15, observedAtEpochMs = 500)))
    }

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
