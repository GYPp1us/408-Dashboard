package com.mutsumi.focus

import java.time.OffsetDateTime
import java.time.LocalTime
import org.junit.Assert.*
import org.junit.Test

class IslandContextTest {
    private fun at(value: String) = OffsetDateTime.parse("2026-10-18T$value+08:00").toInstant().toEpochMilli()
    private val noon = at("12:00:00")
    private val windows = listOf(IslandContext.Session(LocalTime.parse("08:30"), LocalTime.parse("11:40")),
        IslandContext.Session(LocalTime.parse("13:30"), LocalTime.parse("22:45")))
    private val task = IslandContext.Checkin(1, "午间任务", LocalTime.parse("11:00"), LocalTime.parse("14:00"))
    private val context = IslandContext(sessions = windows, checkins = listOf(task), receivedAt = at("08:00:00"))
    private val idle = FocusRuntimeState()

    @Test fun `lunch countdown fills idle gaps but never displaces focus or rest`() {
        for (mode in listOf(FocusMode.IDLE, FocusMode.SETTLED)) {
            val result = context.countdown(idle.copy(mode = mode), null, noon)!!
            assertEquals(IslandContext.Countdown.Kind.AFTERNOON, result.kind)
            assertEquals(5400L, result.remaining(noon))
            assertEquals(5399L, result.remaining(noon + 1000))
        }
        for (mode in listOf(FocusMode.FOCUSING, FocusMode.REST))
            assertNull(context.countdown(idle.copy(mode = mode), null, noon))
        assertNull(context.countdown(idle.copy(mode = FocusMode.FOCUSING), null, at("13:30:00")))
        assertEquals(IslandContext.Countdown.Kind.AFTERNOON, context.countdown(idle, null, at("11:40:00"))!!.kind)
        assertEquals(at("11:40:00"), context.nextBoundary(at("11:39:59")))
        assertEquals(at("13:30:00"), context.nextBoundary(noon))
    }

    @Test fun `pause active reminders and fresh summaries outrank schedule countdowns`() {
        assertNull(context.countdown(idle.copy(mode = FocusMode.PAUSED), null, noon))
        assertNull(context.countdown(idle, DueReminder(ReminderKind.ENDED_15, 0), noon))
        for (mode in listOf(FocusMode.ENDED, FocusMode.SETTLED))
            assertNull(context.countdown(idle.copy(mode = mode, endedAtEpochMs = noon - 1000), null, noon))
    }

    @Test fun `checkins only fill idle gaps and choose earliest uncompleted deadline deterministically`() {
        val second = task.copy(id = 2, end = LocalTime.parse("13:45"))
        val schedule = context.copy(checkins = listOf(task, second))
        assertEquals(2L, schedule.countdown(idle, null, at("13:35:00"))!!.id)
        assertNull(schedule.countdown(idle.copy(mode = FocusMode.REST), null, at("13:35:00")))
        val complete = schedule.copy(checkins = listOf(task.copy(completedDay = "2026-10-18"), second.copy(completedDay = "2026-10-18")))
        assertEquals(IslandContext.Countdown.Kind.WAITING, complete.countdown(idle, null, at("13:35:00"))!!.kind)
        assertEquals(IslandContext.Countdown.Kind.WAITING, schedule.countdown(idle, null, at("14:00:00"))!!.kind)
    }

    @Test fun `each opening provides a fresh lowest priority waiting anchor without fabricating focus`() {
        val schedule = context.copy(checkins = emptyList())
        assertNull(schedule.countdown(idle, null, at("08:29:59")))
        val morning = schedule.countdown(idle, null, at("08:35:00"))!!
        assertEquals(IslandContext.Countdown.Kind.WAITING, morning.kind)
        assertEquals(at("08:30:00"), morning.end)
        assertEquals(300L, morning.remaining(at("08:35:00")))
        assertEquals(at("13:30:00"), schedule.countdown(idle, null, at("13:30:00"))!!.end)
        assertNull(schedule.countdown(idle, null, at("22:45:00")))
        assertNull(schedule.openingWait(idle.copy(mode = FocusMode.ENDED, endedAtEpochMs = at("13:31:00")), at("13:35:00")))
        val layout = AtomicIslandLayout.from(idle, null, at("08:35:00"), countdown = morning)
        assertEquals("等待下一段专注", layout.title)
        assertEquals("5:00", layout.rightText)
    }

    @Test fun `settlement never becomes opening waiting after summary expiry but keeps bedtime checkin countdowns`() {
        val schedule = context.copy(checkins = emptyList())
        val settled = idle.copy(mode = FocusMode.SETTLED, endedAtEpochMs = at("09:00:00"))
        for (time in listOf("09:00:29", "09:00:30", "09:15:00", "13:30:00", "14:30:00")) {
            assertNull(time, schedule.openingWait(settled, at(time)))
            assertNull(time, schedule.countdown(settled, null, at(time)))
        }
        val deadline = context.countdown(settled, null, at("13:35:00"))!!
        assertEquals(IslandContext.Countdown.Kind.CHECKIN, deadline.kind)
        assertEquals(task.id, deadline.id)
        assertEquals("打卡剩余时间", AtomicIslandLayout.from(settled, null, at("13:35:00"), countdown = deadline).title)
        assertEquals(IslandContext.Countdown.Kind.WAITING, schedule.countdown(idle, null, at("13:35:00"))!!.kind)
    }

    @Test fun `overnight deadline crosses midnight and prior completion expires on the account date`() {
        val overnight = context.copy(receivedAt = at("00:00:00"), sessions = emptyList(), checkins = listOf(task.copy(start = LocalTime.parse("23:00"), end = LocalTime.parse("02:00"), completedDay = "2026-10-17")))
        val result = overnight.countdown(idle, null, at("00:30:00"))!!
        assertEquals(at("02:00:00"), result.end)
        assertEquals(5400L, result.remaining(at("00:30:00")))
        assertNull(overnight.countdown(idle, null, at("02:00:00")))
        assertNull(overnight.copy(receivedAt = at("08:00:00") - 37 * 3_600_000L).countdown(idle, null, noon))
    }

    @Test fun `countdown layout keeps complete minute second clock and theme colors without expansion commands`() {
        val countdown = context.countdown(idle, null, noon)!!
        val layout = AtomicIslandLayout.from(idle, null, noon, countdown = countdown)
        assertEquals("90:00", layout.rightText)
        assertEquals("下午开盘", layout.collapsedText)
        val wire = layout.wire(null, IslandPalette(0xFF123456.toInt()))
        val island = wire["notification.superx.island"] as Map<*, *>
        assertFalse(island.containsKey("island.superx.forceShowCard"))
        val first = layout.wire(true, showSeconds = 15)["notification.superx.island"] as Map<*, *>
        assertEquals(15, first["island.superx.showTime"])
        assertEquals(true, first["island.superx.forceShowCard"])
    }
}
