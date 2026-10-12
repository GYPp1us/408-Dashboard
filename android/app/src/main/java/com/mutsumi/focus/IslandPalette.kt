package com.mutsumi.focus

/** Matches the dashboard's current accent; fallback mirrors its mode/palette tokens. */
data class IslandPalette(val accent: Int) {
    val progressBackground: Int get() = (accent and 0x00FFFFFF) or 0x55000000
    val buttonText: Int get() {
        fun channel(shift: Int): Double {
            val c = ((accent shr shift) and 255) / 255.0
            return if (c <= .04045) c / 12.92 else Math.pow((c + .055) / 1.055, 2.4)
        }
        val luminance = .2126 * channel(16) + .7152 * channel(8) + .0722 * channel(0)
        return if (1.05 / (luminance + .05) >= 4.5) 0xFFFFFFFF.toInt() else 0xFF141414.toInt()
    }

    companion object {
        fun group(mode: FocusMode): String = when (mode) {
            FocusMode.FOCUSING, FocusMode.PAUSED -> "focus"
            FocusMode.SETTLED -> "settled"
            else -> "normal"
        }
        fun fallback(palette: String, mode: FocusMode): IslandPalette = IslandPalette(when (group(mode)) {
            "focus" -> 0xFF8067B3.toInt()
            "settled" -> 0xFF6F8F78.toInt()
            else -> when (palette) {
                "sage" -> 0xFF638576.toInt()
                "ocean" -> 0xFF587EAA.toInt()
                else -> 0xFFD66C58.toInt()
            }
        })
    }
}
