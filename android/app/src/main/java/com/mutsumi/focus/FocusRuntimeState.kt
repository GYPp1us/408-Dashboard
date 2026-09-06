package com.mutsumi.focus

import org.json.JSONObject

enum class FocusMode {
    IDLE,
    FOCUSING,
    PAUSED,
    REST,
    ENDED;

    companion object {
        fun fromWire(value: String?): FocusMode = when (value?.lowercase()) {
            "focusing" -> FOCUSING
            "paused" -> PAUSED
            "rest" -> REST
            "ended" -> ENDED
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
}

enum class ReminderKind(val endedIndex: Int = 0) {
    PAUSED,
    ENDED_15(1),
    ENDED_30(2),
    ENDED_60(3),
}

data class DueReminder(val kind: ReminderKind, val overdueMs: Long)

object ReminderPolicy {
    const val PAUSED_DELAY_MS = 5 * 60_000L
    private val endedThresholds = longArrayOf(15 * 60_000L, 30 * 60_000L, 60 * 60_000L)

    fun due(
        state: FocusRuntimeState,
        nowEpochMs: Long,
        pausedSnoozeUntilEpochMs: Long,
        endedAcknowledgedCount: Int,
    ): DueReminder? {
        return when (state.mode) {
            FocusMode.PAUSED -> {
                val baseDue = state.pausedAtEpochMs.takeIf { it > 0 }?.plus(PAUSED_DELAY_MS) ?: return null
                val dueAt = maxOf(baseDue, pausedSnoozeUntilEpochMs)
                if (nowEpochMs >= dueAt) DueReminder(ReminderKind.PAUSED, nowEpochMs - dueAt) else null
            }
            FocusMode.ENDED -> {
                val index = endedAcknowledgedCount.coerceIn(0, endedThresholds.size)
                if (state.endedAtEpochMs <= 0 || index >= endedThresholds.size) return null
                val dueAt = state.endedAtEpochMs + endedThresholds[index]
                if (nowEpochMs >= dueAt) {
                    DueReminder(ReminderKind.entries[index + 1], nowEpochMs - dueAt)
                } else null
            }
            else -> null
        }
    }
}
