package com.mutsumi.focus

import org.junit.Assert.assertEquals
import org.junit.Test

class FocusApiStateTest {
    @Test
    fun `server pause becomes a paused runtime state`() {
        val state = FocusApi.stateFromServerFields(
            sessionId = 42,
            subject = "数学 · 二轮",
            startedAt = "2026-09-06T01:00:00+00:00",
            pausedAt = "2026-09-06T01:15:00+00:00",
            effectiveSeconds = 900,
            baseUrl = "https://platform.arcol.site",
            observedAtEpochMs = 2_000,
        )

        assertEquals(FocusMode.PAUSED, state.mode)
        assertEquals(42L, state.sessionId)
        assertEquals(900L, state.elapsedSeconds)
        assertEquals(1_788_656_400_000L, state.startedAtEpochMs)
        assertEquals(1_788_657_300_000L, state.pausedAtEpochMs)
    }

    @Test
    fun `server focus is focusing and clamps invalid elapsed time`() {
        val state = FocusApi.stateFromServerFields(
            sessionId = 7,
            subject = "408",
            startedAt = "invalid",
            pausedAt = null,
            effectiveSeconds = -1,
            baseUrl = "https://platform.arcol.site",
            observedAtEpochMs = 3_000,
        )

        assertEquals(FocusMode.FOCUSING, state.mode)
        assertEquals(0L, state.elapsedSeconds)
        assertEquals(0L, state.startedAtEpochMs)
    }
}
