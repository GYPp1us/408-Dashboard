package com.mutsumi.focus

import java.time.Instant
import java.time.ZoneId

/** The full-screen reminder has its own clock. No island reminder round feeds it. */
internal object PopupReminderPolicy {
    const val EARLY_MS = 5 * 60_000L
    const val LEAD_MS = 60_000L
    val DEFAULT_MUTE = listOf(15, 30, 60)

    data class Window(val key: String, val edge: Boolean, val due: Boolean)

    fun window(state: FocusRuntimeState, schedule: IslandContext, now: Long, muteUntil: Long,
               pauseMinutes: Int, idleMinutes: Int): Window? {
        if (muteUntil > now) return null
        val anchor = when (state.mode) {
            FocusMode.FOCUSING -> state.startedAtEpochMs
            FocusMode.PAUSED -> state.pausedAtEpochMs
            FocusMode.ENDED -> {
                val local = Instant.ofEpochMilli(now).atZone(ZoneId.of(schedule.timezone))
                val period = schedule.sessions.firstOrNull { local.toLocalTime() >= it.start && local.toLocalTime() < it.end }
                    ?: return null
                val opening = local.toLocalDate().atTime(period.start).atZone(local.zone).toInstant().toEpochMilli()
                maxOf(state.endedAtEpochMs, opening)
            }
            else -> return null
        }
        if (anchor <= 0 || anchor > now) return null
        val key = "${state.mode}:${state.sessionId}:$anchor"
        val early = state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED) && now - anchor < EARLY_MS
        val minutes = when (state.mode) {
            FocusMode.PAUSED -> pauseMinutes
            FocusMode.ENDED -> idleMinutes
            else -> 0
        }
        if (minutes <= 0) return Window(key, early, false)
        val dueAt = maxOf(anchor, muteUntil) + minutes * 60_000L
        return Window(key, early || now in dueAt - LEAD_MS until dueAt, now >= dueAt)
    }
}
