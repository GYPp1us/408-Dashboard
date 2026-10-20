package com.mutsumi.focus

import org.json.JSONObject

/** TimerFormat understood by the verified ROM's SuperXChronometer. */
data class AtomicSystemTimer(val milliseconds: Long, val countDown: Boolean = false) {
    data class Text(val json: String)
    val seconds: Long get() = milliseconds.coerceAtLeast(0) / 1000
    val direction: Int get() = if (countDown) -1 else 1

    fun text(monotonicMs: Long, compact: Boolean, prefix: String = ""): Text {
        val duration = milliseconds.coerceAtLeast(0)
        // The ROM's HMS formatter cannot add hours to its minute argument.
        // Rebase only at ten-minute boundaries to retain unbounded total m:ss.
        val segment = seconds / 600
        val tail = if (compact) duration % 600_000 else duration
        val tens = if (segment == 0L) "" else segment.toString()
        val ms = if (compact) "$tens%1\$d:%2\$02d" else "%1\$d分钟%2\$d秒"
        return Text(JSONObject().apply {
            put("base", monotonicMs + if (countDown) tail else -tail)
            put("contentFormat", "$prefix%s")
            put("countDown", countDown)
            put("elapsedFormatHMS", if (compact) ms else "%1\$d小时%2\$d分钟")
            put("elapsedFormatMS", ms)
            put("elapsedFormatS", "%1\$d")
            put("minUnit", "M")
            put("started", true)
        }.toString())
    }

    fun renderKey(progress: Int = 0): String = "${seconds / 600}:$progress"

    fun wire(source: Map<String, Any>, monotonicMs: Long): Map<String, Any> {
        val small = text(monotonicMs, true)
        val large = text(monotonicMs, false)
        val smallValue = IslandTime.small(seconds)
        val largeValue = IslandTime.large(seconds)
        fun replace(values: Map<String, Any>): Map<String, Any> = values.mapValues { (key, value) ->
            when {
                value is Map<*, *> -> {
                    @Suppress("UNCHECKED_CAST")
                    replace(value as Map<String, Any>)
                }
                key in setOf("island.superx.leftInfo.content", "island.superx.rightInfo.content",
                    "notification.superx.capsule.content") && value == smallValue -> small
                key == "notification.superx.infos.coreInfo" && value == largeValue -> large
                key == "notification.superx.shortInfos.coreInfoShort" && value == smallValue -> small
                key == "notification.superx.shortInfos.coreInfoShort" && value == largeValue -> large
                key == "notification.superx.baseInfos.content" && value is String && value.endsWith(largeValue) ->
                    text(monotonicMs, false, value.removeSuffix(largeValue))
                else -> value
            }
        }
        return replace(source)
    }

    companion object {
        fun supported(model: String, build: String): Boolean = model == "V2505A" && build == "PD2505B_A_17.1.9.0.W10"

        fun from(state: FocusRuntimeState, now: Long, countdown: IslandContext.Countdown? = null,
                 reminder: Boolean = false): AtomicSystemTimer? {
            if (countdown != null) return if (countdown.kind == IslandContext.Countdown.Kind.WAITING)
                AtomicSystemTimer((now - countdown.end).coerceAtLeast(0))
            else AtomicSystemTimer((countdown.end - now).coerceAtLeast(0) + 999, true)
            return when (state.mode) {
                FocusMode.FOCUSING -> AtomicSystemTimer(state.elapsedSeconds * 1000 + (now - state.observedAtEpochMs).coerceAtLeast(0))
                FocusMode.PAUSED -> AtomicSystemTimer((now - state.pausedAtEpochMs).coerceAtLeast(0))
                FocusMode.REST -> AtomicSystemTimer((now - state.restStartedAtEpochMs).coerceAtLeast(0))
                FocusMode.ENDED -> if (reminder) AtomicSystemTimer((now - state.endedAtEpochMs).coerceAtLeast(0)) else null
                else -> null
            }
        }
    }
}
