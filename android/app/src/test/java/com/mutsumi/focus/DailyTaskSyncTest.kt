package com.mutsumi.focus

import java.time.OffsetDateTime
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class DailyTaskSyncTest {
    private val now = OffsetDateTime.parse("2026-10-24T20:00:00+08:00").toInstant().toEpochMilli()
    private val settled = FocusRuntimeState(mode = FocusMode.SETTLED, endedAtEpochMs = now - 40_000)
    private val sync = IslandContext.TaskSync("event:1", "2026-10-24", "pending", 2, 5, now)
    private fun context(value: IslandContext.TaskSync = sync) = IslandContext(receivedAt = now, taskSync = value)

    @Test fun `task synchronization only overlays settled idle and never displaces an active timer or reminder`() {
        assertEquals(sync, context().visibleTaskSync(settled, null, now))
        for (mode in FocusMode.entries.filter { it != FocusMode.SETTLED })
            assertNull(mode.name, context().visibleTaskSync(settled.copy(mode = mode), null, now))
        assertNull(context().visibleTaskSync(settled, DueReminder(ReminderKind.ENDED_15, 0), now))
        val active = AtomicIslandLayout.from(settled.copy(mode = FocusMode.FOCUSING), null, now, taskSync = sync)
        assertEquals(2, active.template)
    }

    @Test fun `pending success and failure expire without enabling next focus reminders`() {
        for ((status, lifetime) in listOf("pending" to 600_000L, "sent" to 15_000L, "failed" to 30_000L, "unconfigured" to 30_000L)) {
            val value = sync.copy(status = status)
            val context = context(value)
            assertNotNull(status, context.visibleTaskSync(settled, null, now + lifetime - 1))
            assertNull(status, context.visibleTaskSync(settled, null, now + lifetime))
            assertNull(context.openingWait(settled, now + lifetime))
        }
        assertNull(context().visibleTaskSync(settled, null, now + 24 * 3600_000L))
    }

    @Test fun `native persistence roundtrips only safe synchronization display fields`() {
        val data = JSONObject().put("timezone", "Asia/Shanghai").put("task_sync", sync.json().put("token", "never-persist"))
        val parsed = IslandContext.fromJson(data, now)!!
        assertEquals(sync, parsed.taskSync)
        assertFalse(parsed.toJson().contains("never-persist"))
        assertEquals(sync, IslandContext.fromJson(JSONObject(parsed.toJson()), now)!!.taskSync)
        assertNull(IslandContext.fromJson(data.put("task_sync", JSONObject().put("status", "unknown")), now)!!.taskSync)
    }

    @Test fun `sync uses public emphasis template and never repeats an expansion command`() {
        for (status in listOf("pending", "sent", "failed", "unconfigured")) {
            val layout = AtomicIslandLayout.from(settled, null, now, taskSync = sync.copy(status = status))
            assertEquals(1, layout.template)
            assertEquals(if (status == "pending") 3 else 4, layout.rightTemplate)
            assertEquals("2/5", layout.rightText)
            val island = layout.wire(null)["notification.superx.island"] as Map<*, *>
            assertFalse(island.containsKey("island.superx.forceShowCard"))
            assertTrue(layout.collapsedText.length <= 4)
        }
    }
}
