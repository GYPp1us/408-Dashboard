package com.mutsumi.focus

import java.time.Instant
import java.time.ZoneId

/** Popup timing and the always-available edge share one stable non-focus period. */
internal object PopupReminderPolicy {
    const val LEAD_MS = 60_000L
    val DEFAULT_MUTE = listOf(15, 30, 60)

    const val WAITING_COLOR = 0xffce792f.toInt()
    const val IMMINENT_COLOR = 0xff8162ad.toInt()
    data class Window(val key: String, val edge: Boolean = true, val due: Boolean, val imminent: Boolean, val dueAt: Long? = null)

    fun window(state: FocusRuntimeState, schedule: IslandContext, now: Long, muteUntil: Long,
               pauseMinutes: Int, idleMinutes: Int): Window? {
        if (state.mode == FocusMode.FOCUSING) return null
        val local = Instant.ofEpochMilli(now).atZone(ZoneId.of(schedule.timezone))
        val period = schedule.sessions.firstOrNull { local.toLocalTime() >= it.start && local.toLocalTime() < it.end }
            ?: return null
        val opening = local.toLocalDate().atTime(period.start).atZone(local.zone).toInstant().toEpochMilli()
        val transition = when (state.mode) {
            FocusMode.PAUSED -> state.pausedAtEpochMs
            FocusMode.ENDED -> state.endedAtEpochMs
            FocusMode.REST -> state.restStartedAtEpochMs
            else -> 0
        }
        val anchor = maxOf(opening, transition)
        val key = "${state.mode}:${state.sessionId}:$anchor"
        val minutes = if (state.mode == FocusMode.PAUSED) pauseMinutes else idleMinutes
        val triggers = minutes > 0 && state.mode != FocusMode.SETTLED
        val dueAt = if (muteUntil > anchor) muteUntil else anchor + minutes * 60_000L
        return Window(key, due = triggers && now >= dueAt, imminent = triggers && now >= dueAt - LEAD_MS, dueAt = dueAt.takeIf { triggers })
    }
}
