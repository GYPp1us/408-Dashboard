package com.mutsumi.focus

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.content.res.ColorStateList
import android.view.Gravity
import android.view.View
import android.widget.HorizontalScrollView
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
    fun tag(value: String) = label(value, 11f, accentInk, true).apply { letterSpacing = .09f }
    fun button(value: String, primary: Boolean = false, compact: Boolean = false, action: () -> Unit) = Button(context).apply {
        text = value; isAllCaps = false; textSize = if (compact) 13f else 14f; gravity = Gravity.CENTER
        typeface = Typeface.create("serif", Typeface.NORMAL)
        minHeight = dp(44); minimumHeight = dp(44); minimumWidth = 0; minWidth = 0
        stateListAnimator = null; elevation = 0f
        setTextColor(if (primary) IslandPalette(accent).buttonText else ink)
        setPadding(dp(10), dp(7), dp(10), dp(7))
        background = RippleDrawable(ColorStateList.valueOf(0x26000000),
            surface(if (primary) accent else tint, stroke = if (primary) null else border), null)
        setOnClickListener { action() }
    }

    fun durations(options: List<Int>, compact: Boolean = false, onChoose: (Int) -> Unit) = LinearLayout(context).apply {
        for ((index, minutes) in options.withIndex()) {
            addView(button("$minutes 分钟", compact = compact) { onChoose(minutes) }, LinearLayout.LayoutParams(0, -2, 1f).apply {
                if (index > 0) marginStart = dp(6)
            })
        }
    }

    fun quiz(parent: LinearLayout, item: ReminderQuestion, wrong: Boolean, compact: Boolean, wide: Boolean = false,
             onAnswer: (Int) -> Unit) {
        val prompt = vertical()
        val options = vertical()
        if (wrong) add(prompt, label("答错了，换一道。", 12f, 0xffa3342b.toInt()).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }, 3)
        val body = vertical()
        question(body, item.body, compact)
        add(prompt, body, if (wrong) 5 else 0)
        for ((index, option) in item.options.withIndex()) {
            val row = LinearLayout(context).apply {
                gravity = Gravity.CENTER_VERTICAL
                minimumHeight = dp(44)
                setPadding(dp(10), dp(4), dp(9), dp(4))
                background = RippleDrawable(ColorStateList.valueOf(0x26000000), surface(tint, 7, border), null)
                isFocusable = true
                setOnClickListener { onAnswer(index) }
                accessibilityDelegate = object : View.AccessibilityDelegate() {
                    override fun onInitializeAccessibilityNodeInfo(host: View, info: android.view.accessibility.AccessibilityNodeInfo) {
                        super.onInitializeAccessibilityNodeInfo(host, info)
                        info.className = Button::class.java.name
                        info.text = "${'A' + index}   ${optionText(option)}"
                    }
                }
            }
            row.addView(tag(('A' + index).toString()), LinearLayout.LayoutParams(dp(22), -2))
            val value = vertical().apply { importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS }
            question(value, option, true)
            row.addView(value, LinearLayout.LayoutParams(0, -2, 1f))
            (row.getChildAt(0)).importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            add(options, row, if (index == 0) 0 else 5)
        }
        if (wide && item.body.length <= 180 && !item.body.contains("```") && item.options.all { it.length <= 32 && '\n' !in it }) {
            add(parent, LinearLayout(context).apply {
                addView(prompt, LinearLayout.LayoutParams(0, -2, 1.3f))
                addView(options, LinearLayout.LayoutParams(0, -2, 1f).apply { marginStart = dp(14) })
            }, 8)
        } else { add(parent, prompt, 7); add(parent, options, 8) }
    }

    private fun optionText(value: String) = ReminderMath.inline(value).replace('\n', ' ').take(160)

    /** Native markup renderer; question text is never executed or loaded as HTML. */
    private fun question(parent: LinearLayout, body: String, compact: Boolean) {
        val lines = body.lines()
        var i = 0
        var paragraph = false
        while (i < lines.size) {
            val line = lines[i++]
            val kind = line.trim()
            if (kind == "\$\$" || kind.startsWith("```")) {
                val code = kind.startsWith("```")
                val content = mutableListOf<String>()
                while (i < lines.size && (if (code) lines[i].trim() != "```" else lines[i].trim() != "\$\$")) content += lines[i++]
                if (i < lines.size) i++
                if (code) {
                    val pre = label(content.joinToString("\n"), if (compact) 12f else 13f).apply {
                        typeface = Typeface.MONOSPACE; setPadding(dp(9), dp(6), dp(9), dp(6))
                        setHorizontallyScrolling(true)
                    }
                    add(parent, HorizontalScrollView(context).apply {
                        background = surface(tint, 7, border); addView(pre)
                    }, if (parent.childCount == 0) 0 else 6)
                } else add(parent, formula(content.joinToString(" "), compact), if (parent.childCount == 0) 0 else 6)
                paragraph = false
            } else if (line.isNotBlank()) {
                add(parent, label(ReminderMath.inline(line), if (compact) 13f else 15f),
                    if (parent.childCount == 0) 0 else if (paragraph) 7 else 2)
                paragraph = false
            } else paragraph = true
        }
    }

    private fun formula(raw: String, compact: Boolean): View = HorizontalScrollView(context).apply {
        background = surface(tint, 7, border)
        isFillViewport = true
        val centered = android.widget.FrameLayout(context).apply { setPadding(dp(8), dp(5), dp(8), dp(5)) }
        val size = if (compact) 16f else 19f
        val expression = ReminderMath.fraction(raw.trim())
        val formula = if (expression == null) label(ReminderMath.symbols(raw), size).apply { setHorizontallyScrolling(true) }
        else LinearLayout(context).apply {
            val (prefix, numerator, denominator) = expression
            gravity = Gravity.CENTER_VERTICAL
            if (prefix.isNotBlank()) addView(label(ReminderMath.symbols(prefix), size).apply { setPadding(0, 0, dp(5), 0) })
            fun term(value: String) = label(ReminderMath.symbols(value), size).apply {
                gravity = Gravity.CENTER
                setPadding(dp(4), 0, dp(4), 0)
                measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
            }
            val top = term(numerator)
            val bottom = term(denominator)
            val stack = vertical().apply {
                add(this, top)
                addView(View(context).apply { setBackgroundColor(ink) }, LinearLayout.LayoutParams(-1, dp(1)))
                add(this, bottom)
            }
            addView(stack, LinearLayout.LayoutParams(maxOf(top.measuredWidth, bottom.measuredWidth), -2))
        }
        centered.addView(formula, android.widget.FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))
        addView(centered, android.widget.FrameLayout.LayoutParams(-2, -2))
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
