package com.mutsumi.focus

import java.util.Locale

/** Shared vocabulary and clock meanings for the notification, island and WebView. */
object FocusPresentation {
    fun clock(seconds: Long): String {
        val value = seconds.coerceAtLeast(0)
        return String.format(Locale.ROOT, "%02d:%02d:%02d", value / 3600, value / 60 % 60, value % 60)
    }

    fun title(state: FocusRuntimeState, due: DueReminder?, now: Long): String = when (state.mode) {
        FocusMode.FOCUSING -> "专注中"
        FocusMode.PAUSED -> if (due != null) "暂停超时" else "专注已暂停"
        FocusMode.REST -> "主动休息"
        FocusMode.ENDED -> if (state.summaryVisible(now)) "本段专注已结束" else "等待下一段专注"
        FocusMode.SETTLED -> "今日已结算"
        FocusMode.IDLE -> "准备开始专注"
    }

    fun timer(state: FocusRuntimeState, now: Long): String = when (state.mode) {
        FocusMode.REST -> clock(if (state.restTargetSeconds > 0)
            (state.restTargetSeconds - state.restElapsed(now)).coerceAtLeast(0) else state.restElapsed(now))
        else -> clock(state.elapsedNow(now))
    }

    fun detail(state: FocusRuntimeState, nextAt: Long, due: DueReminder?, now: Long): String = when (state.mode) {
        FocusMode.FOCUSING -> "有效专注 ${timer(state, now)}" +
            if (state.plannedSeconds > 0) " · 目标 ${clock(state.plannedSeconds)}" else " · 自由计时"
        FocusMode.PAUSED -> "有效 ${timer(state, now)} · 暂停 ${clock((now - state.pausedAtEpochMs).coerceAtLeast(0) / 1000)} · " +
            if (due != null) "暂停超时" else if (nextAt > 0) "下次提醒 ${clock((nextAt - now).coerceAtLeast(0) / 1000)} 后" else "本次提醒已收起"
        FocusMode.REST -> (if (state.restTargetSeconds > 0) "休息剩余 " else "已休息 ") + timer(state, now) + " · 不催促专注"
        FocusMode.ENDED -> "有效专注 ${timer(state, now)} · " +
            if (due != null) reminderTitle(due.kind) else if (nextAt > 0) "下次提醒 ${clock((nextAt - now).coerceAtLeast(0) / 1000)} 后" else "离开提醒已完成"
        FocusMode.SETTLED -> "今天已收官 · 离开提醒已停止"
        FocusMode.IDLE -> "选择事项，开始下一段"
    }

    fun reminderTitle(kind: ReminderKind): String = when (kind) {
        ReminderKind.PAUSED -> "暂停满 5 分钟"
        ReminderKind.ENDED_15 -> "离开专注满 15 分钟"
        ReminderKind.ENDED_30 -> "离开专注满 30 分钟"
        ReminderKind.ENDED_60 -> "离开专注满 60 分钟"
    }

    fun shortName(name: String): String = if (name.codePointCount(0, name.length) <= 6) name
        else name.substring(0, name.offsetByCodePoints(0, 5)) + "…"
}
