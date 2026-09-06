package com.mutsumi.focus

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

class ReminderOverlayView(
    context: Context,
    kind: ReminderKind,
    onContinueSlacking: () -> Unit,
    onOpenTimer: () -> Unit,
) : FrameLayout(context) {
    init {
        isClickable = true
        isFocusable = true
        setBackgroundColor(Color.argb(185, 24, 18, 17))
        setOnClickListener { onOpenTimer() }

        val minutes = when (kind) {
            ReminderKind.PAUSED -> 5
            ReminderKind.ENDED_15 -> 15
            ReminderKind.ENDED_30 -> 30
            ReminderKind.ENDED_60 -> 60
        }
        val title = if (kind == ReminderKind.PAUSED) "暂停已经 $minutes 分钟" else "离开专注已经 $minutes 分钟"
        val detail = if (kind == ReminderKind.PAUSED) {
            "计时器仍在暂停。点遮罩任意位置回到应用继续专注。"
        } else {
            "今天的节奏正在溜走。点遮罩任意位置回到计时器。"
        }

        val card = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(26), dp(28), dp(26), dp(24))
            background = rounded(Color.argb(240, 244, 238, 231), 24f)
            isClickable = false
        }
        card.addView(TextView(context).apply {
            text = "FOCUS INTERRUPTED"
            textSize = 12f
            letterSpacing = .16f
            setTextColor(Color.rgb(185, 74, 67))
            gravity = Gravity.CENTER
        }, LinearLayout.LayoutParams(-1, -2))
        card.addView(TextView(context).apply {
            text = title
            textSize = 27f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.rgb(34, 28, 26))
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(10))
        }, LinearLayout.LayoutParams(-1, -2))
        card.addView(TextView(context).apply {
            text = detail
            textSize = 16f
            setTextColor(Color.rgb(79, 67, 61))
            gravity = Gravity.CENTER
        }, LinearLayout.LayoutParams(-1, -2))
        card.addView(TextView(context).apply {
            text = "继续摸鱼  →"
            textSize = 17f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setTypeface(typeface, Typeface.BOLD)
            background = rounded(Color.rgb(190, 54, 49), 18f)
            setPadding(dp(16), 0, dp(16), 0)
            setOnTouchListener(SwipeListener(this, onContinueSlacking))
        }, LinearLayout.LayoutParams(-1, dp(60)).apply { topMargin = dp(24) })
        card.addView(TextView(context).apply {
            text = "需要向右滑动红色按钮；轻触其他区域会回到应用"
            textSize = 12f
            setTextColor(Color.rgb(112, 96, 88))
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, 0)
        })

        addView(card, LayoutParams(-1, -2, Gravity.CENTER).apply {
            marginStart = dp(24)
            marginEnd = dp(24)
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
