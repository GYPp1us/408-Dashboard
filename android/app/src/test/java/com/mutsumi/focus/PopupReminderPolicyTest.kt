package com.mutsumi.focus

import java.time.LocalTime
import java.time.OffsetDateTime
import kotlin.random.Random
import org.junit.Assert.*
import org.junit.Test

class PopupReminderPolicyTest {
    private fun at(time: String) = OffsetDateTime.parse("2026-11-16T$time+08:00").toInstant().toEpochMilli()
    private val schedule = IslandContext(sessions = listOf(IslandContext.Session(LocalTime.parse("08:30"), LocalTime.parse("11:40")),
        IslandContext.Session(LocalTime.parse("13:30"), LocalTime.parse("22:45"))))

    @Test fun `first five minutes and final minute have their own boundaries`() {
        val start = at("09:00:00")
        val paused = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = start, sessionId = 4)
        fun window(time: String) = PopupReminderPolicy.window(paused, schedule, at(time), 0, 12, 20)!!
        assertTrue(window("09:04:59").edge)
        assertFalse(window("09:05:00").edge)
        assertFalse(window("09:10:59").edge)
        assertTrue(window("09:11:00").edge)
        assertFalse(window("09:11:59").due)
        assertTrue(window("09:12:00").due)
        val active = paused.copy(mode = FocusMode.FOCUSING, startedAtEpochMs = start)
        assertTrue(PopupReminderPolicy.window(active, schedule, at("09:04:00"), 0, 12, 20)!!.edge)
        assertFalse(PopupReminderPolicy.window(active, schedule, at("09:50:00"), 0, 12, 20)!!.due)
        assertFalse(PopupReminderPolicy.window(paused, schedule, at("09:50:00"), 0, 0, 20)!!.due)
    }

    @Test fun `lunch suppresses ended reminder and reopening starts a fresh wait`() {
        val ended = FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = at("11:27:00"))
        fun window(time: String) = PopupReminderPolicy.window(ended, schedule, at(time), 0, 12, 20)
        assertNull(window("12:40:00"))
        assertFalse(window("13:30:00")!!.due)
        assertTrue(window("13:49:00")!!.edge)
        assertTrue(window("13:50:00")!!.due)
        assertNull(window("22:45:00"))
    }

    @Test fun `muting gates all popup phases and does not immediately replay old time`() {
        val paused = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = at("09:00:00"))
        val until = at("09:45:00")
        fun window(time: String) = PopupReminderPolicy.window(paused, schedule, at(time), until, 12, 20)
        assertNull(window("09:44:59"))
        assertFalse(window("09:45:00")!!.due)
        assertTrue(window("09:56:00")!!.edge)
        assertTrue(window("09:57:00")!!.due)
    }

    @Test fun `question rotation avoids same question and preserves answer after shuffle`() {
        val question = ReminderQuestion("custom", listOf("incorrect 1", "correct", "incorrect 2"), 1)
        val random = Random(8)
        var previous: ReminderQuestion? = null
        repeat(75) {
            val result = ReminderQuestions.next(listOf(question), previous, random)
            assertNotEquals(previous?.body, result.body)
            val original = (listOf(question) + ReminderQuestions.builtIn).single { it.body == result.body }
            assertEquals(original.options[original.answer], result.options[result.answer])
            previous = result
        }
    }

    @Test fun `common power series formula retains signs and superscripts`() {
        val fraction = ReminderMath.fraction("\\lim_{x\\to0} \\frac{e^x-e^{-x}}{x}")!!
        assertEquals("eˣ−e⁻ˣ", ReminderMath.symbols(fraction.second))
        assertEquals("x", ReminderMath.symbols(fraction.third))
        assertEquals("√(1+x)", ReminderMath.symbols("\\sqrt{1+x}"))
    }
}
