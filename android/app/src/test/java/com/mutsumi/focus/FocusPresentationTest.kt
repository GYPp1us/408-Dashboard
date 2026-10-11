package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class FocusPresentationTest {
    @Test fun `paused display separates frozen effective time from pause duration`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, elapsedSeconds = 1800, pausedAtEpochMs = 1000)
        assertEquals("00:30:00", FocusPresentation.timer(state, 601_000))
        val detail = FocusPresentation.detail(state, 701_000, null, 601_000)
        assertTrue(detail.contains("暂停 00:10:00"))
        assertTrue(detail.contains("下次提醒 00:01:40 后"))
    }
    @Test fun `target rest counts down without restarting at zero`() {
        val state = FocusRuntimeState(mode = FocusMode.REST, restStartedAtEpochMs = 1000, restTargetSeconds = 900)
        assertEquals("00:05:00", FocusPresentation.timer(state, 601_000))
        assertEquals("00:00:00", FocusPresentation.timer(state, 999_000))
        assertEquals("主动休息", FocusPresentation.title(state, null, 601_000))
    }
    @Test fun `island truncation preserves whole unicode characters`() {
        val shortened = FocusPresentation.shortName("📚数学二轮错题复习")
        assertEquals("📚数学二轮…", shortened)
    }
}
