package com.mutsumi.focus

import android.content.Context
import android.app.Activity
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.ColorDrawable
import android.os.Build
import android.view.WindowManager
import java.util.function.Consumer
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
    val canvas = androidx.core.graphics.ColorUtils.setAlphaComponent(paper, 76)
    val surface = Color.parseColor(if (dark) "#80202832" else "#80FFFAF4")
    val accent = Color.parseColor(when (prefs.getString("theme_palette", "clay")) {
        "sage" -> if (dark) "#91B39F" else "#3E6656"
        "ocean" -> if (dark) "#88A6CB" else "#3C608C"
        else -> if (dark) "#E49B88" else "#B94A43"
    })
    fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()
    fun rounded(color: Int = surface, radius: Int = 8) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(radius).toFloat()
        setStroke(dp(1), Color.parseColor(if (dark) "#404F5A" else "#DFD4CA"))
    }
    fun text(view: TextView, size: Float = 12f) {
        view.textSize = size; view.setTextColor(ink)
        view.typeface = Typeface.create("serif", Typeface.NORMAL)
        view.includeFontPadding = false
    }
    fun button(view: Button, primary: Boolean = false) {
        text(view)
        view.isAllCaps = false
        view.minHeight = dp(34)
        view.minimumHeight = dp(34)
        view.minWidth = 0
        view.minimumWidth = 0
        view.stateListAnimator = null
        view.elevation = 0f
        view.setPadding(dp(12), dp(5), dp(12), dp(5))
        view.background = rounded(if (primary) accent else surface, 7)
        view.setTextColor(if (primary) paper else ink)
    }

    /** Full-window blur behind a translucent setup page; opaque fallback when disabled. */
    fun bindWindow(activity: Activity): () -> Unit {
        if (Build.VERSION.SDK_INT < 31) {
            activity.window.setBackgroundDrawable(ColorDrawable(paper))
            return {}
        }
        val manager = activity.getSystemService(WindowManager::class.java)
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND)
        activity.window.attributes = activity.window.attributes.apply { blurBehindRadius = dp(16) }
        val listener = Consumer<Boolean> { enabled ->
            activity.window.setBackgroundDrawable(ColorDrawable(if (enabled) Color.TRANSPARENT else paper))
        }
        manager.addCrossWindowBlurEnabledListener(listener)
        return { manager.removeCrossWindowBlurEnabledListener(listener) }
    }
}
