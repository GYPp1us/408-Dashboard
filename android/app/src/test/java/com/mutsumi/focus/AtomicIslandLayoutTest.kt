package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class AtomicIslandLayoutTest {
    private val minute = 60_000L
    private fun map(value: Any?) = value as Map<*, *>

    @Test fun `paused island separates pause duration from frozen focus and has one capsule`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = minute, elapsedSeconds = 1800,
            subject = "这是一段很长的事项名称，不能把它塞进胶囊，也不能让它挤掉时钟")
        val layout = AtomicIslandLayout.from(state, DueReminder(ReminderKind.PAUSED, 0, 2), 11 * minute)
        assertEquals(1, layout.template)
        assertEquals("暂停中", layout.title)
        assertEquals("00:10:00", layout.rightText)
        assertEquals("第 2 轮提醒", layout.core)
        assertEquals(AtomicIslandLayout.Button("继续专注", "resume"), layout.button)
        val wire = layout.wire(true)
        val base = map(wire["notification.superx.baseInfos"])
        val island = map(wire["notification.superx.island"])
        assertEquals(2, base["notification.superx.baseInfos.subInfo"])
        assertFalse(base.containsKey("notification.superx.baseInfos.subImageList"))
        assertEquals(4, island["island.superx.rightTemplate"])
        assertEquals(true, island["island.superx.forceShowCard"])
        assertEquals("暂停中", map(island["island.superx.leftInfo"])["island.superx.leftInfo.content"])
        assertEquals("00:10:00", map(island["island.superx.rightInfo"])["island.superx.rightInfo.content"])
        assertEquals(1800L, state.elapsedNow(11 * minute))
    }

    @Test fun `short pause never claims that a reminder was sent`() {
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = minute), null, 2 * minute)
        assertEquals("等待首次提醒", layout.core)
        assertEquals("00:01:00", layout.rightText)
        assertEquals(false, map(layout.wire(false)["notification.superx.island"])["island.superx.forceShowCard"])
    }

    @Test fun `target focus uses a two node progress card and system progress glyph`() {
        val state = FocusRuntimeState(mode = FocusMode.FOCUSING, elapsedSeconds = 900, plannedSeconds = 1800, observedAtEpochMs = minute)
        val layout = AtomicIslandLayout.from(state, null, minute)
        assertEquals(2, layout.template)
        assertEquals(2, layout.rightTemplate)
        assertEquals(50, layout.progress)
        val wire = layout.wire(false)
        val info = map(wire["notification.superx.infos"])
        assertEquals(2, (info["notification.superx.infos.nodeIcon"] as List<*>).size)
        assertEquals(50, info["notification.superx.infos.progress"])
        val right = map(map(wire["notification.superx.island"])["island.superx.rightInfo"])
        assertFalse(right.containsKey("island.superx.rightInfo.icon"))
        assertEquals(0, right["island.superx.rightInfo.progressState"])
    }

    @Test fun `free focus has no invented percentage and goal overrun remains bounded`() {
        val free = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.FOCUSING, elapsedSeconds = 900), null, minute)
        assertEquals(2, free.template)
        assertEquals(3, free.rightTemplate)
        assertEquals(0, free.progress)
        assertTrue(free.subtitle.endsWith("自由计时"))
        val overrun = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.FOCUSING, elapsedSeconds = 9000, plannedSeconds = 1800), null, minute)
        assertEquals(100, overrun.progress)
        assertFalse(overrun.completed)
    }

    @Test fun `session summary uses actual effective and cumulative pause statistics`() {
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.ENDED, elapsedSeconds = 2700, pausedSeconds = 600), null, minute)
        assertEquals(3, layout.template)
        assertEquals("00:45:00", layout.leftValue)
        assertEquals("00:10:00", layout.rightValue)
        assertEquals("累计暂停", layout.rightLabel)
        assertTrue(layout.completed)
        val info = map(layout.wire(false)["notification.superx.infos"])
        assertEquals("有效专注", info["notification.superx.infos.leftSub"])
        assertEquals("00:10:00", info["notification.superx.infos.rightMain"])
    }

    @Test fun `daily summary uses settlement totals rather than the last session`() {
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.SETTLED, elapsedSeconds = 900,
            todayFocusSeconds = 25_200, todaySessionCount = 8), null, minute)
        assertEquals(3, layout.template)
        assertEquals("07:00:00", layout.leftValue)
        assertEquals("8 段", layout.rightValue)
        assertEquals("专注次数", layout.rightLabel)
        assertEquals(1, map(map(layout.wire(false)["notification.superx.island"])["island.superx.rightInfo"])["island.superx.rightInfo.progressState"])
    }

    @Test fun `departure reminder keeps one primary entry and displays the latest round`() {
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = minute),
            DueReminder(ReminderKind.ENDED_60, 0), 61 * minute)
        assertEquals(1, layout.template)
        assertEquals("第 3 轮提醒", layout.core)
        assertEquals(AtomicIslandLayout.Button("开始专注", "next"), layout.button)
    }
}
