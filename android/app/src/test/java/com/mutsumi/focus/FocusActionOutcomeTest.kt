package com.mutsumi.focus

import org.junit.Assert.assertEquals
import org.junit.Test

class FocusActionOutcomeTest {
    private val paused = FocusRuntimeState(mode = FocusMode.PAUSED, sessionId = 8)

    @Test fun `timeout followed by readback confirms a committed resume`() {
        assertEquals(FocusActionOutcome.COMPLETED, FocusActionOutcome.resolve(
            paused, paused.copy(mode = FocusMode.FOCUSING), FocusMode.FOCUSING))
    }

    @Test fun `new session on another device must not claim old resume succeeded`() {
        assertEquals(FocusActionOutcome.CHANGED_ELSEWHERE, FocusActionOutcome.resolve(
            paused, paused.copy(mode = FocusMode.FOCUSING, sessionId = 9), FocusMode.FOCUSING))
    }

    @Test fun `failed resume with unchanged readback remains retryable`() {
        assertEquals(FocusActionOutcome.UNCONFIRMED, FocusActionOutcome.resolve(paused, paused, FocusMode.FOCUSING))
        assertEquals(FocusActionOutcome.UNCONFIRMED, FocusActionOutcome.resolve(paused, null, FocusMode.FOCUSING))
    }
}
