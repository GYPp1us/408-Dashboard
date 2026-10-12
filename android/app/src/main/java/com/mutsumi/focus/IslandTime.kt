package com.mutsumi.focus

import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Display formats only: never wrap total minutes, cap a duration, or alter stored seconds. */
object IslandTime {
    fun small(seconds: Long): String {
        val value = seconds.coerceAtLeast(0)
        return String.format(Locale.ROOT, "%d:%02d", value / 60, value % 60)
    }

    fun large(seconds: Long): String {
        val value = seconds.coerceAtLeast(0)
        return if (value >= 3600) "${value / 3600}小时${value / 60 % 60}分钟"
        else "${value / 60}分钟${value % 60}秒"
    }

    fun point(epochMs: Long, state: FocusRuntimeState): String {
        if (epochMs <= 0) return "--:--"
        val zone = runCatching { ZoneId.of(state.accountTimeZone) }.getOrElse {
            ZoneOffset.ofTotalSeconds(state.accountOffsetSeconds.coerceIn(-64_800, 64_800))
        }
        return DateTimeFormatter.ofPattern("HH:mm", Locale.ROOT).withZone(zone).format(Instant.ofEpochMilli(epochMs))
    }

    fun dayDifference(state: FocusRuntimeState): Int {
        if (state.startedAtEpochMs <= 0 || state.endedAtEpochMs <= 0) return 0
        val zone = runCatching { ZoneId.of(state.accountTimeZone) }.getOrElse {
            ZoneOffset.ofTotalSeconds(state.accountOffsetSeconds.coerceIn(-64_800, 64_800))
        }
        return java.time.temporal.ChronoUnit.DAYS.between(
            Instant.ofEpochMilli(state.startedAtEpochMs).atZone(zone).toLocalDate(),
            Instant.ofEpochMilli(state.endedAtEpochMs).atZone(zone).toLocalDate()).coerceIn(0, Int.MAX_VALUE.toLong()).toInt()
    }
}
