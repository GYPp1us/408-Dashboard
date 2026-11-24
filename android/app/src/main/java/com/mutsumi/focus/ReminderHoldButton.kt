package com.mutsumi.focus

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.ViewConfiguration
import android.view.animation.DecelerateInterpolator
import android.view.animation.OvershootInterpolator
import android.view.animation.PathInterpolator
import android.widget.Button
import androidx.core.view.ViewCompat
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat.AccessibilityActionCompat
import kotlin.math.abs

internal class ReminderHoldButton(
    context: Context,
    fillColor: Int,
    private val inset: Float,
    private val radius: Float,
    private val canConfirm: () -> Boolean,
    private val action: () -> Unit,
) : Button(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = fillColor }
    private val holdCurve = PathInterpolator(.55f, .07f, .35f, 1f)
    private val slop = ViewConfiguration.get(context).scaledTouchSlop
    private var activePointer = MotionEvent.INVALID_POINTER_ID
    private var downX = 0f
    private var downY = 0f
    private var confirmed = false
    private var progress = 0f
    private var fillAnimation: ValueAnimator? = null
    private val finishHold = Runnable {
        if (activePointer != MotionEvent.INVALID_POINTER_ID) performLongClick()
    }
    private val dispatchChoice = Runnable {
        val accepted = confirmed && isAttachedToWindow && isShown && isEnabled && canConfirm()
        reset(animate = false)
        if (accepted) action()
    }

    init {
        isClickable = false
        isLongClickable = true
        isFocusable = true
        ViewCompat.replaceAccessibilityAction(this, AccessibilityActionCompat.ACTION_LONG_CLICK, "确认延迟") { _, _ ->
            performLongClick()
        }
    }

    override fun onDraw(canvas: Canvas) {
        if (progress > 0f) {
            val saved = canvas.save()
            val right = width - inset
            canvas.clipRect(inset, inset, inset + (right - inset) * progress, height - inset)
            canvas.drawRoundRect(inset, inset, right, height - inset, radius, radius, paint)
            canvas.restoreToCount(saved)
        }
        super.onDraw(canvas)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                if (!isEnabled || !canConfirm() || confirmed) return false
                reset(animate = false)
                activePointer = event.getPointerId(0)
                downX = event.x
                downY = event.y
                postDelayed(finishHold, HOLD_MS)
                if (ValueAnimator.areAnimatorsEnabled()) {
                    animate().scaleX(.97f).scaleY(.97f).setDuration(165).setInterpolator(DecelerateInterpolator()).start()
                    animateFill(1f, HOLD_MS, holdCurve)
                } else {
                    progress = .16f
                    invalidate()
                }
            }
            MotionEvent.ACTION_MOVE -> {
                val pointer = event.findPointerIndex(activePointer)
                if (pointer >= 0) {
                    val x = event.getX(pointer)
                    val y = event.getY(pointer)
                    if (x < 0f || y < 0f || x >= width || y >= height ||
                        abs(x - downX) > slop || abs(y - downY) > slop) reset(animate = true)
                }
            }
            MotionEvent.ACTION_UP -> {
                activePointer = MotionEvent.INVALID_POINTER_ID
                if (!confirmed) reset(animate = true)
            }
            MotionEvent.ACTION_CANCEL, MotionEvent.ACTION_POINTER_DOWN -> reset(animate = true)
        }
        return true
    }

    override fun performLongClick(): Boolean {
        if (!isEnabled || !isAttachedToWindow || !isShown || !canConfirm()) {
            reset(animate = false)
            return false
        }
        if (confirmed) return true
        confirmed = true
        removeCallbacks(finishHold)
        fillAnimation?.cancel()
        progress = 1f
        invalidate()
        performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        postDelayed(dispatchChoice, CONFIRM_FEEDBACK_MS)
        return true
    }

    override fun onCancelPendingInputEvents() {
        super.onCancelPendingInputEvents()
        reset(animate = false)
    }

    override fun onDetachedFromWindow() {
        reset(animate = false)
        super.onDetachedFromWindow()
    }

    private fun reset(animate: Boolean) {
        removeCallbacks(finishHold)
        removeCallbacks(dispatchChoice)
        activePointer = MotionEvent.INVALID_POINTER_ID
        confirmed = false
        fillAnimation?.cancel()
        animate().cancel()
        if (animate && ValueAnimator.areAnimatorsEnabled()) {
            animateFill(0f, 135L, DecelerateInterpolator())
            animate().scaleX(1f).scaleY(1f).setDuration(170).setInterpolator(OvershootInterpolator(1.15f)).start()
        } else {
            progress = 0f
            scaleX = 1f
            scaleY = 1f
            invalidate()
        }
    }

    private fun animateFill(to: Float, time: Long, curve: android.animation.TimeInterpolator) {
        fillAnimation = ValueAnimator.ofFloat(progress, to).apply {
            duration = time
            interpolator = curve
            addUpdateListener {
                progress = it.animatedValue as Float
                invalidate()
            }
            start()
        }
    }

    private companion object {
        const val HOLD_MS = 500L
        const val CONFIRM_FEEDBACK_MS = 75L
    }
}
