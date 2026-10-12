package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.util.TimeZone

class IslandTimeTest {
    @Test fun `small duration carries all hours into total minutes and retains seconds`() {
        assertEquals("0:00", IslandTime.small(0))
        assertEquals("0:59", IslandTime.small(59))
        assertEquals("1:00", IslandTime.small(60))
        assertEquals("60:05", IslandTime.small(3605))
        assertEquals("125:07", IslandTime.small(7507))
        assertEquals("1440:01", IslandTime.small(86401))
    }

    @Test fun `large duration switches units at one hour without rounding up stored time`() {
        assertEquals("0分钟0秒", IslandTime.large(0))
        assertEquals("59分钟59秒", IslandTime.large(3599))
        assertEquals("1小时0分钟", IslandTime.large(3600))
        assertEquals("2小时5分钟", IslandTime.large(7507))
        assertEquals("24小时0分钟", IslandTime.large(86401))
        val state = FocusRuntimeState(mode = FocusMode.ENDED, elapsedSeconds = 7507)
        IslandTime.large(state.elapsedSeconds)
        assertEquals(7507, state.elapsedNow(10000))
    }

    @Test fun `account time points are independent of device timezone and preserve cross day identity`() {
        val previous = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Los_Angeles"))
            val state = FocusRuntimeState(accountTimeZone = "Asia/Shanghai",
                startedAtEpochMs = Instant.parse("2026-10-11T15:50:17Z").toEpochMilli(),
                endedAtEpochMs = Instant.parse("2026-10-11T16:20:42Z").toEpochMilli())
            assertEquals("23:50", IslandTime.point(state.startedAtEpochMs, state))
            assertEquals("00:20", IslandTime.point(state.endedAtEpochMs, state))
            assertEquals(1, IslandTime.dayDifference(state))
        } finally { TimeZone.setDefault(previous) }
    }

    @Test fun `named account timezone follows daylight saving for each endpoint`() {
        val state = FocusRuntimeState(accountTimeZone = "America/New_York",
            startedAtEpochMs = Instant.parse("2026-03-08T06:30:00Z").toEpochMilli(),
            endedAtEpochMs = Instant.parse("2026-03-08T07:30:00Z").toEpochMilli())
        assertEquals("01:30", IslandTime.point(state.startedAtEpochMs, state))
        assertEquals("03:30", IslandTime.point(state.endedAtEpochMs, state))
    }

    @Test fun `server offset is used before timezone name arrives and missing endpoints remain explicit`() {
        val state = FocusRuntimeState(accountOffsetSeconds = 20700)
        assertEquals("05:45", IslandTime.point(Instant.parse("2026-10-11T00:00:00Z").toEpochMilli(), state))
        assertEquals("--:--", IslandTime.point(0, state))
    }
}
