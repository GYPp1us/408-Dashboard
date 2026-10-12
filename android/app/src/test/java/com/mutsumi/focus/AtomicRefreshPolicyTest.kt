package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class AtomicRefreshPolicyTest {
    private val focus = FocusRuntimeState(mode = FocusMode.FOCUSING, sessionId = 1, startedAtEpochMs = 1000)

    private fun key(state: FocusRuntimeState = focus, visible: Boolean = true, atomic: Boolean = true,
                    accent: Int = 1, token: String = "", retry: String = "", revision: Long = 1) =
        AtomicRefreshPolicy.StateKey.from(state, visible, atomic, accent, token, retry, revision)

    @Test fun `clock-only snapshots refresh every second and unchanged summaries stay quiet`() {
        for (atomic in listOf(true, false)) {
            val policy = AtomicRefreshPolicy()
            val state = key(visible = atomic, atomic = atomic)
            policy.published(state, 0, 0)
            assertFalse(policy.shouldPublish(state, 1, 999, false))
            for (second in 1..12) {
                assertTrue(policy.shouldPublish(state, second.toLong(), second * 1000L, false))
                policy.published(state, second.toLong(), second * 1000L)
            }
            assertFalse(policy.shouldPublish(state, 12, 99_000, false))
        }
    }

    @Test fun `every phase transition bypasses the clock interval even in the same millisecond`() {
        val policy = AtomicRefreshPolicy()
        policy.published(key(), 10, 1000)
        for (mode in listOf(FocusMode.PAUSED, FocusMode.FOCUSING, FocusMode.ENDED,
                            FocusMode.REST, FocusMode.SETTLED, FocusMode.IDLE)) {
            val state = key(focus.copy(mode = mode))
            assertTrue(mode.name, policy.shouldPublish(state, 0, 1000, false))
            policy.published(state, 0, 1000)
        }
    }

    @Test fun `theme reminder retry target timezone and revision changes publish immediately`() {
        for (updated in listOf(key(accent = 2), key(token = "round1"), key(retry = "resume"),
            key(focus.copy(plannedSeconds = 1500)), key(focus.copy(accountTimeZone = "UTC")),
            key(focus.copy(accountOffsetSeconds = 0)), key(revision = 2), key(atomic = false))) {
            val policy = AtomicRefreshPolicy()
            policy.published(key(), 10, 1000)
            assertTrue(policy.shouldPublish(updated, 10, 1001, false))
        }
    }

    @Test fun `summary corrections and island removal publish without waiting for a clock tick`() {
        val policy = AtomicRefreshPolicy()
        val summary = focus.copy(mode = FocusMode.SETTLED, todayFocusSeconds = 60, todaySessionCount = 1)
        policy.published(key(summary), 0, 1000)
        val corrected = key(summary.copy(todayFocusSeconds = 90, todaySessionCount = 2))
        assertTrue(policy.shouldPublish(corrected, 0, 1001, false))
        policy.published(corrected, 0, 1001)
        assertTrue(policy.shouldPublish(key(summary.copy(todayFocusSeconds = 90, todaySessionCount = 2), visible = false), 0, 1002, false))
    }

    @Test fun `heartbeat clock reanchoring does not turn half-second polls into transitions`() {
        val policy = AtomicRefreshPolicy()
        policy.published(key(), 10, 1000)
        val observed = key(focus.copy(elapsedSeconds = 11, observedAtEpochMs = 1500, pausedSeconds = 2))
        assertFalse(policy.stateChanged(observed))
        assertFalse(policy.shouldPublish(observed, 11, 1500, false))
        assertTrue(policy.shouldPublish(observed, 11, 2000, false))
    }

    @Test fun `failed publications do not consume an immediate reminder update`() {
        val policy = AtomicRefreshPolicy()
        val previous = key(focus.copy(mode = FocusMode.PAUSED))
        val round = key(focus.copy(mode = FocusMode.PAUSED), token = "round1")
        policy.published(previous, 299, 1000)
        assertTrue(policy.shouldPublish(round, 300, 1001, false))
        assertTrue(policy.shouldPublish(round, 300, 1002, false))
        policy.published(round, 300, 1002)
        assertFalse(policy.shouldPublish(round, 300, 1003, false))
        assertTrue(policy.shouldPublish(key(focus.copy(mode = FocusMode.PAUSED), token = "round2"), 600, 1003, false))
    }

    @Test fun `foreground start still discharges an identical accepted service request`() {
        val policy = AtomicRefreshPolicy()
        policy.published(key(), 10, 1000)
        assertTrue(policy.shouldPublish(key(), 10, 1001, true))
    }
}
