package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class AtomicIslandLayoutTest {
    private val minute = 60_000L
    private fun map(value: Any?) = value as Map<*, *>

    @Test fun `compact focus clock stays short and updates each second without changing templates or nodes`() {
        val state = FocusRuntimeState(mode = FocusMode.FOCUSING, elapsedSeconds = 3599, plannedSeconds = 10800,
            observedAtEpochMs = minute)
        for (second in 0..12) {
            val layout = AtomicIslandLayout.from(state, null, minute + second * 1000L)
            val wire = layout.wire(false)
            assertEquals(2, wire["notification.superx.template"])
            assertEquals(IslandTime.small(3599 + second.toLong()),
                map(wire["notification.superx.shortInfos"])["notification.superx.shortInfos.coreInfoShort"])
            assertEquals(listOf(AtomicIslandLayout.Glyph.START, AtomicIslandLayout.Glyph.COMPLETE),
                map(wire["notification.superx.infos"])["notification.superx.infos.nodeIcon"])
        }
    }

    @Test fun `paused island separates pause duration from frozen focus and has one capsule`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = minute, elapsedSeconds = 1800,
            subject = "这是一段很长的事项名称，不能把它塞进胶囊，也不能让它挤掉时钟")
        val layout = AtomicIslandLayout.from(state, DueReminder(ReminderKind.PAUSED, 0, 2), 11 * minute)
        assertEquals(1, layout.template)
        assertEquals("暂停中", layout.title)
        assertEquals("10:00", layout.rightText)
        assertEquals("第 2 轮提醒", layout.core)
        assertEquals(AtomicIslandLayout.Button("关闭提醒", "closeReminders"), layout.button)
        val wire = layout.wire(true)
        val base = map(wire["notification.superx.baseInfos"])
        val island = map(wire["notification.superx.island"])
        assertEquals(2, base["notification.superx.baseInfos.subInfo"])
        assertFalse(base.containsKey("notification.superx.baseInfos.subImageList"))
        assertEquals(4, island["island.superx.rightTemplate"])
        assertEquals(true, island["island.superx.forceShowCard"])
        assertEquals("暂停中", map(island["island.superx.leftInfo"])["island.superx.leftInfo.content"])
        assertEquals("10:00", map(island["island.superx.rightInfo"])["island.superx.rightInfo.content"])
        assertEquals(1800L, state.elapsedNow(11 * minute))
    }

    @Test fun `short pause never claims that a reminder was sent`() {
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = minute), null, 2 * minute)
        assertEquals("等待首次提醒", layout.core)
        assertEquals(AtomicIslandLayout.Button("继续专注", "resume"), layout.button)
        assertEquals("1:00", layout.rightText)
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
        assertEquals("已专注 15分钟0秒", free.subtitle)
        assertEquals("15:00", free.collapsedText)
        val overrun = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.FOCUSING, elapsedSeconds = 9000, plannedSeconds = 1800), null, minute)
        assertEquals(100, overrun.progress)
        assertFalse(overrun.completed)
    }

    @Test fun `session summary displays start and end with effective duration on the middle line`() {
        val start = java.time.Instant.parse("2026-10-11T01:00:00Z").toEpochMilli()
        val end = start + 55 * minute
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.ENDED, elapsedSeconds = 2700,
            pausedSeconds = 600, startedAtEpochMs = start, endedAtEpochMs = end, accountTimeZone = "Asia/Shanghai"), null, end)
        assertEquals(3, layout.template)
        assertEquals("09:00", layout.leftValue)
        assertEquals("09:55", layout.rightValue)
        assertEquals("开始", layout.leftLabel)
        assertEquals("结束", layout.rightLabel)
        assertEquals("45分钟0秒", layout.middleValue)
        assertEquals("累计有效专注", layout.middleLabel)
        assertEquals("45:00", layout.collapsedText)
        assertTrue(layout.completed)
        val info = map(layout.wire(false)["notification.superx.infos"])
        assertEquals("45分钟0秒", info["notification.superx.infos.midTopMsg"])
    }

    @Test fun `daily summary uses settlement totals rather than the last session`() {
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.SETTLED, elapsedSeconds = 900,
            todayFocusSeconds = 25_200, todaySessionCount = 8), null, minute)
        assertEquals(3, layout.template)
        assertEquals("7小时0分钟", layout.leftValue)
        assertEquals("8 段", layout.rightValue)
        assertEquals("专注次数", layout.rightLabel)
        assertEquals(1, map(map(layout.wire(false)["notification.superx.island"])["island.superx.rightInfo"])["island.superx.rightInfo.progressState"])
    }

    @Test fun `departure reminder keeps one close entry and displays the latest round`() {
        val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.ENDED, endedAtEpochMs = minute),
            DueReminder(ReminderKind.ENDED_60, 0), 61 * minute)
        assertEquals(1, layout.template)
        assertEquals("第 3 轮提醒", layout.core)
        assertEquals(AtomicIslandLayout.Button("关闭提醒", "closeReminders"), layout.button)
    }

    @Test fun `all reminder kinds have the same themed close capsule in notification and island`() {
        val palette = IslandPalette(0xFF587EAA.toInt())
        for (kind in ReminderKind.entries) {
            val state = FocusRuntimeState(mode = if (kind == ReminderKind.PAUSED) FocusMode.PAUSED else FocusMode.ENDED,
                pausedAtEpochMs = minute, endedAtEpochMs = minute)
            val wire = AtomicIslandLayout.from(state, DueReminder(kind, 0), 61 * minute).wire(true, palette)
            val base = map(wire["notification.superx.baseInfos"])
            assertEquals("关闭提醒", base["notification.superx.baseInfos.subText"])
            assertEquals(AtomicIslandLayout.Click.PRIMARY, base["notification.superx.baseInfos.subInfoClickResp"])
            assertEquals(palette.accent, base["notification.superx.baseInfos.subCapsuleBgColor"])
            assertEquals(base, map(wire["notification.superx.island"])["island.superx.baseInfos"])
        }
    }

    @Test fun `closing a pause reminder restores resume without claiming that reminders are active`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = minute, elapsedSeconds = 1800)
        val layout = AtomicIslandLayout.from(state, null, 11 * minute, remindersClosed = true)
        assertEquals("提醒已关闭", layout.core)
        assertEquals("10:00", layout.rightText)
        assertEquals(AtomicIslandLayout.Button("继续专注", "resume"), layout.button)
        assertEquals(1800L, state.elapsedNow(11 * minute))
    }

    @Test fun `rest has the same text timer capsule as pause and never caps elapsed time to its goal`() {
        val state = FocusRuntimeState(mode = FocusMode.REST, restStartedAtEpochMs = minute, restTargetSeconds = 900)
        val layout = AtomicIslandLayout.from(state, null, 126 * minute + 7000)
        assertEquals(1, layout.template)
        assertEquals(4, layout.rightTemplate)
        assertEquals("休息中", layout.collapsedText)
        assertEquals("125:07", layout.rightText)
        assertEquals("2小时5分钟", layout.core)
        assertEquals(AtomicIslandLayout.Button("结束休息", "endRest"), layout.button)
        assertNull(ReminderPolicy.due(state, 126 * minute, 0, 0))
    }

    @Test fun `long pause and focus times do not wrap or collapse when the progress reaches its target`() {
        val paused = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.PAUSED, pausedAtEpochMs = minute), null, 126 * minute + 7000)
        assertEquals("125:07", paused.rightText)
        assertEquals("已暂停 2小时5分钟", paused.subtitle)
        val focus = AtomicIslandLayout.from(FocusRuntimeState(mode = FocusMode.FOCUSING, elapsedSeconds = 7507,
            plannedSeconds = 900, observedAtEpochMs = minute), null, minute)
        assertEquals(100, focus.progress)
        assertEquals("125:07", focus.collapsedText)
        assertEquals("已专注 2小时5分钟", focus.subtitle)
    }

    @Test fun `each live second is reflected while paused effective focus remains frozen`() {
        val focus = FocusRuntimeState(mode = FocusMode.FOCUSING, elapsedSeconds = 3599, observedAtEpochMs = minute)
        val pause = focus.copy(mode = FocusMode.PAUSED, pausedAtEpochMs = minute)
        for (second in 0..12) {
            val now = minute + second * 1000L
            assertEquals(IslandTime.small(3599 + second.toLong()), AtomicIslandLayout.from(focus, null, now).collapsedText)
            assertEquals("0:${second.toString().padStart(2, '0')}", AtomicIslandLayout.from(pause, null, now).rightText)
            assertEquals(3599, pause.elapsedNow(now))
        }
    }
}
