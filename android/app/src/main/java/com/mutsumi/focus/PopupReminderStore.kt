package com.mutsumi.focus

import android.content.Context
import android.content.SharedPreferences

internal class PopupReminderStore(private val prefs: SharedPreferences) {
    constructor(context: Context) : this(context.getSharedPreferences("focus_popup_v1", Context.MODE_PRIVATE))

    var enabled: Boolean
        get() = prefs.getBoolean("enabled", false)
        set(value) { prefs.edit().putBoolean("enabled", value).apply() }
    var pauseMinutes: Int
        get() = prefs.getInt("pause_minutes", 12)
        set(value) { prefs.edit().putInt("pause_minutes", if (value == 0) 0 else value.coerceIn(6, 120)).apply() }
    var idleMinutes: Int
        get() = prefs.getInt("idle_minutes", 20)
        set(value) { prefs.edit().putInt("idle_minutes", if (value == 0) 0 else value.coerceIn(6, 120)).apply() }
    var muteOptions: List<Int>
        get() = prefs.getString("mute_options", "").orEmpty().split(',').mapNotNull(String::toIntOrNull)
            .filter { it in 1..240 }.distinct().sorted().takeIf { it.size == 3 } ?: PopupReminderPolicy.DEFAULT_MUTE
        set(value) { if (value.size == 3 && value.distinct().size == 3 && value.all { it in 1..240 })
            prefs.edit().putString("mute_options", value.sorted().joinToString(",")).apply() }

    fun edgePosition(horizontal: Boolean): Float = prefs.getFloat(edgePositionKey(horizontal), 0f)
    fun saveEdgePosition(horizontal: Boolean, fraction: Float) {
        prefs.edit().putFloat(edgePositionKey(horizontal), fraction).apply()
    }
    private fun edgePositionKey(horizontal: Boolean) = if (horizontal) "edge_position_landscape" else "edge_position_portrait"

    val muteUntil: Long get() = prefs.getLong("mute_until", 0)
    fun muted(now: Long) = now < muteUntil
    fun beginPhase(key: String) {
        if (prefs.getString("delay_phase", "") == key) return
        prefs.edit().putString("delay_phase", key).putBoolean("free_delay_used", false)
            .putBoolean("minute_delay_used", false).apply()
    }
    val freeDelayAvailable: Boolean get() = !prefs.getBoolean("free_delay_used", false)
    val minuteDelayAvailable: Boolean get() = !prefs.getBoolean("minute_delay_used", false)
    fun delayWithoutQuestion(minutes: Int, now: Long, extraMinute: Boolean = false): Boolean {
        if (extraMinute && minutes != 1) return false
        val bonus = extraMinute
        if (bonus && !minuteDelayAvailable || !bonus && (!freeDelayAvailable || minutes !in muteOptions)) return false
        prefs.edit().putBoolean(if (bonus) "minute_delay_used" else "free_delay_used", true)
            .putLong("mute_until", maxOf(now, muteUntil) + minutes * 60_000L)
            .remove("pending").remove("returning").apply()
        return true
    }
    fun mute(minutes: Int, now: Long) {
        if (minutes !in muteOptions) return
        prefs.edit().putLong("mute_until", now + minutes * 60_000L).remove("pending").remove("returning").apply()
    }
    val pending: String get() = prefs.getString("pending", "").orEmpty()
    val returning: Boolean get() = prefs.getBoolean("returning", false)
    fun trigger(key: String) { prefs.edit().putString("pending", key).putBoolean("returning", false).apply() }
    fun returnToFocus() { if (pending.isNotBlank()) prefs.edit().putBoolean("returning", true).apply() }
    fun resolve() { prefs.edit().remove("pending").remove("returning").apply() }

    val accountGeneration: Long get() = prefs.getLong("account_generation", 0)
    fun clearAccount() {
        prefs.edit().remove("pending").remove("returning").remove("mute_until").remove("bank")
            .remove("delay_phase").remove("free_delay_used").remove("minute_delay_used")
            .putLong("account_generation", accountGeneration + 1).apply()
    }
    var bankJson: String
        get() = prefs.getString("bank", "").orEmpty()
        set(value) { prefs.edit().putString("bank", value).apply() }
}
