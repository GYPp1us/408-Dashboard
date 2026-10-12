package com.mutsumi.focus

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.FrameLayout
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class ReminderOverlayView(
    context: Context,
    kind: ReminderKind,
    onContinueSlacking: () -> Unit,
    onOpenTimer: () -> Unit,
    onResume: () -> Unit,
    onClose: () -> Unit,
) : FrameLayout(context) {
    init {
        val style = SetupStyle(context)
        isClickable = true
        isFocusable = true
        setBackgroundColor(Color.argb(108, 24, 18, 17))

        val minutes = when (kind) {
            ReminderKind.PAUSED -> 5
            ReminderKind.ENDED_15 -> 15
            ReminderKind.ENDED_30 -> 30
            ReminderKind.ENDED_60 -> 60
        }
        val title = FocusPresentation.reminderTitle(kind)
        val detail = if (kind == ReminderKind.PAUSED) {
            "计时仍在暂停。准备好时继续，也可以再等 5 分钟。"
        } else {
            "休息一下也没关系。准备好时回到应用，选择下一段事项。"
        }

        val card = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(18), dp(18), dp(18), dp(16))
            background = style.rounded()
            isClickable = false
        }
        card.addView(TextView(context).apply {
            text = "M · 专注提醒"
            textSize = 12f
            letterSpacing = .16f
            setTextColor(style.accent)
            gravity = Gravity.CENTER
        }, LinearLayout.LayoutParams(-1, -2))
        card.addView(TextView(context).apply {
            text = title
            textSize = 21f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(style.ink)
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(10))
        }, LinearLayout.LayoutParams(-1, -2))
        card.addView(TextView(context).apply {
            text = detail
            textSize = 13f
            setTextColor(style.muted)
            gravity = Gravity.CENTER
        }, LinearLayout.LayoutParams(-1, -2))
        if (kind == ReminderKind.PAUSED) card.addView(TextView(context).apply {
            text = "继续专注"
            textSize = 12f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            background = rounded(style.accent, 7f)
            setOnClickListener { onResume() }
        }, LinearLayout.LayoutParams(-1, dp(34)).apply { topMargin = dp(12) })
        card.addView(TextView(context).apply {
            text = "再等 5 分钟  →"
            textSize = 12f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setTypeface(typeface, Typeface.BOLD)
            background = rounded(Color.argb(180, 86, 75, 69), 7f)
            setPadding(dp(16), 0, dp(16), 0)
            setOnTouchListener(SwipeListener(this, onContinueSlacking))
        }, LinearLayout.LayoutParams(-1, dp(34)).apply { topMargin = dp(12) })
        card.addView(Button(context).apply {
            text = "关闭提醒"
            style.button(this)
            setOnClickListener { onClose() }
        }, LinearLayout.LayoutParams(-1, dp(34)).apply { topMargin = dp(12) })
        card.addView(TextView(context).apply {
            text = "查看提醒 · 返回应用"
            textSize = 13f
            setTextColor(Color.rgb(112, 96, 88))
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, 0)
            minHeight = dp(34)
            setOnClickListener { onOpenTimer() }
        })

        addView(android.widget.ScrollView(context).apply { addView(card) },
            LayoutParams(minOf(resources.displayMetrics.widthPixels - dp(48), dp(520)), -2, Gravity.CENTER).apply {
                topMargin = dp(12); bottomMargin = dp(24)
            })
    }

    private inner class SwipeListener(
        private val target: View,
        private val completed: () -> Unit,
    ) : OnTouchListener {
        private var downX = 0f
        private var progress = 0f

        override fun onTouch(view: View, event: MotionEvent): Boolean {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX
                    progress = 0f
                    target.parent.requestDisallowInterceptTouchEvent(true)
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    progress = ((event.rawX - downX) / maxOf(1f, target.width * .62f)).coerceIn(0f, 1f)
                    target.translationX = progress * dp(24)
                    target.alpha = .82f + progress * .18f
                    return true
                }
                MotionEvent.ACTION_UP -> {
                    target.parent.requestDisallowInterceptTouchEvent(false)
                    if (progress >= .86f) completed() else target.animate().translationX(0f).alpha(1f).setDuration(160).start()
                    return true
                }
                MotionEvent.ACTION_CANCEL -> {
                    target.parent.requestDisallowInterceptTouchEvent(false)
                    target.animate().translationX(0f).alpha(1f).setDuration(160).start()
                    return true
                }
            }
            return false
        }
    }

    private fun rounded(color: Int, radiusDp: Float) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = radiusDp * resources.displayMetrics.density
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
