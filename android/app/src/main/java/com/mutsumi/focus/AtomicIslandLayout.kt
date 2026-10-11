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
) {
    enum class Glyph { BRAND, START, COMPLETE }
    enum class Click { PRIMARY, HOME }
    data class Button(val label: String, val action: String)

    fun wire(forceShowCard: Boolean): Map<String, Any> {
        val accent = 0xFFB94A43.toInt()
        val base = linkedMapOf<String, Any>(
            "notification.superx.baseInfos.icon" to Glyph.BRAND,
            "notification.superx.baseInfos.title" to title,
            "notification.superx.baseInfos.content" to subtitle,
            "notification.superx.baseInfos.subInfo" to 2,
            "notification.superx.baseInfos.subText" to button.label,
            "notification.superx.baseInfos.subTextColor" to 0xFFFFFFFF.toInt(),
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
                "notification.superx.infos.BgColor" to 0x66534541,
            )
            else -> linkedMapOf(
                "notification.superx.infos.leftMain" to leftValue,
                "notification.superx.infos.leftSub" to leftLabel,
                "notification.superx.infos.rightMain" to rightValue,
                "notification.superx.infos.rightSub" to rightLabel,
                "notification.superx.infos.midMainType" to 2,
                "notification.superx.infos.midMainMsg" to "·",
            )
        }
        val right: Map<String, Any> = when (rightTemplate) {
            2 -> linkedMapOf(
                "island.superx.rightInfo.progressValue" to progress,
                "island.superx.rightInfo.progressColor" to accent,
                "island.superx.rightInfo.progressBgColor" to 0xFF534541.toInt(),
                "island.superx.rightInfo.progressState" to if (completed) 1 else 0,
            )
            3 -> mapOf("island.superx.rightInfo.loadingColor" to accent)
            else -> mapOf("island.superx.rightInfo.content" to rightText)
        }
        val island = linkedMapOf<String, Any>(
            "island.superx.leftTemplate" to 1,
            "island.superx.leftInfo" to mapOf("island.superx.leftInfo.icon" to Glyph.BRAND,
                "island.superx.leftInfo.content" to title),
            "island.superx.rightTemplate" to rightTemplate,
            "island.superx.rightInfo" to right,
            "island.superx.islandClick" to 0,
            "island.superx.clickResp" to Click.HOME,
            "island.superx.template" to template,
            "island.superx.baseInfos" to base,
            "island.superx.infos" to info,
            "island.superx.forceShowCard" to forceShowCard,
        )
        return linkedMapOf(
            "notification.superx.template" to template,
            "notification.superx.baseInfos" to base,
            "notification.superx.infos" to info,
            "notification.superx.shortInfos" to mapOf(
                "notification.superx.shortInfos.icon" to Glyph.BRAND,
                "notification.superx.shortInfos.image" to Glyph.BRAND,
                "notification.superx.shortInfos.coreInfoShort" to when (template) { 1 -> core; 3 -> leftValue; else -> subtitle },
                "notification.superx.shortInfos.describeShort" to title,
            ),
            "notification.superx.capsule" to mapOf(
                "notification.superx.capsule.state" to 1,
                "notification.superx.capsule.icon" to Glyph.BRAND,
                "notification.superx.capsule.content" to title,
                "notification.superx.capsule.clickResp" to Click.HOME,
            ),
            "notification.superx.island" to island,
        )
    }

    companion object {
        fun from(state: FocusRuntimeState, due: DueReminder?, now: Long): AtomicIslandLayout {
            val elapsed = FocusPresentation.clock(state.elapsedNow(now))
            val pauseRound = ((now - state.pausedAtEpochMs).coerceAtLeast(0) / ReminderPolicy.PAUSED_DELAY_MS)
                .coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
            fun progress(elapsedSeconds: Long, target: Long) = if (target > 0)
                (elapsedSeconds * 100 / target).coerceIn(0, 100).toInt() else 0
            return when (state.mode) {
                FocusMode.PAUSED -> AtomicIslandLayout(1, "暂停中", "专注计时已暂停", 4,
                    rightText = FocusPresentation.clock((now - state.pausedAtEpochMs).coerceAtLeast(0) / 1000),
                    core = if (pauseRound > 0) "第 $pauseRound 轮提醒" else "等待首次提醒",
                    description = "已暂停 ${FocusPresentation.clock((now - state.pausedAtEpochMs).coerceAtLeast(0) / 1000)}",
                    button = Button("继续专注", "resume"))
                FocusMode.FOCUSING -> AtomicIslandLayout(2, "专注中",
                    if (state.plannedSeconds > 0) "$elapsed / ${FocusPresentation.clock(state.plannedSeconds)}" else "$elapsed · 自由计时",
                    if (state.plannedSeconds > 0) 2 else 3,
                    progress = progress(state.elapsedNow(now), state.plannedSeconds), button = Button("暂停", "pause"))
                FocusMode.REST -> AtomicIslandLayout(1, "休息中", "主动休息", if (state.restTargetSeconds > 0) 2 else 3,
                    progress = progress(state.restElapsed(now), state.restTargetSeconds), core = FocusPresentation.timer(state, now),
                    description = if (state.restTargetSeconds > 0) "休息剩余" else "已休息",
                    button = Button("结束休息", "endRest"))
                FocusMode.SETTLED -> AtomicIslandLayout(3, "今日结算", "今日专注统计", 2, progress = 100, completed = true,
                    leftValue = FocusPresentation.clock(state.todayFocusSeconds), leftLabel = "有效专注",
                    rightValue = "${state.todaySessionCount} 段", rightLabel = "专注次数", button = Button("查看总结", "summary"))
                FocusMode.ENDED -> if (due != null) AtomicIslandLayout(1, "专注提醒", "准备好后开始下一段", 3,
                    core = "第 ${due.round} 轮提醒", description = "已离开 ${FocusPresentation.clock((now - state.endedAtEpochMs).coerceAtLeast(0) / 1000)}",
                    button = Button("开始专注", "next"))
                else AtomicIslandLayout(3, "专注结束", "本段专注统计", 2, progress = 100, completed = true,
                    leftValue = elapsed, leftLabel = "有效专注", rightValue = FocusPresentation.clock(state.pausedSeconds),
                    rightLabel = "累计暂停", button = Button("查看总结", "summary"))
                FocusMode.IDLE -> AtomicIslandLayout(1, "准备专注", "选择事项开始", 3, core = "开始下一段", description = "准备专注",
                    button = Button("开始专注", "next"))
            }
        }
    }
}
