package com.mutsumi.focus.localadb

import org.junit.Assert.*
import org.junit.Test

class AtomicSceneRegistrationTest {
    private val target = "com.mutsumi.focus.debug"
    private val other = AtomicSceneRegistration.Mapping("com.vivo.weather", "WEATHER", true)
    private val production = AtomicSceneRegistration.Mapping("com.mutsumi.focus", "FOCUS_TIMER", true)

    @Test fun enablePreservesExistingAppsAndScenes() {
        val device = Device(mutableListOf(other, production))
        var snapshot = ""
        assertTrue(AtomicSceneRegistration(target).configure(device, true) { snapshot = it }.enabled)
        assertEquals(setOf(other, production, AtomicSceneRegistration.Mapping(target, "FOCUS_TIMER", true)), device.entries.toSet())
        assertTrue(snapshot.contains("com.vivo.weather"))
    }

    @Test fun revokeRemovesOnlyCurrentPackage() {
        val device = Device(mutableListOf(other, production, AtomicSceneRegistration.Mapping(target, "FOCUS_TIMER", true)))
        assertFalse(AtomicSceneRegistration(target).configure(device, false).enabled)
        assertEquals(setOf(other, production), device.entries.toSet())
    }

    @Test fun preserveDisabledOwnedEntry() {
        val disabled = production.copy(enabled = false)
        val device = Device(mutableListOf(other, disabled))
        AtomicSceneRegistration(target).configure(device, true)
        assertTrue(device.entries.contains(disabled))
    }

    @Test fun unknownFirmwareNeverWritesBinder() {
        val device = Device(mutableListOf(other)).apply { build = "new-firmware" }
        expectFailure { AtomicSceneRegistration(target).configure(device, true) }
        assertFalse(device.commands.any { it.startsWith("service call") })
    }

    @Test fun foreignPackageCollisionNeverWritesBinder() {
        val device = Device(mutableListOf(other, AtomicSceneRegistration.Mapping("com.foreign.app", "FOCUS_TIMER", true)))
        expectFailure { AtomicSceneRegistration(target).configure(device, true) }
        assertFalse(device.commands.any { it.startsWith("service call") })
    }

    @Test fun malformedAndDuplicateConfigsAreRejected() {
        expectFailure { AtomicSceneRegistration.parseConfig("SuperXNoti Inform\nappInfo com.a.b\nscene FOCUS_TIMER switch true") }
        expectFailure { AtomicSceneRegistration.parseConfig(config(listOf(other, other))) }
        expectFailure { AtomicSceneRegistration.parseConfig(config(listOf(other)).replace("scene WEATHER", "unexpected WEATHER")) }
    }

    @Test fun binderExceptionCannotReportGranted() {
        val device = Device(mutableListOf(other)).apply { reject = true }
        expectFailure { AtomicSceneRegistration(target).configure(device, true) }
        assertEquals(listOf(other), device.entries)
    }

    @Test fun arbitraryTargetPackageIsRejected() {
        expectFailure { AtomicSceneRegistration("com.foreign.app") }
    }

    private fun expectFailure(block: () -> Unit) {
        try { block(); fail("Expected rejection") }
        catch (_: IllegalArgumentException) { }
        catch (_: IllegalStateException) { }
    }

    private class Device(val entries: MutableList<AtomicSceneRegistration.Mapping>) : AtomicSceneRegistration.Shell {
        val commands = mutableListOf<String>()
        var build = AtomicSceneRegistration.VERIFIED_BUILD
        var reject = false
        override fun run(command: String): String {
            commands += command
            return when {
                command == "getprop ro.product.model" -> AtomicSceneRegistration.VERIFIED_MODEL
                command == "getprop ro.build.display.id" -> build
                command == "id -u" -> "2000\n"
                command == AtomicSceneRegistration.CONFIG_COMMAND -> config(entries)
                command.startsWith("service call notification 209") -> {
                    if (reject) "Result: Parcel(ffffffff)" else {
                        val values = Regex("s16 '([^']*)'").findAll(command).map { it.groupValues[1] }.toList()
                        entries.removeAll { it.scene == "FOCUS_TIMER" }
                        if (values[2].isNotEmpty()) {
                            values[2].split('-').zip(values[3].split('-')).forEach { (name, state) ->
                                entries += AtomicSceneRegistration.Mapping(name, "FOCUS_TIMER", state.toBoolean())
                            }
                        }
                        "Result: Parcel(00000000   '....')"
                    }
                }
                command.startsWith("service call notification 210") -> {
                    val name = Regex("s16 '([^']*)'").find(command)!!.groupValues[1]
                    val bit = if (entries.any { it.packageName == name && it.scene == "FOCUS_TIMER" && it.enabled }) "1" else "0"
                    "Result: Parcel(00000000 0000000$bit   '........')"
                }
                else -> error("Unexpected command")
            }
        }
    }

    companion object {
        private fun config(entries: List<AtomicSceneRegistration.Mapping>) = buildString {
            append("SuperXNoti Inform \n")
            entries.groupBy { it.packageName }.forEach { (name, scenes) ->
                append("appInfo $name\n")
                scenes.forEach { append("scene ${it.scene} switch ${it.enabled}\n") }
            }
            append("\nIsland Info \nSUPERX_CHANGED_INFO\n")
        }
    }
}
