package com.mutsumi.focus

import android.content.Context
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.widget.Button
import android.widget.TextView

/** Native setup follows the account's appearance preferences. */
class SetupStyle(private val context: Context) {
    private val prefs = context.getSharedPreferences("focus_runtime", Context.MODE_PRIVATE)
    val dark = when (prefs.getString("theme_mode", "system")) {
        "dark" -> true
        "light" -> false
        else -> context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
    }
    val ink = Color.parseColor(if (dark) "#E2E8EE" else "#332925")
    val muted = Color.parseColor(if (dark) "#AAB4BC" else "#6C625D")
    val paper = Color.parseColor(if (dark) "#191F27" else "#F4EEE7")
    val surface = Color.parseColor(if (dark) "#EC202832" else "#ECFFFAF4")
    val accent = Color.parseColor(when (prefs.getString("theme_palette", "clay")) {
        "sage" -> if (dark) "#91B39F" else "#3E6656"
        "ocean" -> if (dark) "#88A6CB" else "#3C608C"
        else -> if (dark) "#E49B88" else "#B94A43"
    })
    fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()
    fun rounded(color: Int = surface) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(20).toFloat()
        setStroke(dp(1), Color.parseColor(if (dark) "#404F5A" else "#DFD4CA"))
    }
    fun text(view: TextView, size: Float = 16f) {
        view.textSize = size; view.setTextColor(ink)
        view.typeface = Typeface.create("serif", Typeface.NORMAL)
    }
    fun button(view: Button, primary: Boolean = false) {
        text(view)
        view.isAllCaps = false
        view.minHeight = dp(48)
        view.setPadding(dp(18), dp(8), dp(18), dp(8))
        view.background = rounded(if (primary) accent else surface)
        view.setTextColor(if (primary) paper else ink)
    }
}
