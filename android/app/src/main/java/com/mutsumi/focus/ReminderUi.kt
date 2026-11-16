package com.mutsumi.focus

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.content.res.ColorStateList
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.graphics.ColorUtils

internal class ReminderUi(val context: Context, val accent: Int) {
    val ink = 0xff272322.toInt()
    val muted = 0xff625b57.toInt()
    val border = ColorUtils.blendARGB(Color.WHITE, accent, .23f)
    val tint = ColorUtils.blendARGB(Color.WHITE, accent, .075f)
    private val accentInk = ColorUtils.blendARGB(accent, ink, .36f)
    fun dp(value: Int) = (value * context.resources.displayMetrics.density + .5f).toInt()
    fun surface(background: Int, radius: Int = 9, stroke: Int? = null) = GradientDrawable().apply {
        setColor(background); cornerRadius = dp(radius).toFloat()
        if (stroke != null) setStroke(dp(1), stroke)
    }
    fun label(value: String, size: Float = 15f, color: Int = ink, bold: Boolean = false) = TextView(context).apply {
        text = value; textSize = size; setTextColor(color)
        typeface = Typeface.create("serif", if (bold) Typeface.BOLD else Typeface.NORMAL)
        setLineSpacing(dp(3).toFloat(), 1f)
    }
    fun vertical() = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    fun add(parent: LinearLayout, view: View, margin: Int = 0, width: Int = -1) {
        parent.addView(view, LinearLayout.LayoutParams(width, -2).apply { topMargin = dp(margin) })
    }
    fun tag(value: String) = label(value, 12f, accentInk, true).apply { letterSpacing = .12f }
    fun button(value: String, primary: Boolean = false, action: () -> Unit) = Button(context).apply {
        text = value; isAllCaps = false; textSize = 15f; gravity = Gravity.CENTER
        typeface = Typeface.create("serif", Typeface.NORMAL)
        minHeight = dp(48); minimumHeight = dp(48); minimumWidth = 0; minWidth = 0
        stateListAnimator = null; elevation = 0f
        setTextColor(if (primary) IslandPalette(accent).buttonText else ink)
        setPadding(dp(10), dp(7), dp(10), dp(7))
        background = RippleDrawable(ColorStateList.valueOf(0x26000000),
            surface(if (primary) accent else tint, stroke = if (primary) null else border), null)
        setOnClickListener { action() }
    }

    fun durations(options: List<Int>, onChoose: (Int) -> Unit) = LinearLayout(context).apply {
        for ((index, minutes) in options.withIndex()) {
            addView(button("$minutes 分钟") { onChoose(minutes) }, LinearLayout.LayoutParams(0, -2, 1f).apply {
                if (index > 0) marginStart = dp(8)
            })
        }
    }

    /** Native markup renderer; question text is never executed or loaded as HTML. */
    fun question(parent: LinearLayout, body: String) {
        val lines = body.lines()
        var i = 0
        while (i < lines.size) {
            val line = lines[i++]
            val kind = line.trim()
            if (kind == "\$\$" || kind.startsWith("```")) {
                val code = kind.startsWith("```")
                val content = mutableListOf<String>()
                while (i < lines.size && (if (code) lines[i].trim() != "```" else lines[i].trim() != "\$\$")) content += lines[i++]
                if (i < lines.size) i++
                if (code) {
                    val pre = label(content.joinToString("\n"), 14f).apply {
                        typeface = Typeface.MONOSPACE; setPadding(dp(12), dp(8), dp(12), dp(8))
                    }
                    add(parent, android.widget.HorizontalScrollView(context).apply {
                        background = surface(tint, stroke = border); addView(pre)
                    }, 8)
                } else add(parent, formula(content.joinToString(" ")), 8)
            } else if (line.isNotBlank()) add(parent, label(ReminderMath.inline(line), 16f), if (parent.childCount == 0) 0 else 4)
        }
    }

