package com.mutsumi.focus

import android.content.SharedPreferences
import org.junit.Assert.*
import org.junit.Test

class FocusStateStoreTest {
    @Test fun `opening waiting reminders use existing stages but yield to checkins and reset at afternoon opening`() {
        fun at(time: String) = java.time.OffsetDateTime.parse("2026-10-19T$time+08:00").toInstant().toEpochMilli()
        val preferences = MemoryPreferences()
        val store = FocusStateStore(preferences)
        val schedule = IslandContext(sessions = listOf(IslandContext.Session(java.time.LocalTime.parse("08:30"), java.time.LocalTime.parse("11:40")),
            IslandContext.Session(java.time.LocalTime.parse("13:30"), java.time.LocalTime.parse("22:45"))), receivedAt = at("08:00:00"))
        store.writeIslandContext(schedule)
        assertNull(store.due(at("08:44:59")))
        assertEquals(ReminderKind.ENDED_15, store.due(at("08:45:00"))!!.kind)
        val token = store.reminderToken(ReminderKind.ENDED_15, at("08:45:00"))
        assertEquals(token, FocusStateStore(preferences).reminderToken(ReminderKind.ENDED_15, at("08:45:14")))
        store.writeIslandContext(schedule.copy(checkins = listOf(IslandContext.Checkin(1, "晨间打卡", java.time.LocalTime.parse("08:30"), java.time.LocalTime.parse("09:00")))))
        assertNull(store.due(at("08:45:00")))
        assertEquals(ReminderKind.ENDED_30, store.due(at("09:00:00"))!!.kind)
        store.snoozeEnded(at("09:00:00"))
        assertNull(store.due(at("09:04:59")))
        assertEquals(ReminderKind.ENDED_30, store.due(at("09:05:00"))!!.kind)
        store.closeReminders(at("09:05:00"))
        assertNull(FocusStateStore(preferences).due(at("10:00:00")))
        assertNull(store.due(at("12:00:00")))
        assertNull(store.due(at("13:44:59")))
        assertEquals(ReminderKind.ENDED_15, store.due(at("13:45:00"))!!.kind)
        assertNotEquals(token, store.reminderToken(ReminderKind.ENDED_15, at("13:45:00")))
        assertEquals(FocusMode.IDLE, store.read().mode)
        assertEquals(0L, store.read().sessionId)
    }
    private val minute = 60_000L
    private val paused = FocusRuntimeState(mode = FocusMode.PAUSED, sessionId = 8,
        pausedAtEpochMs = minute, elapsedSeconds = 1800, observedAtEpochMs = minute)

