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

    @Test fun `pause has two one minute windows and starting focus has no edge`() {
        val start = at("09:00:00")
        val paused = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = start, sessionId = 4)
        fun window(time: String) = PopupReminderPolicy.window(paused, schedule, at(time), 0, 12, 20)!!
        assertTrue(window("09:00:00").edge)
        assertTrue(window("09:00:59").edge)
        assertFalse(window("09:01:00").edge)
        assertFalse(window("09:10:59").edge)
        assertTrue(window("09:11:00").edge)
        assertFalse(window("09:11:59").due)
        assertTrue(window("09:12:00").due)
        val active = paused.copy(mode = FocusMode.FOCUSING, startedAtEpochMs = start)
        assertNull(PopupReminderPolicy.window(active, schedule, at("09:00:00"), 0, 12, 20))
        assertNull(PopupReminderPolicy.window(active, schedule, at("09:01:00"), 0, 12, 20))
        assertFalse(PopupReminderPolicy.window(paused, schedule, at("09:50:00"), 0, 0, 20)!!.due)
    }

    @Test fun `actual end has an immediate minute plus an idle warning minute`() {
        val ended = FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = at("09:00:00"), sessionId = 4)
        fun window(time: String) = PopupReminderPolicy.window(ended, schedule, at(time), 0, 12, 20)!!
        assertTrue(window("09:00:00").edge)
        assertTrue(window("09:00:59").edge)
        assertFalse(window("09:01:00").edge)
        assertFalse(window("09:18:59").edge)
        assertTrue(window("09:19:00").edge)
        assertFalse(window("09:19:59").due)
        assertTrue(window("09:20:00").due)
        val afterClose = ended.copy(endedAtEpochMs = at("23:00:00"))
        assertTrue(PopupReminderPolicy.window(afterClose, schedule, at("23:00:59"), 0, 12, 20)!!.edge)
        assertFalse(PopupReminderPolicy.window(afterClose, schedule, at("23:20:00"), 0, 12, 20)!!.due)
    }

    @Test fun `lunch suppresses ended reminder and reopening starts a fresh wait`() {
        val ended = FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = at("11:27:00"))
        fun window(time: String) = PopupReminderPolicy.window(ended, schedule, at(time), 0, 12, 20)
        assertFalse(window("12:40:00")!!.due)
        assertFalse(window("12:40:00")!!.edge)
        assertFalse(window("13:30:00")!!.due)
        assertFalse(window("13:30:00")!!.edge)
        assertTrue(window("13:49:00")!!.edge)
        assertTrue(window("13:50:00")!!.due)
        assertFalse(window("22:45:00")!!.due)
    }

    @Test fun `fast flick opens or closes while short slow pull settles back`() {
        assertFalse(EdgeSheetMotion.opens(25f, 300f, 60f, false, 1f))
        assertTrue(EdgeSheetMotion.opens(25f, 300f, 850f, false, 1f))
        assertTrue(EdgeSheetMotion.opens(150f, 300f, 0f, false, 1f))
        assertTrue(EdgeSheetMotion.opens(250f, 300f, 0f, true, 1f))
        assertFalse(EdgeSheetMotion.opens(250f, 300f, -850f, true, 1f))
        assertTrue(EdgeSheetMotion.opens(60f, 300f, EdgeSheetMotion.releaseSpeed(0f, 60f, 65, 1f), false, 1f))
        assertEquals(-850f, EdgeSheetMotion.releaseSpeed(-850f, 60f, 65, 1f))
        assertTrue(EdgeSheetMotion.duration(220f, 1000f, 1f) < EdgeSheetMotion.duration(220f, 0f, 1f))
    }

    @Test fun `edge ignores taps and distinguishes pull from moving along the edge`() {
        assertNull(EdgeSheetMotion.drag(4f, -5f, 8))
        assertEquals(EdgeDrag.REPOSITION, EdgeSheetMotion.drag(20f, -30f, 8))
        assertEquals(EdgeDrag.REPOSITION, EdgeSheetMotion.drag(-4f, 14f, 8))
        assertEquals(EdgeDrag.PULL, EdgeSheetMotion.drag(-25f, 16f, 8))
        assertEquals(450, EdgeSheetMotion.crossLimit(1000, 100))
        assertEquals(0, EdgeSheetMotion.crossLimit(100, 120))
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

    @Test fun `offline bank contains distinct valid questions across all categories`() {
        val bank = ReminderQuestions.builtIn
        assertEquals(50, bank.size)
        assertEquals(bank.size, bank.distinctBy { it.body }.size)
        for (category in listOf("极限", "定积分", "级数", "口算")) {
            assertTrue(category, bank.any { it.body.contains(category) })
        }
        for (item in bank) {
            assertEquals(item.body, 4, item.options.distinct().size)
            assertTrue(item.body, item.answer in item.options.indices && item.options.all { it.isNotBlank() })
        }
    }

    @Test fun `common power series formula retains signs and superscripts`() {
        val fraction = ReminderMath.fraction("\\lim_{x\\to0} \\frac{e^x-e^{-x}}{x}")!!
        assertEquals("eˣ−e⁻ˣ", ReminderMath.symbols(fraction.second))
        assertEquals("x", ReminderMath.symbols(fraction.third))
        assertEquals("√(1+x)", ReminderMath.symbols("\\sqrt{1+x}"))
    }
}
