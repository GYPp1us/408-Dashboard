package com.mutsumi.focus

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.Locale

class AtomicSystemTimerTest {
    // Contract of the inspected ROM's formatter, not an Android rendering test.
    private fun displayed(text: AtomicSystemTimer.Text, monotonic: Long): String {
        val json = JSONObject(text.json)
        val delta = if (json.getBoolean("countDown")) json.getLong("base") - monotonic else monotonic - json.getLong("base")
        val seconds = (delta / 1000).coerceAtLeast(0)
        val time = if (seconds >= 3600) String.format(Locale.ROOT, json.getString("elapsedFormatHMS"), seconds / 3600, seconds / 60 % 60, seconds % 60)
            else String.format(Locale.ROOT, json.getString("elapsedFormatMS"), seconds / 60, seconds % 60)
        return String.format(Locale.ROOT, json.getString("contentFormat"), time)
    }

    @Test fun `unbounded compact minutes survive all hour and ten minute boundaries`() {
        for (seconds in listOf(0L, 59, 60, 599, 600, 3599, 3600, 3661, 7199, 360_001)) {
            val timer = AtomicSystemTimer(seconds * 1000)
            assertEquals(IslandTime.small(seconds), displayed(timer.text(5000, true), 5000))
        }
        val timer = AtomicSystemTimer(3661_000)
        assertEquals("61:04", displayed(timer.text(5000, true), 8000))
        assertEquals("1小时1分钟", displayed(timer.text(5000, false), 8000))
    }

    @Test fun `countdown uses ceiling through the last fractional second without dropping an hour`() {
        val state = FocusRuntimeState()
        for (remaining in listOf(1L, 400, 1000, 90_000, 3600_000, 3661_123)) {
            val countdown = IslandContext.Countdown(IslandContext.Countdown.Kind.AFTERNOON, 100_000 + remaining)
            val timer = AtomicSystemTimer.from(state, 100_000, countdown)!!
            assertEquals(IslandTime.small((remaining + 999) / 1000), displayed(timer.text(5000, true), 5000))
        }
        val timer = AtomicSystemTimer(90_999, true)
        assertEquals("1:25", displayed(timer.text(5000, true), 10_000))
    }

    @Test fun `real seconds move without reposting while native shapes and pause round text stay intact`() {
        val state = FocusRuntimeState(mode = FocusMode.PAUSED, startedAtEpochMs = 1000, pausedAtEpochMs = 10_000)
        val now = 80_000L
        val layout = AtomicIslandLayout.from(state, null, now)
        val timer = AtomicSystemTimer.from(state, now)!!
        val wire = timer.wire(layout.wire(null), 5000)
        @Suppress("UNCHECKED_CAST")
        val island = wire["notification.superx.island"] as Map<String, Any>
        @Suppress("UNCHECKED_CAST")
        val right = island["island.superx.rightInfo"] as Map<String, Any>
        val time = right["island.superx.rightInfo.content"] as AtomicSystemTimer.Text
        assertEquals("1:10", displayed(time, 5000))
        assertEquals("1:15", displayed(time, 10_000))
        assertEquals(layout.template, wire["notification.superx.template"])
        @Suppress("UNCHECKED_CAST")
        val info = wire["notification.superx.infos"] as Map<String, Any>
        assertEquals("等待首次提醒", info["notification.superx.infos.coreInfo"])
    }

    @Test fun `system timer stays quiet for a free focusing hour except format boundaries`() {
        val state = FocusRuntimeState(mode = FocusMode.FOCUSING, sessionId = 1)
        val key = AtomicRefreshPolicy.StateKey.from(state, true, true, 1, "", "", 1)
        val policy = AtomicRefreshPolicy()
        var publications = 0
        for (second in 0L until 3600) {
            val renderKey = AtomicSystemTimer(second * 1000).renderKey()
            if (policy.shouldPublish(key, second, second * 1000, false, systemTimerKey = renderKey)) {
                policy.published(key, second, second * 1000, renderKey)
                publications++
            }
        }
        assertEquals(6, publications)
        assertTrue(policy.shouldPublish(key, 3605, 3600_000, false, systemTimerKey = "6:0"))
    }

    @Test fun `progress changes wait during a reminder but genuine state changes remain immediate`() {
        val state = FocusRuntimeState(mode = FocusMode.FOCUSING)
        val key = AtomicRefreshPolicy.StateKey.from(state, true, true, 1, "round1", "", 1)
        val policy = AtomicRefreshPolicy()
        policy.published(key, 10, 1000, "0:1")
        assertFalse(policy.shouldPublish(key, 11, 2000, false, true, "0:2"))
        assertTrue(policy.shouldPublish(key.copy(accent = 2), 11, 2000, false, true, "0:2"))
        assertTrue(policy.shouldPublish(key, 11, 2000, false, false, "0:2"))
    }

    @Test fun `countdown heartbeat reanchoring does not cause per second notifications`() {
        val key = AtomicRefreshPolicy.StateKey.from(FocusRuntimeState(), true, true, 1, "", "", 1)
        val policy = AtomicRefreshPolicy()
        policy.published(key, 90, 0, "0:0")
        for (second in 1L..20) assertFalse(policy.shouldPublish(key, 90 - second, second * 1000, false,
            systemTimerKey = "0:0", clockDirection = -1))
        assertTrue(policy.shouldPublish(key, 60, 20_000, false, systemTimerKey = "0:0", clockDirection = -1))
    }

    @Test fun `unverified firmware and static summaries retain the existing path`() {
        assertTrue(AtomicSystemTimer.supported("V2505A", "PD2505B_A_17.1.9.0.W10"))
        assertFalse(AtomicSystemTimer.supported("V2505A", "PD2505B_A_16.0.30.14.W10"))
        assertFalse(AtomicSystemTimer.supported("other", "PD2505B_A_17.1.9.0.W10"))
        assertNull(AtomicSystemTimer.from(FocusRuntimeState(mode = FocusMode.SETTLED), 1000))
        assertNull(AtomicSystemTimer.from(FocusRuntimeState(mode = FocusMode.ENDED), 1000))
    }
}
