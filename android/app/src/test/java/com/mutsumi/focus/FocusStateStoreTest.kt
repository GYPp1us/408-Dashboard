package com.mutsumi.focus

import android.content.SharedPreferences
import org.junit.Assert.*
import org.junit.Test

class FocusStateStoreTest {
    private val minute = 60_000L
    private val paused = FocusRuntimeState(mode = FocusMode.PAUSED, sessionId = 8,
        pausedAtEpochMs = minute, elapsedSeconds = 1800, observedAtEpochMs = minute)

    @Test fun `an active reminder keeps expansion through clock updates and recreation until closed`() {
        val prefs = MemoryPreferences()
        val store = FocusStateStore(prefs)
        store.write(paused)
        val token = store.reminderToken(ReminderKind.PAUSED, 6 * minute)
        assertEquals(AtomicRefreshPolicy.ReminderPresentation(true, true),
            AtomicRefreshPolicy.reminderPresentation(true, true, token, store.wasIslandPresented(token)))
        store.markIslandPresented(token)
        val restored = FocusStateStore(prefs)
        for (second in 0..12) {
            val latest = restored.reminderToken(ReminderKind.PAUSED, 6 * minute + second * 1000)
            assertEquals(AtomicRefreshPolicy.ReminderPresentation(true, false),
                AtomicRefreshPolicy.reminderPresentation(true, true, latest, restored.wasIslandPresented(latest)))
        }
        restored.closeReminders()
        assertNull(restored.due(8 * minute))
        assertFalse(AtomicRefreshPolicy.reminderPresentation(true, true, "", false).expanded)
        assertFalse(AtomicRefreshPolicy.reminderPresentation(true, false, token, false).expanded)
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