    private fun formula(raw: String): View = vertical().apply {
        gravity = Gravity.CENTER_HORIZONTAL; background = surface(tint, stroke = border)
        setPadding(dp(10), dp(9), dp(10), dp(9))
        val expression = ReminderMath.fraction(raw.trim())
        if (expression == null) add(this, label(ReminderMath.symbols(raw), 21f).apply { gravity = Gravity.CENTER })
        else {
            val (prefix, numerator, denominator) = expression
            val row = LinearLayout(context).apply { gravity = Gravity.CENTER_VERTICAL }
            if (prefix.isNotBlank()) row.addView(label(ReminderMath.symbols(prefix), 19f).apply { setPadding(0, 0, dp(8), 0) })
            val stack = vertical().apply {
                add(this, label(ReminderMath.symbols(numerator), 21f).apply { gravity = Gravity.CENTER; setPadding(dp(4), 0, dp(4), 0) })
                addView(View(context).apply { setBackgroundColor(ink) }, LinearLayout.LayoutParams(-1, dp(1)))
                add(this, label(ReminderMath.symbols(denominator), 19f).apply { gravity = Gravity.CENTER })
            }
            row.addView(stack, LinearLayout.LayoutParams(-2, -2))
            add(this, row, width = -2)
        }
    }
}

internal object ReminderMath {
    val frac = Regex("\\\\(?:d?frac)\\s*")
    private val superscript = "⁰¹²³⁴⁵⁶⁷⁸⁹"
    private val subscript = "₀₁₂₃₄₅₆₇₈₉"
    private val tokens = mapOf("to" to "→", "rightarrow" to "→", "infty" to "∞", "pi" to "π", "cdot" to "·",
        "times" to "×", "pm" to "±", "left" to "", "right" to "", "sqrt" to "√", "le" to "≤", "ge" to "≥",
        "alpha" to "α", "beta" to "β", "theta" to "θ")
    fun inline(text: String): String = Regex("\\$([^$]+)\\$").replace(text) { symbols(it.groupValues[1]) }
    fun symbols(value: String): String {
        val fraction = fraction(value.trim())
        if (fraction != null) return symbols(fraction.first) + "(${symbols(fraction.second)})/(${symbols(fraction.third)})"
        return Regex("\\\\([a-zA-Z]+)").replace(value) { tokens[it.groupValues[1]] ?: it.groupValues[1] }
            .replace(Regex("([_^])(?:\\{([^{}]+)\\}|([0-9nx+\\-]))")) { match ->
                val what = match.groupValues[2].ifEmpty { match.groupValues[3] }
                val script = if (match.groupValues[1] == "^") superscript else subscript
                if (what.all { it in '0'..'9' }) what.map { script[it - '0'] }.joinToString("")
                else if (match.groupValues[1] == "^" && what.all { it in "-+nx0123456789" }) what.map {
                    when (it) { '-' -> '⁻'; '+' -> '⁺'; 'n' -> 'ⁿ'; 'x' -> 'ˣ'; else -> superscript[it - '0'] }
                }.joinToString("") else "(${what})"
            }.replace(Regex("√\\{([^{}]+)\\}"), "√($1)").replace("{", "").replace("}", "").replace("-", "−").trim()
    }

    fun fraction(value: String): Triple<String, String, String>? {
        val match = frac.find(value) ?: return null
        fun group(start: Int): Pair<String, Int>? {
            val opening = (start until value.length).firstOrNull { !value[it].isWhitespace() } ?: return null
            if (value[opening] != '{') return null
            var depth = 0
            for (end in opening until value.length) {
                if (value[end] == '{') depth++
                if (value[end] == '}' && --depth == 0) return value.substring(opening + 1, end) to end + 1
            }
            return null
        }
        val numerator = group(match.range.last + 1) ?: return null
        val denominator = group(numerator.second) ?: return null
        if (value.substring(denominator.second).isNotBlank()) return null
        return Triple(value.substring(0, match.range.first), numerator.first, denominator.first)
    }
}