    @Test fun `one reminder expands once holds fifteen seconds and never reopens after manual collapse or recreation`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.write(paused)
        val token = store.reminderToken(ReminderKind.PAUSED, 6 * minute)
        assertEquals(AtomicRefreshPolicy.ReminderPresentation(true, true),
            AtomicRefreshPolicy.reminderPresentation(true, true, token, store.islandPresentedAt(token), false, 6 * minute))
        store.markIslandPresented(token, 6 * minute)
        val restored = FocusStateStore(prefs)
        for (second in 0..14) {
            val latest = restored.reminderToken(ReminderKind.PAUSED, 6 * minute + second * 1000)
            assertEquals(AtomicRefreshPolicy.ReminderPresentation(null, false),
                AtomicRefreshPolicy.reminderPresentation(true, true, latest, restored.islandPresentedAt(latest), false, 6 * minute + second * 1000))
        }
        assertEquals(AtomicRefreshPolicy.ReminderPresentation(false, false, true),
            AtomicRefreshPolicy.reminderPresentation(true, true, token, restored.islandPresentedAt(token), false, 6 * minute + 15_000))
        restored.markIslandCollapsed(token)
        assertEquals(AtomicRefreshPolicy.ReminderPresentation(null, false),
            AtomicRefreshPolicy.reminderPresentation(true, true, token, restored.islandPresentedAt(token), restored.islandCollapseSent(token), 8 * minute))
        restored.closeReminders()
        assertNull(restored.due(8 * minute))
        assertNull(AtomicRefreshPolicy.reminderPresentation(true, true, "", null, false, 8 * minute).expanded)
        assertNull(AtomicRefreshPolicy.reminderPresentation(true, false, token, null, false, 8 * minute).expanded)
    }

    @Test fun `island reminder expansion is persisted per round and reset for a new pause`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.write(paused)
        val first = store.reminderToken(ReminderKind.PAUSED, 6 * minute)
        store.markIslandPresented(first)
        val restored = FocusStateStore(prefs)
        assertTrue(restored.wasIslandPresented(first))
        assertEquals(first, restored.reminderToken(ReminderKind.PAUSED, 7 * minute))
        val second = restored.reminderToken(ReminderKind.PAUSED, 11 * minute)
        assertNotEquals(first, second)
        assertFalse(restored.wasIslandPresented(second))
        restored.write(paused.copy(mode = FocusMode.FOCUSING, pausedAtEpochMs = 0))
        restored.write(paused)
        assertFalse(restored.wasIslandPresented(first))
    }

    @Test fun `notification sequence and real summary statistics survive process recreation`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.write(paused.copy(pausedSeconds = 123, todayFocusSeconds = 25_200, todaySessionCount = 8))
        assertEquals(1, store.nextAtomicRecord())
        val restored = FocusStateStore(prefs)
        assertEquals(2, restored.nextAtomicRecord())
        assertEquals(123L, restored.read().pausedSeconds)
        assertEquals(25_200L, restored.read().todayFocusSeconds)
        assertEquals(8, restored.read().todaySessionCount)
    }

    @Test fun `upgrade adopts the existing notification sequence before replacing its payload`() {
        val store = FocusStateStore(MemoryPreferences())
        store.seedAtomicRecord(1250)
        assertEquals(1251, store.nextAtomicRecord())
        store.seedAtomicRecord(100)
        assertEquals(1252, store.nextAtomicRecord())
    }

    @Test fun `snooze deadline and presented stage survive store recreation`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.write(paused)
        store.markPresented(store.reminderToken(ReminderKind.PAUSED))
        store.snoozePaused(10 * minute)
        val restored = FocusStateStore(prefs)
        assertEquals(15 * minute, restored.nextReminderAt())
        assertNull(restored.due(15 * minute - 1))
        assertEquals(ReminderKind.PAUSED, restored.due(15 * minute)?.kind)
        assertFalse(restored.wasPresented(restored.reminderToken(ReminderKind.PAUSED)))
        assertEquals(1800, restored.read().elapsedNow(15 * minute))
    }

    @Test fun `swiping pause reminder suppresses it until a new pause`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.write(paused)
        store.dismissPaused()
        assertNull(FocusStateStore(prefs).due(500 * minute))
        store.write(paused.copy(elapsedSeconds = 1801))
        assertNull(store.due(500 * minute))
        store.write(paused.copy(mode = FocusMode.FOCUSING, pausedAtEpochMs = 0))
        store.write(paused.copy(pausedAtEpochMs = 500 * minute))
        assertEquals(ReminderKind.PAUSED, store.due(505 * minute)?.kind)
    }

    @Test fun `pause cycle changes revision and clears old stage token`() {
        val store = FocusStateStore(MemoryPreferences())
        store.write(paused)
        val before = store.transitionRevision()
        val token = store.reminderToken(ReminderKind.PAUSED)
        store.markPresented(token)
        store.write(paused.copy(mode = FocusMode.FOCUSING, pausedAtEpochMs = 0))
        store.write(paused)
        assertTrue(store.transitionRevision() > before)
        assertFalse(store.wasPresented(token))
    }

    @Test fun `close pause reminders persists across heartbeat and restarts but resets for the next pause`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.write(paused)
        store.closeReminders()
        val restored = FocusStateStore(prefs)
        assertTrue(restored.remindersClosed())
        assertEquals(0L, restored.nextReminderAt())
        assertNull(restored.due(500 * minute))
        restored.write(paused.copy(observedAtEpochMs = 400 * minute))
        assertTrue(restored.remindersClosed())
        assertEquals(1800L, restored.read().elapsedNow(500 * minute))
        restored.write(paused.copy(mode = FocusMode.FOCUSING, pausedAtEpochMs = 0))
        restored.write(paused.copy(pausedAtEpochMs = 500 * minute))
        assertFalse(restored.remindersClosed())
        assertEquals(ReminderKind.PAUSED, restored.due(505 * minute)?.kind)
    }

    @Test fun `close departure reminders stops all later stages without deleting the session`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        val ended = paused.copy(mode = FocusMode.ENDED, pausedAtEpochMs = 0, endedAtEpochMs = minute)
        store.write(ended)
        assertEquals(ReminderKind.ENDED_15, store.due(16 * minute)?.kind)
        store.closeReminders()
        val restored = FocusStateStore(prefs)
        assertTrue(restored.remindersClosed())
        assertEquals(0L, restored.nextReminderAt())
        for (time in listOf(16 * minute, 31 * minute, 61 * minute)) assertNull(restored.due(time))
        assertEquals(ended.sessionId, restored.read().sessionId)
        assertEquals(1800L, restored.read().elapsedSeconds)
        restored.write(ended.copy(observedAtEpochMs = 100 * minute))
        assertTrue(restored.remindersClosed())
        restored.write(ended.copy(sessionId = 9, endedAtEpochMs = 200 * minute))
        assertFalse(restored.remindersClosed())
        assertEquals(ReminderKind.ENDED_15, restored.due(215 * minute)?.kind)
    }

    @Test fun `ordinary dismissal still only acknowledges the current departure stage`() {
        val store = FocusStateStore(MemoryPreferences())
        store.write(paused.copy(mode = FocusMode.ENDED, pausedAtEpochMs = 0, endedAtEpochMs = minute))
        store.acknowledgeEnded(1)
        assertFalse(store.remindersClosed())
        assertNull(store.due(16 * minute))
        assertEquals(ReminderKind.ENDED_30, store.due(31 * minute)?.kind)
    }

    @Test fun `rest persists through reload and never schedules a reminder`() {
        val prefs = MemoryPreferences()
        FocusStateStore(prefs).write(FocusRuntimeState(mode = FocusMode.REST,
            restStartedAtEpochMs = minute, restTargetSeconds = 900))
        val restored = FocusStateStore(prefs)
        assertEquals(900, restored.read().restTargetSeconds)
        assertEquals(600, restored.read().restElapsed(11 * minute))
        assertNull(restored.due(200 * minute))
        assertEquals(0, restored.nextReminderAt())
    }

    @Test fun `settlement cancels an outstanding departure snooze`() {
        val store = FocusStateStore(MemoryPreferences())
        val ended = paused.copy(mode = FocusMode.ENDED, pausedAtEpochMs = 0, endedAtEpochMs = minute)
        store.write(ended)
        store.snoozeEnded(20 * minute)
        assertEquals(25 * minute, store.nextReminderAt())
        store.write(ended.copy(mode = FocusMode.SETTLED))
        assertEquals(0, store.nextReminderAt())
        assertNull(store.due(80 * minute))
    }

    @Test fun `persisted daily settlement cannot revive opening reminders after summary expiry or next opening`() {
        fun at(time: String) = java.time.OffsetDateTime.parse("2026-10-19T$time+08:00").toInstant().toEpochMilli()
        val preferences = MemoryPreferences()
        val store = FocusStateStore(preferences)
        store.writeIslandContext(IslandContext(sessions = listOf(
            IslandContext.Session(java.time.LocalTime.parse("08:30"), java.time.LocalTime.parse("11:40")),
            IslandContext.Session(java.time.LocalTime.parse("13:30"), java.time.LocalTime.parse("22:45"))), receivedAt = at("08:00:00")))
        assertNotNull(store.due(at("09:00:00")))
        store.snoozeEnded(at("09:00:00"))
        val settled = FocusRuntimeState(mode = FocusMode.SETTLED, endedAtEpochMs = at("09:01:00"))
        store.write(settled)
        val restored = FocusStateStore(preferences)
        for (time in listOf("09:01:29", "09:01:30", "09:05:00", "09:31:00", "13:45:00", "14:30:00")) {
            assertNull(time, restored.due(at(time)))
            assertEquals(settled, restored.reminderState(at(time)))
        }
        assertEquals(0, restored.nextReminderAt())
    }

    private fun marketAt(time: String) = java.time.OffsetDateTime.parse("2026-10-24T$time+08:00").toInstant().toEpochMilli()
    private fun marketStore(): FocusStateStore = FocusStateStore(MemoryPreferences()).also {
        it.writeIslandContext(IslandContext(sessions = listOf(
            IslandContext.Session(java.time.LocalTime.parse("08:30"), java.time.LocalTime.parse("11:40")),
            IslandContext.Session(java.time.LocalTime.parse("13:30"), java.time.LocalTime.parse("22:45"))), receivedAt = marketAt("08:00:00")))
    }

    @Test fun `actual session departure reminders stop exactly at lunch and resume from afternoon opening`() {
        val store = marketStore()
        val ended = FocusRuntimeState(mode = FocusMode.ENDED, sessionId = 20, endedAtEpochMs = marketAt("11:20:00"))
        store.write(ended)
        assertEquals(ReminderKind.ENDED_15, store.due(marketAt("11:39:59"))?.kind)
        for (time in listOf("11:40:00", "12:00:00", "13:29:59")) {
            assertNull(time, store.due(marketAt(time)))
            assertEquals(time, 0L, store.nextReminderAt(now = marketAt(time)))
        }
        assertEquals(IslandContext.Countdown.Kind.AFTERNOON,
            store.islandContext().countdown(ended, store.due(marketAt("12:00:00")), marketAt("12:00:00"))!!.kind)
        assertNull(store.due(marketAt("13:30:00")))
        assertNull(store.due(marketAt("13:44:59")))
        assertEquals(ReminderKind.ENDED_15, store.due(marketAt("13:45:00"))?.kind)
        assertTrue(store.reminderToken(ReminderKind.ENDED_15, marketAt("13:45:00")).startsWith("opening:"))
        assertEquals(ended, store.read())
    }

    @Test fun `night and preopening suppress ended reminders and the next morning never replays night stages`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.writeIslandContext(marketStore().islandContext())
        store.write(FocusRuntimeState(mode = FocusMode.ENDED, sessionId = 21, endedAtEpochMs = marketAt("22:20:00")))
        assertNotNull(store.due(marketAt("22:44:59")))
        val restored = FocusStateStore(prefs)
        for (time in listOf("22:45:00", "23:00:00", "23:59:59")) {
            assertNull(time, restored.due(marketAt(time)))
            assertEquals(time, 0L, restored.nextReminderAt(now = marketAt(time)))
        }
        fun nextDay(time: String) = java.time.OffsetDateTime.parse("2026-10-25T$time+08:00").toInstant().toEpochMilli()
        assertNull(restored.due(nextDay("08:29:59")))
        assertNull(restored.due(nextDay("08:30:00")))
        assertNull(restored.due(nextDay("08:44:59")))
        assertEquals(ReminderKind.ENDED_15, restored.due(nextDay("08:45:00"))?.kind)
    }

    @Test fun `future departure and snooze deadlines beyond closing are not advertised`() {
        val store = marketStore()
        store.write(FocusRuntimeState(mode = FocusMode.ENDED, sessionId = 22, endedAtEpochMs = marketAt("22:35:00")))
        assertEquals(0L, store.nextReminderAt(now = marketAt("22:40:00")))
        assertNull(store.due(marketAt("22:50:00")))
        store.write(FocusRuntimeState(mode = FocusMode.ENDED, sessionId = 23, endedAtEpochMs = marketAt("22:20:00")))
        store.snoozeEnded(marketAt("22:42:00"))
        assertEquals(0L, store.nextReminderAt(now = marketAt("22:42:00")))
        assertNull(store.due(marketAt("22:47:00")))
    }

    @Test fun `cached account hours still suppress night reminders when schedule data is stale`() {
        val store = marketStore()
        store.writeIslandContext(store.islandContext().copy(receivedAt = marketAt("08:00:00") - 48 * 3600000L))
        store.write(FocusRuntimeState(mode = FocusMode.ENDED, sessionId = 24, endedAtEpochMs = marketAt("22:20:00")))
        assertNull(store.due(marketAt("23:00:00")))
        assertEquals(0L, store.nextReminderAt(now = marketAt("23:00:00")))
    }

    @Test fun `pause reminders are preserved outside trading hours`() {
        val store = marketStore()
        store.write(FocusRuntimeState(mode = FocusMode.PAUSED, sessionId = 25, pausedAtEpochMs = marketAt("23:00:00")))
        assertEquals(ReminderKind.PAUSED, store.due(marketAt("23:05:00"))?.kind)
        assertEquals(marketAt("23:05:00"), store.nextReminderAt(now = marketAt("23:01:00")))
    }

    @Test fun `strong reminder is opt in even after old permissions were granted`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        assertFalse(store.strongReminders())
        store.setStrongReminders(true)
        assertTrue(FocusStateStore(prefs).strongReminders())
        store.setStrongReminders(false)
        assertFalse(FocusStateStore(prefs).strongReminders())
    }
}

