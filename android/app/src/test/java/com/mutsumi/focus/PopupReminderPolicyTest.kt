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

    @Test fun `nonfocus edge stays available throughout opening and distinguishes final minute`() {
        val start = at("09:00:00")
        val paused = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = start, sessionId = 4)
        fun window(time: String) = PopupReminderPolicy.window(paused, schedule, at(time), 0, 12, 20)!!
        assertTrue(window("09:00:00").edge)
        assertTrue(window("09:00:59").edge)
        assertTrue(window("09:01:00").edge)
        assertTrue(window("09:10:59").edge)
        assertFalse(window("09:10:59").imminent)
        assertTrue(window("09:11:00").imminent)
        assertTrue(window("09:11:00").edge)
        assertFalse(window("09:11:59").due)
        assertTrue(window("09:12:00").due)
        val active = paused.copy(mode = FocusMode.FOCUSING, startedAtEpochMs = start)
        assertNull(PopupReminderPolicy.window(active, schedule, at("09:00:00"), 0, 12, 20))
        assertNull(PopupReminderPolicy.window(active, schedule, at("09:01:00"), 0, 12, 20))
        assertFalse(PopupReminderPolicy.window(paused, schedule, at("09:50:00"), 0, 0, 20)!!.due)
    }

    @Test fun `ended and idle states remain available until close`() {
        val ended = FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = at("09:00:00"), sessionId = 4)
        fun window(time: String) = PopupReminderPolicy.window(ended, schedule, at(time), 0, 12, 20)!!
        assertTrue(window("09:00:00").edge)
        assertTrue(window("09:00:59").edge)
        assertTrue(window("09:01:00").edge)
        assertTrue(window("09:18:59").edge)
        assertFalse(window("09:18:59").imminent)
        assertTrue(window("09:19:00").imminent)
        assertTrue(window("09:19:00").edge)
        assertFalse(window("09:19:59").due)
        assertTrue(window("09:20:00").due)
        val afterClose = ended.copy(endedAtEpochMs = at("23:00:00"))
        assertNull(PopupReminderPolicy.window(afterClose, schedule, at("23:00:59"), 0, 12, 20))
        assertTrue(PopupReminderPolicy.window(FocusRuntimeState(), schedule, at("09:00:00"), 0, 12, 20)!!.edge)
        assertTrue(PopupReminderPolicy.window(FocusRuntimeState(mode = FocusMode.REST, restStartedAtEpochMs = at("09:00:00")),
            schedule, at("09:10:00"), 0, 12, 20)!!.edge)
        assertFalse(PopupReminderPolicy.window(FocusRuntimeState(mode = FocusMode.SETTLED), schedule,
            at("09:20:00"), 0, 12, 20)!!.due)
    }

    @Test fun `lunch suppresses ended reminder and reopening starts a fresh wait`() {
        val ended = FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = at("11:27:00"))
        fun window(time: String) = PopupReminderPolicy.window(ended, schedule, at(time), 0, 12, 20)
        assertNull(window("12:40:00"))
        assertFalse(window("13:30:00")!!.due)
        assertTrue(window("13:30:00")!!.edge)
        assertTrue(window("13:49:00")!!.edge)
        assertTrue(window("13:50:00")!!.due)
        assertNull(window("22:45:00"))
    }

    @Test fun `fast flick opens or closes while short slow pull settles back`() {
        assertFalse(EdgeSheetMotion.opens(25f, 300f, 60f, false, 1f))
        assertTrue(EdgeSheetMotion.opens(25f, 300f, 850f, false, 1f))
        assertTrue(EdgeSheetMotion.opens(150f, 300f, 0f, false, 1f))
        assertTrue(EdgeSheetMotion.opens(250f, 300f, 0f, true, 1f))
        assertFalse(EdgeSheetMotion.opens(250f, 300f, -850f, true, 1f))
        assertTrue(EdgeSheetMotion.opens(60f, 300f, EdgeSheetMotion.releaseSpeed(0f, 60f, 65, 1f), false, 1f))
        assertTrue(EdgeSheetMotion.opens(150f, 866f, EdgeSheetMotion.releaseSpeed(0f, 150f, 126, 2.625f), false, 2.625f))
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

    @Test fun `delay keeps edge visible and triggers exactly at the selected time`() {
        val paused = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = at("09:00:00"))
        val until = at("09:45:00")
        fun window(time: String) = PopupReminderPolicy.window(paused, schedule, at(time), until, 12, 20)
        assertTrue(window("09:43:59")!!.edge)
        assertFalse(window("09:43:59")!!.imminent)
        assertTrue(window("09:44:00")!!.imminent)
        assertFalse(window("09:44:59")!!.due)
        assertTrue(window("09:45:00")!!.due)
        assertEquals(window("09:43:59")!!.key, window("09:45:00")!!.key)
    }

    @Test fun `free normal delay and extra minute are independent single use across store recreation`() {
        val prefs = MemoryPreferences()
        val store = PopupReminderStore(prefs)
        store.beginPhase("pause1")
        assertTrue(store.delayWithoutQuestion(1, 1000, extraMinute = true))
        assertFalse(PopupReminderStore(prefs).delayWithoutQuestion(1, 1001, extraMinute = true))
        assertTrue(store.freeDelayAvailable)
        assertTrue(store.delayWithoutQuestion(15, 2000))
        assertEquals(961000, store.muteUntil)
        store.beginPhase("pause1")
        assertFalse(store.delayWithoutQuestion(30, 3000))
        store.beginPhase("pause2")
        assertTrue(store.freeDelayAvailable)
        assertTrue(store.minuteDelayAvailable)
        assertFalse(store.delayWithoutQuestion(999, 3000))
    }

    @Test fun `a custom normal minute remains separate from the bonus minute`() {
        val store = PopupReminderStore(MemoryPreferences())
        store.muteOptions = listOf(1, 15, 30)
        store.beginPhase("pause")
        assertTrue(store.delayWithoutQuestion(1, 1000))
        assertFalse(store.freeDelayAvailable)
        assertTrue(store.minuteDelayAvailable)
        assertTrue(store.delayWithoutQuestion(1, 1001, extraMinute = true))
        assertFalse(store.minuteDelayAvailable)
    }

    @Test fun `a slightly ahead transition keeps one stable edge phase`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, sessionId = 5, pausedAtEpochMs = at("09:01:00"))
        val first = PopupReminderPolicy.window(state, schedule, at("09:00:00"), 0, 12, 20)!!
        val next = PopupReminderPolicy.window(state, schedule, at("09:00:01"), 0, 12, 20)!!
        assertEquals(first.key, next.key)
        assertFalse(first.due)
    }

    @Test fun `question rotation avoids same question and preserves answer after shuffle`() {
        val question = ReminderQuestion("first", listOf("incorrect 1", "correct", "incorrect 2"), 1)
        val bank = listOf(question, question.copy(body = "second"))
        val random = Random(8)
        var previous: ReminderQuestion? = null
        repeat(75) {
            val result = checkNotNull(ReminderQuestions.next(bank, previous, random))
            assertNotEquals(previous?.body, result.body)
            val original = bank.single { it.body == result.body }
            assertEquals(original.options[original.answer], result.options[result.answer])
            previous = result
        }
    }

    @Test fun `empty bank offers no question and one question can be retried`() {
        val question = ReminderQuestion("only", listOf("wrong", "correct", "also wrong"), 1)
        assertNull(ReminderQuestions.next(ReminderQuestions.decode("""{"questions":[]}"""), question))
        val result = checkNotNull(ReminderQuestions.next(listOf(question), question, Random(2)))
        assertEquals(question.body, result.body)
        assertEquals(question.options[question.answer], result.options[result.answer])
    }

    @Test fun `reads a full managed bank with escaped supplementary characters`() {
        val escapedGlyph = "\\ud83d\\ude00"
        val body = escapedGlyph.repeat(555)
        val option = escapedGlyph.repeat(79)
        val options = (1..5).joinToString(",") { """"$it$option"""" }
        val rows = (1..512).joinToString(",") { """{"body":"题 $it$body","options":[$options],"answer_index":4}""" }
        val payload = """{"revision":1,"questions":[$rows]}"""
        val bank = ReminderQuestions.decode(checkNotNull(FocusApi.readReminderResponse(payload.reader())))
        assertEquals(512, bank.size)
        assertTrue(bank.last().body.startsWith("题 512"))
        assertTrue(bank.last().options[bank.last().answer].startsWith("5"))
    }

    @Test fun `common power series formula retains signs and superscripts`() {
        val fraction = ReminderMath.fraction("\\lim_{x\\to0} \\frac{e^x-e^{-x}}{x}")!!
        assertEquals("eˣ−e⁻ˣ", ReminderMath.symbols(fraction.second))
        assertEquals("x", ReminderMath.symbols(fraction.third))
        assertEquals("√(1+x)", ReminderMath.symbols("\\sqrt{1+x}"))
    }
}
