package com.mutsumi.focus

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ReminderPolicyTest {
    private val minute = 60_000L

    @Test
    fun `paused focus becomes due after five minutes`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = 10 * minute)

        assertNull(ReminderPolicy.due(state, 15 * minute - 1, 0, 0))
        assertEquals(ReminderKind.PAUSED, ReminderPolicy.due(state, 15 * minute, 0, 0)?.kind)
    }

    @Test
    fun `paused acknowledgement snoozes for another five minutes`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = minute)
        val snoozeUntil = 20 * minute

        assertNull(ReminderPolicy.due(state, snoozeUntil - 1, snoozeUntil, 0))
        assertEquals(ReminderKind.PAUSED, ReminderPolicy.due(state, snoozeUntil, snoozeUntil, 0)?.kind)
    }

    @Test
    fun `ended focus emits fifteen thirty and sixty minute reminders`() {
        val state = FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = 100 * minute)

        assertNull(ReminderPolicy.due(state, 115 * minute - 1, 0, 0))
        assertEquals(ReminderKind.ENDED_15, ReminderPolicy.due(state, 115 * minute, 0, 0)?.kind)
        assertEquals(ReminderKind.ENDED_30, ReminderPolicy.due(state, 130 * minute, 0, 1)?.kind)
        assertEquals(ReminderKind.ENDED_60, ReminderPolicy.due(state, 160 * minute, 0, 2)?.kind)
        assertNull(ReminderPolicy.due(state, 200 * minute, 0, 3))
    }

    @Test
    fun `focus rest and idle never trigger reminder`() {
        listOf(FocusMode.FOCUSING, FocusMode.REST, FocusMode.IDLE).forEach { mode ->
            assertNull(ReminderPolicy.due(FocusRuntimeState(mode = mode), Long.MAX_VALUE, 0, 0))
        }
    }
}
