package com.mutsumi.focus

/** doc895 layouts, emitted using doc896's public fields. No user subject on the collapsed island. */
data class AtomicIslandLayout(
    val template: Int,
    val title: String,
    val subtitle: String,
    val rightTemplate: Int,
    val rightText: String = "",
    val progress: Int = 0,
    val completed: Boolean = false,
    val core: String = "",
    val description: String = "",
    val leftValue: String = "",
    val leftLabel: String = "",
    val rightValue: String = "",
    val rightLabel: String = "",
    val button: Button,
    val collapsedText: String = title,
    val middleValue: String = "",
    val middleLabel: String = "",
    val dayOffset: Int = 0,
    val displayNode: Int = 0,
) {
    enum class Glyph { BRAND, START, COMPLETE }
    enum class Click { PRIMARY, HOME }
    data class Button(val label: String, val action: String)

    fun wire(forceShowCard: Boolean?, palette: IslandPalette = IslandPalette.fallback("clay", FocusMode.IDLE), showSeconds: Int = 0): Map<String, Any> {
        val accent = palette.accent
        val base = linkedMapOf<String, Any>(
            "notification.superx.baseInfos.icon" to Glyph.BRAND,
            "notification.superx.baseInfos.title" to title,
            "notification.superx.baseInfos.content" to subtitle,
            "notification.superx.baseInfos.subInfo" to 2,
            "notification.superx.baseInfos.subText" to button.label,
            "notification.superx.baseInfos.subTextColor" to palette.buttonText,
            "notification.superx.baseInfos.subCapsuleBgColor" to accent,
            "notification.superx.baseInfos.subInfoClickResp" to Click.PRIMARY,
        )
        val info: Map<String, Any> = when (template) {
            1 -> linkedMapOf(
                "notification.superx.infos.coreInfo" to core,
                "notification.superx.infos.describe" to description,
                "notification.superx.infos.image" to Glyph.BRAND,
            )
            2 -> linkedMapOf(
                "notification.superx.infos.nodeIcon" to listOf(Glyph.START, Glyph.COMPLETE),
                "notification.superx.infos.progress" to progress,
                "notification.superx.infos.progressColor" to accent,
                "notification.superx.infos.BgColor" to palette.progressBackground,
            )
            else -> linkedMapOf(
                "notification.superx.infos.leftMain" to leftValue,
                "notification.superx.infos.leftSub" to leftLabel,
                "notification.superx.infos.rightMain" to rightValue,
                "notification.superx.infos.rightSub" to rightLabel,
                "notification.superx.infos.midMainType" to 2,
                "notification.superx.infos.midMainMsg" to "—",
                "notification.superx.infos.midTopMsg" to middleValue,
                "notification.superx.infos.midSubType" to 2,
                "notification.superx.infos.midSubMsg" to middleLabel,
            ).also { if (dayOffset > 0) it["notification.superx.infos.rightMainExtra"] = "+${dayOffset}天" }
        }
        val right: Map<String, Any> = when (rightTemplate) {
            2 -> linkedMapOf(
                "island.superx.rightInfo.progressValue" to progress,
                "island.superx.rightInfo.progressColor" to accent,
                "island.superx.rightInfo.progressBgColor" to palette.progressBackground,
                "island.superx.rightInfo.progressState" to if (completed) 1 else 0,
            )
            3 -> mapOf("island.superx.rightInfo.loadingColor" to accent)
            else -> mapOf("island.superx.rightInfo.content" to rightText)
        }
        val island = linkedMapOf<String, Any>(
            "island.superx.leftTemplate" to 1,
            "island.superx.leftInfo" to mapOf("island.superx.leftInfo.icon" to Glyph.BRAND,
                "island.superx.leftInfo.content" to collapsedText),
            "island.superx.rightTemplate" to rightTemplate,
            "island.superx.rightInfo" to right,
            "island.superx.islandClick" to 0,
            "island.superx.clickResp" to Click.HOME,
            "island.superx.template" to template,
            "island.superx.baseInfos" to base,
            "island.superx.infos" to info,
        )
        // Expansion is an edge-triggered request, not part of the live clock.
        // Omitting it on UPDATE leaves the user's expand/collapse choice alone.
        if (forceShowCard != null) island["island.superx.forceShowCard"] = forceShowCard
        if (showSeconds > 0) island["island.superx.showTime"] = showSeconds
        return linkedMapOf(
            "notification.superx.template" to template,
            "notification.superx.baseInfos" to base,
            "notification.superx.infos" to info,
            "notification.superx.shortInfos" to mapOf(
                "notification.superx.shortInfos.icon" to Glyph.BRAND,
                "notification.superx.shortInfos.image" to Glyph.BRAND,
                // A fixed-format clock avoids changing unit words / width on
                // the desktop compact card; statistics still update each second.
                "notification.superx.shortInfos.coreInfoShort" to when (template) { 1 -> core; 3 -> leftValue; else -> collapsedText },
                "notification.superx.shortInfos.describeShort" to title,
            ),
            "notification.superx.capsule" to mapOf(
                "notification.superx.capsule.state" to 1,
                "notification.superx.capsule.icon" to Glyph.BRAND,
                "notification.superx.capsule.content" to if (rightText.isNotEmpty()) rightText else collapsedText,
                "notification.superx.capsule.clickResp" to Click.HOME,
            ),
            "notification.superx.island" to island,
        )
    }

    companion object {
        fun from(state: FocusRuntimeState, due: DueReminder?, now: Long, remindersClosed: Boolean = false,
                 countdown: IslandContext.Countdown? = null, taskSync: IslandContext.TaskSync? = null): AtomicIslandLayout {
            if (taskSync != null && state.mode == FocusMode.SETTLED && due == null) {
                val label = when (taskSync.status) {
                    "pending" -> "正在同步"
                    "sent" -> "同步成功"
                    "failed" -> "推送待重试"
                    else -> "待配置接收端"
                }
                return AtomicIslandLayout(1, "每日任务同步", "$label · ${taskSync.completed}/${taskSync.total} 项已完成",
                    if (taskSync.status == "pending") 3 else 4,
                    rightText = "${taskSync.completed}/${taskSync.total}", core = label,
                    description = "${taskSync.completed}/${taskSync.total} 项已完成",
                    collapsedText = when (taskSync.status) { "pending" -> "同步中"; "sent" -> "同步成功"; "failed" -> "待重试"; else -> "待配置" },
                    button = if (taskSync.status == "unconfigured") Button("接入设置", "planIntegration") else Button("查看结算", "summary"),
                    displayNode = 1_000_000)
            }
            if (countdown != null) {
                if (countdown.kind == IslandContext.Countdown.Kind.WAITING) {
                    val elapsed = countdown.remaining(now)
                    return AtomicIslandLayout(1, "等待下一段专注", "开盘后已等待 ${IslandTime.large(elapsed)}", 3,
                        rightText = IslandTime.small(elapsed), core = IslandTime.large(elapsed), description = "开盘后已等待",
                        button = Button("开始专注", "next"), collapsedText = "等待专注", displayNode = 700_000)
                }
                val afternoon = countdown.kind == IslandContext.Countdown.Kind.AFTERNOON
                val remaining = countdown.remaining(now)
                return AtomicIslandLayout(1, if (afternoon) "下午开盘倒计时" else "打卡剩余时间", if (afternoon) "午间休盘" else countdown.name,
                    4, rightText = IslandTime.small(remaining), core = IslandTime.large(remaining),
                    description = if (afternoon) "距下午开盘" else FocusPresentation.shortName(countdown.name),
                    button = if (afternoon) Button("打开首页", "home") else Button("查看打卡", "checkin"),
                    collapsedText = if (afternoon) "下午开盘" else "打卡剩余",
                    displayNode = if (afternoon) 800_000 else 900_000 + (countdown.id % 99_999).toInt())
            }
            val effective = state.elapsedNow(now)
            val elapsed = IslandTime.large(effective)
            val paused = (now - state.pausedAtEpochMs).coerceAtLeast(0) / 1000
            val pauseRound = (paused / 300).coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
            fun progress(elapsedSeconds: Long, target: Long) = if (target > 0)
                (elapsedSeconds * 100 / target).coerceIn(0, 100).toInt() else 0
            return when (state.mode) {
                FocusMode.PAUSED -> AtomicIslandLayout(1, "暂停中", "已暂停 ${IslandTime.large(paused)}", 4,
                    rightText = IslandTime.small(paused),
                    core = if (remindersClosed) "提醒已关闭" else if (pauseRound > 0) "第 $pauseRound 轮提醒" else "等待首次提醒",
                    description = "专注计时已暂停", button = if (due != null) Button("关闭提醒", "closeReminders")
                        else Button("继续专注", "resume"))
                FocusMode.FOCUSING -> AtomicIslandLayout(2, "专注中", "已专注 $elapsed",
                    if (state.plannedSeconds > 0) 2 else 3,
                    progress = progress(effective, state.plannedSeconds), button = Button("暂停", "pause"),
                    collapsedText = IslandTime.small(effective))
                FocusMode.REST -> {
                    val rest = state.restElapsed(now)
                    AtomicIslandLayout(1, "休息中", "主动休息", 4, rightText = IslandTime.small(rest),
                        core = IslandTime.large(rest), description = "已休息", button = Button("结束休息", "endRest"))
                }
                FocusMode.SETTLED -> AtomicIslandLayout(3, "今日结算", "今日专注统计", 2, progress = 100, completed = true,
                    leftValue = IslandTime.large(state.todayFocusSeconds), leftLabel = "有效专注",
                    rightValue = "${state.todaySessionCount} 段", rightLabel = "专注次数", button = Button("查看总结", "summary"),
                    collapsedText = IslandTime.small(state.todayFocusSeconds))
                FocusMode.ENDED -> if (due != null) AtomicIslandLayout(1, "专注提醒", "已离开 ${IslandTime.large((now - state.endedAtEpochMs).coerceAtLeast(0) / 1000)}", 3,
                    core = "第 ${due.round} 轮提醒", description = "准备好后开始下一段",
                    button = Button("关闭提醒", "closeReminders"), collapsedText = IslandTime.small((now - state.endedAtEpochMs).coerceAtLeast(0) / 1000))
                else AtomicIslandLayout(3, "专注结束", "本段专注统计", 2, progress = 100, completed = true,
                    leftValue = IslandTime.point(state.startedAtEpochMs, state), leftLabel = "开始",
                    rightValue = IslandTime.point(state.endedAtEpochMs, state), rightLabel = "结束",
                    button = Button("查看总结", "summary"), collapsedText = IslandTime.small(effective),
                    middleValue = elapsed, middleLabel = "累计有效专注", dayOffset = IslandTime.dayDifference(state))
                FocusMode.IDLE -> AtomicIslandLayout(1, "准备专注", "选择事项开始", 3, core = "开始下一段", description = "准备专注",
                    button = Button("开始专注", "next"))
            }
        }
    }
}
