package com.mutsumi.focus.localadb

/** The Binder numbering and package-list format are verified on one firmware only. */
internal class AtomicSceneRegistration(private val packageName: String, private val userId: Int = 0) {
    fun interface Shell { fun run(command: String): String }
    data class Mapping(val packageName: String, val scene: String, val enabled: Boolean)
    data class Result(val enabled: Boolean, val before: String, val after: String)

    init {
        require(packageName in CLIENT_PACKAGES) { "仅允许注册当前 Mutsumi Focus 应用" }
        require(userId >= 0)
    }

    fun configure(shell: Shell, enabled: Boolean, saveBefore: (String) -> Unit = {}): Result {
        check(isSupported(shell.run("getprop ro.product.model").trim(), shell.run("getprop ro.build.display.id").trim())) {
            "当前系统版本尚未适配，未修改原子岛配置"
        }
        check(shell.run("id -u").trim() == "2000") { "无线调试没有取得预期的 shell 身份" }
        val beforeText = shell.run(CONFIG_COMMAND)
        val before = parseConfig(beforeText)
        val focus = before.filter { it.scene == SCENE }
        check(focus.all { it.packageName in OWN_PACKAGES }) { "专注场景包含其他应用，停止修改以保留现有配置" }
        val desired = focus.associate { it.packageName to it.enabled }.toMutableMap()
        if (enabled) desired[packageName] = true else desired.remove(packageName)
        saveBefore(beforeText)

        val reply = shell.run(setterCommand(desired))
        check(NO_EXCEPTION.containsMatchIn(reply)) { "系统拒绝了场景注册，未确认启用" }
        val afterText = shell.run(CONFIG_COMMAND)
        val after = parseConfig(afterText)
        check(before.filter { it.scene != SCENE }.toSet() == after.filter { it.scene != SCENE }.toSet()) {
            "其他场景配置发生变化，请保留本机快照并停止操作"
        }
        check(after.filter { it.scene == SCENE }.associate { it.packageName to it.enabled } == desired) {
            "系统没有保存预期的专注场景配置"
        }
        val status = STATUS.find(shell.run("service call notification 210 s16 '$packageName' s16 '$SCENE' i32 $userId"))
            ?: error("无法读取系统场景授权结果")
        check((status.groupValues[1] == "00000001") == enabled) { "场景授权回读与操作结果不一致" }
        return Result(enabled, beforeText, afterText)
    }

    private fun setterCommand(mappings: Map<String, Boolean>): String {
        val ordered = mappings.toSortedMap()
        check(ordered.keys.all { it in OWN_PACKAGES })
        return "service call notification 209 " +
            "i32 1 s16 '$SCENE' i32 1 s16 '${ordered.values.any { it }}' " +
            "i32 1 s16 '${ordered.keys.joinToString("-")}' " +
            "i32 1 s16 '${ordered.values.joinToString("-")}'"
    }

    companion object {
        const val SCENE = "FOCUS_TIMER"
        const val VERIFIED_MODEL = "V2505A"
        const val VERIFIED_BUILD = "PD2505B_A_16.0.30.14.W10"
        private val CLIENT_PACKAGES = setOf("com.mutsumi.focus", "com.mutsumi.focus.debug")
        private val OWN_PACKAGES = CLIENT_PACKAGES + "com.mutsumi.focus.atomiclab"
        // Filter on the device: other apps' notification contents never reach the client.
        const val CONFIG_COMMAND = "dumpsys notification | sed -n '/^SuperXNoti Inform /,/^SUPERX_CHANGED_INFO/p'"
        private val NO_EXCEPTION = Regex("^Result: Parcel\\(\\s*00000000(?:\\s|\\))")
        private val STATUS = Regex("^Result: Parcel\\(\\s*00000000\\s+(0000000[01])(?:\\s|\\))")
        private val PACKAGE = Regex("[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*)+")
        private val ENTRY = Regex("scene ([A-Za-z0-9_]+) switch (true|false)")

        fun isSupported(model: String, display: String) = model == VERIFIED_MODEL && display == VERIFIED_BUILD

        fun parseConfig(text: String): List<Mapping> {
            check(text.length <= 262_144) { "配置输出过大" }
            val lines = text.lines().map { it.trimEnd() }
            check(lines.firstOrNull() == "SuperXNoti Inform" && lines.any { it == "SUPERX_CHANGED_INFO" }) {
                "无法识别系统配置格式，未修改配置"
            }
            val islandIndex = lines.indexOf("Island Info")
            check(islandIndex > 0 && islandIndex < lines.indexOf("SUPERX_CHANGED_INFO")) { "系统配置不完整" }
            val mappings = mutableListOf<Mapping>()
            var app: String? = null
            for (line in lines.subList(1, islandIndex)) {
                if (line.isBlank()) continue
                if (line.startsWith("appInfo ")) {
                    app = line.removePrefix("appInfo ")
                    check(PACKAGE.matches(app)) { "系统包名格式异常" }
                } else {
                    val match = ENTRY.matchEntire(line) ?: error("无法识别场景配置")
                    mappings += Mapping(checkNotNull(app) { "场景缺少应用包名" }, match.groupValues[1], match.groupValues[2].toBoolean())
                }
            }
            check(mappings.map { it.packageName to it.scene }.distinct().size == mappings.size) { "场景配置存在重复项" }
            return mappings
        }
    }
}
