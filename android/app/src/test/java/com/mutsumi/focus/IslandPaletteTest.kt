package com.mutsumi.focus

import org.junit.Assert.*
import org.junit.Test

class IslandPaletteTest {
    @Test fun `all public glyph and capsule fields use the supplied current theme color`() {
        val color = IslandPalette(0xFF3C608C.toInt())
        for (mode in FocusMode.entries) {
            val layout = AtomicIslandLayout.from(FocusRuntimeState(mode = mode, plannedSeconds = 600), null, 1000)
            val wire = layout.wire(false, color)
            val base = wire["notification.superx.baseInfos"] as Map<*, *>
            assertEquals(color.accent, base["notification.superx.baseInfos.subCapsuleBgColor"])
            val right = ((wire["notification.superx.island"] as Map<*, *>)["island.superx.rightInfo"] as Map<*, *>)
            if (layout.rightTemplate == 2) assertEquals(color.accent, right["island.superx.rightInfo.progressColor"])
            if (layout.rightTemplate == 3) assertEquals(color.accent, right["island.superx.rightInfo.loadingColor"])
        }
    }

    @Test fun `fallback follows dashboard phase and palette rather than a fixed clay icon`() {
        assertNotEquals(IslandPalette.fallback("clay", FocusMode.REST), IslandPalette.fallback("ocean", FocusMode.REST))
        assertEquals(IslandPalette.fallback("sage", FocusMode.FOCUSING), IslandPalette.fallback("sage", FocusMode.PAUSED))
        assertEquals(0xFF8067B3.toInt(), IslandPalette.fallback("clay", FocusMode.FOCUSING).accent)
        assertEquals(0xFF6F8F78.toInt(), IslandPalette.fallback("clay", FocusMode.SETTLED).accent)
    }

    @Test fun `capsule label switches contrast without changing the theme color`() {
        assertEquals(0xFFFFFFFF.toInt(), IslandPalette(0xFF3C608C.toInt()).buttonText)
        assertEquals(0xFF141414.toInt(), IslandPalette(0xFFE49B88.toInt()).buttonText)
    }
}