/** In-memory Android preferences allow real persistence logic to run on the JVM. */
private class MemoryPreferences : SharedPreferences {
    private val values = mutableMapOf<String, Any?>()
    override fun getAll(): MutableMap<String, *> = values.toMutableMap()
    override fun getString(key: String?, defValue: String?): String? = values[key] as? String ?: defValue
    @Suppress("UNCHECKED_CAST")
    override fun getStringSet(key: String?, defValues: MutableSet<String>?): MutableSet<String>? = values[key] as? MutableSet<String> ?: defValues
    override fun getInt(key: String?, defValue: Int): Int = values[key] as? Int ?: defValue
    override fun getLong(key: String?, defValue: Long): Long = values[key] as? Long ?: defValue
    override fun getFloat(key: String?, defValue: Float): Float = values[key] as? Float ?: defValue
    override fun getBoolean(key: String?, defValue: Boolean): Boolean = values[key] as? Boolean ?: defValue
    override fun contains(key: String?): Boolean = values.containsKey(key)
    override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit
    override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit
    override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
        private val updates = mutableMapOf<String, Any?>()
        private var clear = false
        private fun put(key: String?, value: Any?): SharedPreferences.Editor { updates[requireNotNull(key)] = value; return this }
        override fun putString(key: String?, value: String?) = put(key, value)
        override fun putStringSet(key: String?, values: MutableSet<String>?) = put(key, values?.toMutableSet())
        override fun putInt(key: String?, value: Int) = put(key, value)
        override fun putLong(key: String?, value: Long) = put(key, value)
        override fun putFloat(key: String?, value: Float) = put(key, value)
        override fun putBoolean(key: String?, value: Boolean) = put(key, value)
        override fun remove(key: String?): SharedPreferences.Editor = put(key, null)
        override fun clear(): SharedPreferences.Editor { clear = true; return this }
        override fun apply() {
            if (clear) values.clear()
            updates.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value }
        }
        override fun commit(): Boolean { apply(); return true }
    }
}
