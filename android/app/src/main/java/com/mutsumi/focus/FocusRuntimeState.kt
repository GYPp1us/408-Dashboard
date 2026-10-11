package com.mutsumi.focus

import org.json.JSONObject

enum class FocusMode {
    IDLE,
    FOCUSING,
    PAUSED,
    REST,
    ENDED,
    SETTLED;

    companion object {
        fun fromWire(value: String?): FocusMode = when (value?.lowercase()) {
            "focusing" -> FOCUSING
            "paused" -> PAUSED
            "rest" -> REST
            "ended" -> ENDED
            "settled" -> SETTLED
            else -> IDLE
        }
    }
}

data class FocusRuntimeState(
    val mode: FocusMode = FocusMode.IDLE,
    val sessionId: Long = 0,
    val subject: String = "",
    val startedAtEpochMs: Long = 0,
    val pausedAtEpochMs: Long = 0,
    val endedAtEpochMs: Long = 0,
    val elapsedSeconds: Long = 0,
    val pausedSeconds: Long = 0,
    val todayFocusSeconds: Long = 0,
    val todaySessionCount: Int = 0,
    val plannedSeconds: Long = 0,
    val focusItemId: Long = 0,
    val restStartedAtEpochMs: Long = 0,
    val restTargetSeconds: Long = 0,
    val observedAtEpochMs: Long = System.currentTimeMillis(),
    val baseUrl: String = BuildConfig.DASHBOARD_URL.trimEnd('/'),
) {
    companion object {
        fun fromJson(raw: String): FocusRuntimeState {
            val data = JSONObject(raw)
            return FocusRuntimeState(
                mode = FocusMode.fromWire(data.optString("mode")),
                sessionId = data.optLong("sessionId"),
                subject = data.optString("subject").take(120),
                startedAtEpochMs = data.optLong("startedAtEpochMs"),
                pausedAtEpochMs = data.optLong("pausedAtEpochMs"),
                endedAtEpochMs = data.optLong("endedAtEpochMs"),
                elapsedSeconds = data.optLong("elapsedSeconds").coerceAtLeast(0),
                pausedSeconds = data.optLong("pausedSeconds").coerceAtLeast(0),
                todayFocusSeconds = data.optLong("todayFocusSeconds").coerceAtLeast(0),
                todaySessionCount = data.optInt("todaySessionCount").coerceAtLeast(0),
                plannedSeconds = data.optLong("plannedSeconds").coerceIn(0, 86_400),
                focusItemId = data.optLong("focusItemId").coerceAtLeast(0),
                restStartedAtEpochMs = data.optLong("restStartedAtEpochMs").coerceAtLeast(0),
                restTargetSeconds = data.optLong("restTargetSeconds").coerceIn(0, 86_400),
                observedAtEpochMs = System.currentTimeMillis(),
                baseUrl = trustedBaseUrl(data.optString("baseUrl")),
            )
        }

        private fun trustedBaseUrl(candidate: String): String {
            val configured = BuildConfig.DASHBOARD_URL.trimEnd('/')
            return if (candidate.trimEnd('/') == configured) configured else configured
        }
    }

    fun elapsedNow(nowEpochMs: Long = System.currentTimeMillis()): Long =
        elapsedSeconds + if (mode == FocusMode.FOCUSING) {
            ((nowEpochMs - observedAtEpochMs).coerceAtLeast(0) / 1000)
        } else 0

    fun restElapsed(nowEpochMs: Long): Long = if (restStartedAtEpochMs > 0)
        (nowEpochMs - restStartedAtEpochMs).coerceAtLeast(0) / 1000 else 0

    fun summaryVisible(nowEpochMs: Long): Boolean = mode in setOf(FocusMode.ENDED, FocusMode.SETTLED) &&
        endedAtEpochMs > 0 && nowEpochMs - endedAtEpochMs in 0 until 30_000
}

enum class ReminderKind(val endedIndex: Int = 0) {
    PAUSED,
    ENDED_15(1),
    ENDED_30(2),
    ENDED_60(3),
}

data class DueReminder(val kind: ReminderKind, val overdueMs: Long, val round: Int = kind.endedIndex.coerceAtLeast(1))

object ReminderPolicy {
    const val PAUSED_DELAY_MS = 5 * 60_000L
    private val endedThresholds = longArrayOf(15 * 60_000L, 30 * 60_000L, 60 * 60_000L)

    fun acknowledgedCount(current: Int, incomingIndex: Int): Int = maxOf(current, incomingIndex).coerceIn(0, 3)

    fun due(
        state: FocusRuntimeState,
        nowEpochMs: Long,
        pausedSnoozeUntilEpochMs: Long,
        endedAcknowledgedCount: Int,
        pausedDismissed: Boolean = false,
        endedSnoozeUntilEpochMs: Long = 0,
    ): DueReminder? {
        return when (state.mode) {
            FocusMode.PAUSED -> {
                if (pausedDismissed) return null
                val baseDue = state.pausedAtEpochMs.takeIf { it > 0 }?.plus(PAUSED_DELAY_MS) ?: return null
                val dueAt = maxOf(baseDue, pausedSnoozeUntilEpochMs)
                if (nowEpochMs < dueAt) return null
                // A long absence advances directly to the current five-minute
                // round; it must never replay all the missed reminders.
                val round = ((nowEpochMs - state.pausedAtEpochMs) / PAUSED_DELAY_MS).coerceIn(1, Int.MAX_VALUE.toLong()).toInt()
                val roundAt = maxOf(state.pausedAtEpochMs + round * PAUSED_DELAY_MS, pausedSnoozeUntilEpochMs)
                DueReminder(ReminderKind.PAUSED, nowEpochMs - roundAt, round)
            }
            FocusMode.ENDED -> {
                val index = endedAcknowledgedCount.coerceIn(0, endedThresholds.size)
                if (state.endedAtEpochMs <= 0 || index >= endedThresholds.size) return null
                if (nowEpochMs < endedSnoozeUntilEpochMs) return null
                // After a long offline period show the latest relevant stage,
                // never a burst of all missed reminders.
                val reached = endedThresholds.indexOfLast { nowEpochMs >= state.endedAtEpochMs + it }
                val dueAt = maxOf(state.endedAtEpochMs + endedThresholds[index], endedSnoozeUntilEpochMs)
                if (reached >= index && nowEpochMs >= dueAt) {
                    DueReminder(ReminderKind.entries[reached + 1], nowEpochMs - dueAt)
                } else null
            }
            else -> null
        }
    }

    fun nextAt(state: FocusRuntimeState, pausedSnooze: Long, endedCount: Int,
               pausedDismissed: Boolean = false, endedSnooze: Long = 0): Long = when (state.mode) {
        FocusMode.PAUSED -> if (pausedDismissed || state.pausedAtEpochMs <= 0) 0
            else maxOf(state.pausedAtEpochMs + PAUSED_DELAY_MS, pausedSnooze)
        FocusMode.ENDED -> if (endedCount >= endedThresholds.size || state.endedAtEpochMs <= 0) 0
            else maxOf(state.endedAtEpochMs + endedThresholds[endedCount.coerceAtLeast(0)], endedSnooze)
        else -> 0
    }
}
