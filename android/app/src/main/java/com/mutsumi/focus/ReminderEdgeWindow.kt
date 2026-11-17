package com.mutsumi.focus

import android.animation.ValueAnimator
import android.content.Context
import android.content.res.Configuration
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.VelocityTracker
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowInsets
import android.view.WindowManager
import android.view.animation.DecelerateInterpolator
import android.widget.FrameLayout
import android.widget.ScrollView
import kotlin.math.abs
import kotlin.math.roundToInt

/** Separate, tightly bounded windows: no invisible full-screen touch interceptor. */
internal class ReminderEdgeWindow(private val context: Context, private val onMuted: () -> Unit) {
    private val prefs = PopupReminderStore(context)
    private var gesture: Sheet? = null
    private var phase: String? = null
    private var styleKey = ""
    private var mayShowHandle = false
    private var duration = 0
    private var question: ReminderQuestion? = null
    private var wrong = false

    fun update(key: String?, show: Boolean, accent: Int) {
        if (key == null || phase != key) dismiss()
        phase = key
        mayShowHandle = show
        if (key == null || (!show && gesture?.engaged != true)) { dismiss(); return }
        val specific = if (Settings.canDrawOverlays(context)) context else FocusAccessibilityService.connectedContext()
        if (specific == null) { dismiss(); return }
        val type = if (specific === context) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
        val config = context.resources.configuration
        val horizontal = config.orientation == Configuration.ORIENTATION_LANDSCAPE
        val layout = "$type:$horizontal:$accent:${config.screenWidthDp}:${config.screenHeightDp}:${config.fontScale}"
        if (layout == styleKey && gesture != null) return
        val reopen = gesture?.engaged == true
        gesture?.remove()
        val windowContext = if (type == WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY && Build.VERSION.SDK_INT >= 30)
            runCatching { specific.createWindowContext(type, null) }.getOrDefault(specific) else specific
        gesture = Sheet(ReminderUi(windowContext, accent), type, horizontal).takeIf { it.attach(reopen) }
        styleKey = layout
    }

    private fun nextQuestion() = ReminderQuestions.next(ReminderQuestions.decode(prefs.bankJson), question)

    fun dismiss() {
        gesture?.remove(); gesture = null; styleKey = ""; phase = null
        duration = 0; question = null; wrong = false
    }

    private inner class Sheet(private val ui: ReminderUi, private val type: Int, private val horizontal: Boolean) {
        private val wm = ui.context.getSystemService(WindowManager::class.java)
        private val config = ui.context.resources.configuration
        private val viewConfig = ViewConfiguration.get(ui.context)
        private val alignment = if (horizontal) Gravity.TOP or Gravity.CENTER_HORIZONTAL else Gravity.RIGHT or Gravity.CENTER_VERTICAL
        private val gap = ui.dp(9)
        private val handSize = ui.dp(40)
        private val backStrip = if (!horizontal && Build.VERSION.SDK_INT >= 30) runCatching {
            wm.currentWindowMetrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemGestures()).right
        }.getOrDefault(0) else 0
        private val handleInset = maxOf(ui.dp(20), backStrip + ui.dp(10) - gap - ui.dp(9))
        private val cardWidth = (ui.dp(config.screenWidthDp) - ui.dp(if (horizontal) 44 else 54))
            .coerceIn(ui.dp(160), ui.dp(if (horizontal) 550 else 330))
        private val maxHeight = (ui.dp(config.screenHeightDp) - ui.dp(if (horizontal) 80 else 96)).coerceAtLeast(ui.dp(110))
        private var panelHeight = 0
        private var panel: ScrollView? = null
        private val clip = FrameLayout(ui.context).apply { clipChildren = true }
        private val panelParams = params(1, 1, "Focus reminder choices")
        private val handleParams = params(if (horizontal) ui.dp(132) else handSize,
            if (horizontal) handSize else ui.dp(132), "Focus reminder edge")
        private var sheetAttached = false
        private var handleAttached = false
        private var shown = 0f
        private var lastExtent = -1
        private var animator: ValueAnimator? = null
        private var tracking = false
        private var opening = false
        val engaged: Boolean get() = tracking || opening || shown > 0f
        private val extent: Float get() = (if (horizontal) panelHeight else cardWidth).toFloat()
        private val handle = Handle()

        fun attach(reopen: Boolean): Boolean {
            populate()
            return runCatching {
                wm.addView(handle, handleParams)
                handleAttached = true
                if (reopen) {
                    opening = true
                    handle.contentDescription = "收起专注提醒卡"
                    position(extent)
                } else position(0f)
                true
            }.getOrDefault(false)
        }

        private fun populate() {
            val existing = panel
            val content = ui.vertical().apply {
                setPadding(ui.dp(12), ui.dp(10), ui.dp(12), ui.dp(10))
                val selected = question
                if (selected == null) {
                    ui.add(this, ui.tag("专注提醒"))
                    ui.add(this, ui.label("关闭所有提醒", 17f, bold = true), 2)
                    ui.add(this, ui.label("选时长，答对一题后生效。", 12f, ui.muted), 2)
                    ui.add(this, ui.durations(prefs.muteOptions, compact = true) { minutes ->
                        duration = minutes; wrong = false; question = nextQuestion()
                        replacePanel()
                    }, 7)
                } else {
                    ui.add(this, ui.tag("静默 $duration 分钟"))
                    ui.add(this, ui.label("答对一题，暂停提醒", 16f, bold = true), 2)
                    ui.quiz(this, selected, wrong, compact = true, wide = horizontal && config.fontScale <= 1.25f) { index ->
                        // Ignore taps from a removed question view while animating/replacing it.
                        if (question !== selected) return@quiz
                        if (index != selected.answer) {
                            wrong = true; question = nextQuestion(); replacePanel()
                        } else {
                            prefs.mute(duration, System.currentTimeMillis())
                            dismiss(); onMuted()
                        }
                    }
                    ui.add(this, ui.button("更改静默时长", compact = true) {
                        duration = 0; question = null; wrong = false; replacePanel()
                    }, 6)
                }
            }
            val next = ScrollView(ui.context).apply {
                background = ui.surface(Color.WHITE, 8, ui.border)
                clipToOutline = true
                isFillViewport = true
                addView(content)
            }
            next.measure(View.MeasureSpec.makeMeasureSpec(cardWidth, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(maxHeight, View.MeasureSpec.AT_MOST))
            panelHeight = next.measuredHeight.coerceIn(1, maxHeight)
            existing?.let(clip::removeView)
            clip.addView(next, FrameLayout.LayoutParams(cardWidth, panelHeight, if (horizontal) Gravity.BOTTOM else Gravity.LEFT))
            panel = next
            lastExtent = -1
        }

        private fun replacePanel() {
            populate()
            settle(true, 0f)
        }

        private fun params(width: Int, height: Int, title: String) = WindowManager.LayoutParams(width, height, type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT).apply {
            gravity = alignment
            if (horizontal) y = gap else x = gap
            if (Build.VERSION.SDK_INT >= 30) {
                setFitInsetsTypes(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                setFitInsetsIgnoringVisibility(true)
            }
            setTitle(title)
        }

        private fun position(value: Float) {
            if (!handleAttached) return
            shown = value.coerceIn(0f, extent)
            val edge = shown.roundToInt()
            if (lastExtent == edge) return
            lastExtent = edge
            if (horizontal) handleParams.y = gap + edge else {
                // Leave the OS back gesture its own strip; tighten the gap when docked to the card.
                val safeOffset = (handleInset * (1f - shown / extent.coerceAtLeast(1f))).roundToInt()
                handleParams.x = gap + edge + safeOffset
            }
            if (edge > 0) {
                panelParams.width = if (horizontal) cardWidth else edge
                panelParams.height = if (horizontal) edge else panelHeight
                if (!sheetAttached) {
                    if (runCatching { wm.addView(clip, panelParams) }.isSuccess) sheetAttached = true
                } else runCatching { wm.updateViewLayout(clip, panelParams) }
            } else if (sheetAttached) {
                runCatching { wm.removeViewImmediate(clip) }; sheetAttached = false
            }
            runCatching { wm.updateViewLayout(handle, handleParams) }
        }

        private fun settle(open: Boolean, speed: Float) {
            animator?.cancel()
            if (open && !opening && question == null) ReminderBankSync.refresh(context)
            opening = open
            handle.contentDescription = if (open) "收起专注提醒卡" else "拉开专注提醒卡"
            val target = if (open) extent else 0f
            val remaining = abs(shown - target)
            if (remaining < 1f) {
                position(target)
                if (!open && !mayShowHandle) dismiss()
                return
            }
            animator = ValueAnimator.ofFloat(shown, target).apply {
                duration = EdgeSheetMotion.duration(remaining, speed, ui.dp(1).toFloat())
                interpolator = DecelerateInterpolator(1.65f)
                addUpdateListener { frame ->
                    position(frame.animatedValue as Float)
                    if (frame.animatedFraction >= 1f && !opening && !mayShowHandle) dismiss()
                }
                start()
            }
        }

        fun remove() {
            animator?.cancel(); animator = null
            handle.releaseTracker()
            if (handleAttached) runCatching { wm.removeViewImmediate(handle) }
            if (sheetAttached) runCatching { wm.removeViewImmediate(clip) }
            handleAttached = false; sheetAttached = false
        }

        private inner class Handle : View(ui.context) {
            private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            private val bar = RectF()
            private var tracker: VelocityTracker? = null
            private var startAxis = 0f
            private var startCross = 0f
            private var startOffset = 0f
            private var startTime = 0L
            private var drag = false
            private var startedOpen = false
            init {
                setLayerType(LAYER_TYPE_SOFTWARE, null)
                contentDescription = "拉开专注提醒卡"
                isFocusable = true; isClickable = true
            }
            override fun onDraw(canvas: Canvas) {
                val x = if (horizontal) width * .5f else width - ui.dp(9).toFloat()
                val y = if (horizontal) ui.dp(9).toFloat() else height * .5f
                val halfLength = ui.dp(44).toFloat()
                val halfWidth = ui.dp(2).toFloat()
                bar.set(x - if (horizontal) halfLength else halfWidth, y - if (horizontal) halfWidth else halfLength,
                    x + if (horizontal) halfLength else halfWidth, y + if (horizontal) halfWidth else halfLength)
                paint.color = ui.accent
                paint.setShadowLayer(ui.dp(4).toFloat(), 0f, 0f, 0xB8FFFFFF.toInt())
                canvas.drawRoundRect(bar, halfWidth, halfWidth, paint)
                paint.clearShadowLayer()
            }

            private fun axis(event: MotionEvent) = if (horizontal) event.rawY else -event.rawX
            private fun cross(event: MotionEvent) = if (horizontal) event.rawX else event.rawY

            private fun record(event: MotionEvent) {
                val raw = MotionEvent.obtain(event)
                // This window moves along with the finger; local coordinates would cancel the velocity.
                raw.offsetLocation(event.rawX - event.x, event.rawY - event.y)
                tracker?.addMovement(raw)
                raw.recycle()
            }

            override fun onTouchEvent(event: MotionEvent): Boolean {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        animator?.cancel(); tracker?.recycle(); tracker = VelocityTracker.obtain(); record(event)
                        startAxis = axis(event); startCross = cross(event); startOffset = shown
                        startTime = event.eventTime
                        tracking = true; drag = false; startedOpen = opening
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        record(event)
                        val delta = axis(event) - startAxis
                        if (!drag && abs(delta) >= viewConfig.scaledTouchSlop && abs(delta) > abs(cross(event) - startCross)) drag = true
                        if (drag) position(startOffset + delta)
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        record(event); tracker?.computeCurrentVelocity(1000, viewConfig.scaledMaximumFlingVelocity.toFloat())
                        val delta = axis(event) - startAxis
                        if (!drag && abs(delta) >= viewConfig.scaledTouchSlop && abs(delta) > abs(cross(event) - startCross)) drag = true
                        if (drag) position(startOffset + delta)
                        val velocity = if (horizontal) tracker?.yVelocity ?: 0f else -(tracker?.xVelocity ?: 0f)
                        val speed = EdgeSheetMotion.releaseSpeed(velocity, delta, event.eventTime - startTime, ui.dp(1).toFloat())
                        releaseTracker()
                        if (drag) settle(EdgeSheetMotion.opens(shown, extent, speed, startedOpen, ui.dp(1).toFloat()), speed)
                        else if (abs(axis(event) - startAxis) < viewConfig.scaledTouchSlop && abs(cross(event) - startCross) < viewConfig.scaledTouchSlop) performClick()
                        else settle(startedOpen, 0f)
                        return true
                    }
                    MotionEvent.ACTION_CANCEL -> { releaseTracker(); settle(startedOpen, 0f); return true }
                }
                return true
            }

            fun releaseTracker() { tracker?.recycle(); tracker = null; tracking = false }
            override fun performClick(): Boolean { super.performClick(); settle(!opening, 0f); return true }
        }
    }
}

internal object EdgeSheetMotion {
    fun releaseSpeed(tracked: Float, displacement: Float, elapsedMs: Long, density: Float): Float =
        if (elapsedMs in 1..155 && abs(tracked) < 240 * density) displacement * 1000f / elapsedMs else tracked

    fun opens(offset: Float, extent: Float, speed: Float, opened: Boolean, density: Float): Boolean {
        val projected = (offset + (speed * .14f).coerceIn(-extent * .65f, extent * .65f)).coerceIn(0f, extent)
        if (abs(speed) >= 580 * density) return speed > 0
        return projected >= extent * if (opened) .65f else .37f
    }

    fun duration(remaining: Float, speed: Float, density: Float): Long =
        (110 + remaining / (density.coerceAtLeast(1f) * .9f + abs(speed) / 1000f)).toLong().coerceIn(120, 320)
}
