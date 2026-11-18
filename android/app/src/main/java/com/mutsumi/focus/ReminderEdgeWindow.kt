package com.mutsumi.focus

import android.animation.ValueAnimator
import android.content.Context
import android.content.res.Configuration
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Point
import android.graphics.RectF
import android.hardware.input.InputManager
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.VelocityTracker
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowInsets
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
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
    private var reviewingAnswer = false

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
        val reopen = gesture?.expanded == true
        gesture?.remove()
        val windowContext = if (type == WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY && Build.VERSION.SDK_INT >= 30)
            runCatching { specific.createWindowContext(type, null) }.getOrDefault(specific) else specific
        gesture = Sheet(ReminderUi(windowContext, accent), type, horizontal).takeIf { it.attach(reopen) }
        styleKey = layout
    }

    private fun nextQuestion() = ReminderQuestions.next(ReminderQuestions.decode(prefs.bankJson), question)

    fun dismiss() {
        gesture?.remove(); gesture = null; styleKey = ""; phase = null
        duration = 0; question = null; reviewingAnswer = false
    }

    fun trackDashboardTouch(event: MotionEvent): Boolean = gesture?.trackDashboardTouch(event) == true

    private inner class Sheet(private val ui: ReminderUi, private val type: Int, private val horizontal: Boolean) {
        private val wm = ui.context.getSystemService(WindowManager::class.java)
        private val config = ui.context.resources.configuration
        private val viewConfig = ViewConfiguration.get(ui.context)
        private val alignment = if (horizontal) Gravity.TOP or Gravity.CENTER_HORIZONTAL else Gravity.RIGHT or Gravity.CENTER_VERTICAL
        private val gap = ui.dp(9)
        private val safeInsets = if (Build.VERSION.SDK_INT >= 30)
            WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() else 0
        private val handleLength = ui.dp(104)
        private val stripThickness = ui.dp(16)
        private val railWidth = ui.dp(24)
        private val railGap = ui.dp(3)
        private val backStrip = if (!horizontal && Build.VERSION.SDK_INT >= 30) runCatching {
            wm.currentWindowMetrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemGestures()).right
        }.getOrDefault(0) else 0
        private val handleInset = maxOf(ui.dp(20), backStrip + ui.dp(10) - gap - ui.dp(9))
        private val cardWidth = (ui.dp(config.screenWidthDp) - ui.dp(if (horizontal) 44 else 54))
            .coerceIn(ui.dp(160), ui.dp(if (horizontal) 550 else 330))
        private val maxHeight = (ui.dp(config.screenHeightDp) - ui.dp(if (horizontal) 80 else 96)).coerceAtLeast(ui.dp(110))
        private var panelHeight = 0
        private var panel: View? = null
        private val clip = FrameLayout(ui.context).apply { clipChildren = true }
        private val panelParams = params(1, 1, "Focus reminder choices")
        private val visualParams = params(if (horizontal) handleLength else stripThickness,
            if (horizontal) stripThickness else handleLength, "Focus reminder edge").apply {
            flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            if (type == WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY && Build.VERSION.SDK_INT >= 31) {
                alpha = ui.context.getSystemService(InputManager::class.java).maximumObscuringOpacityForTouch
            }
        }
        private val railParams = params(if (horizontal) handleLength else railWidth,
            if (horizontal) railWidth else handleLength, "Focus reminder drag")
        private var sheetAttached = false
        private var handleAttached = false
        private var railAttached = false
        private var shown = 0f
        private var lastExtent = -1
        private var lastCross = Int.MIN_VALUE
        private val crossSpace = availableCrossLength()
        private val crossLimit = EdgeSheetMotion.crossLimit(crossSpace, handleLength)
        private var crossOffset = (prefs.edgePosition(horizontal).coerceIn(-1f, 1f) * crossLimit).roundToInt()
        private var animator: ValueAnimator? = null
        private var opening = false
        val expanded: Boolean get() = opening || shown > 0f
        val engaged: Boolean get() = handle.drag != null || expanded
        private val extent: Float get() = (if (horizontal) panelHeight else cardWidth).toFloat()
        private val handle = Handle()
        private val rail = object : View(ui.context) {
            override fun onTouchEvent(event: MotionEvent): Boolean {
                handle.touch(event, dashboard = false)
                return true
            }
        }.apply { importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO }

        fun attach(reopen: Boolean): Boolean {
            populate()
            return runCatching {
                opening = reopen
                shown = if (reopen) extent else 0f
                updateHandleParams(shown.roundToInt())
                wm.addView(handle, visualParams)
                handleAttached = true
                wm.addView(rail, railParams)
                railAttached = true
                position(shown)
                true
            }.onFailure { remove() }.getOrDefault(false)
        }

        fun trackDashboardTouch(event: MotionEvent): Boolean = handle.touch(event, dashboard = true)

        @Suppress("DEPRECATION")
        private fun availableCrossLength(): Int {
            if (Build.VERSION.SDK_INT >= 30) {
                val metrics = wm.currentWindowMetrics
                val insets = metrics.windowInsets.getInsetsIgnoringVisibility(safeInsets)
                return if (horizontal) metrics.bounds.width() - insets.left - insets.right
                    else metrics.bounds.height() - insets.top - insets.bottom
            }
            val size = Point()
            wm.defaultDisplay.getSize(size)
            return if (horizontal) size.x else size.y
        }

        private fun populate() {
            val existing = panel
            val selected = question
            val content = ui.vertical().apply {
                setPadding(ui.dp(12), ui.dp(10), ui.dp(12), ui.dp(10))
                if (selected == null) {
                    ui.add(this, ui.tag("专注提醒"))
                    ui.add(this, ui.label("关闭所有提醒", 17f, bold = true), 2)
                    ui.add(this, ui.label("选时长，答对一题后生效。", 12f, ui.muted), 2)
                    ui.add(this, ui.durations(prefs.muteOptions, compact = true) { minutes ->
                        duration = minutes; reviewingAnswer = false; question = nextQuestion()
                        replacePanel()
                    }, 7)
                } else {
                    ui.add(this, ui.tag("静默 $duration 分钟"))
                    if (reviewingAnswer) ui.revealedAnswer(this, selected, compact = true)
                    else {
                        ui.add(this, ui.label("答对一题，暂停提醒", 16f, bold = true), 2)
                        ui.quiz(this, selected, compact = true, wide = horizontal && config.fontScale <= 1.25f) { index ->
                            if (question !== selected || reviewingAnswer) return@quiz
                            if (index != selected.answer) {
                                reviewingAnswer = true; replacePanel()
                            } else {
                                prefs.mute(duration, System.currentTimeMillis())
                                dismiss(); onMuted()
                            }
                        }
                        ui.add(this, ui.button("更改静默时长", compact = true, action = ::changeDuration), 6)
                    }
                }
            }
            val next = if (reviewingAnswer) ui.reviewCard(content, compact = true, onNext = {
                if (reviewingAnswer && question === selected) {
                    question = nextQuestion(); reviewingAnswer = false; replacePanel()
                }
            }, onChangeDuration = ::changeDuration) else ScrollView(ui.context).apply {
                isFillViewport = true
                addView(content)
            }
            next.background = ui.surface(Color.WHITE, 8, ui.border)
            next.clipToOutline = true
            next.measure(View.MeasureSpec.makeMeasureSpec(cardWidth, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(maxHeight, View.MeasureSpec.AT_MOST))
            panelHeight = next.measuredHeight.coerceIn(1, maxHeight)
            existing?.let(clip::removeView)
            clip.addView(next, FrameLayout.LayoutParams(cardWidth, panelHeight, if (horizontal) Gravity.BOTTOM else Gravity.LEFT))
            panel = next
            lastExtent = -1
        }

        private fun changeDuration() {
            duration = 0; question = null; reviewingAnswer = false
            replacePanel()
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
                setFitInsetsTypes(safeInsets)
                setFitInsetsIgnoringVisibility(true)
            }
            setTitle(title)
        }

        private fun position(value: Float) {
            if (!handleAttached) return
            shown = value.coerceIn(0f, extent)
            val edge = shown.roundToInt()
            if (lastExtent == edge && lastCross == crossOffset) return
            lastExtent = edge
            lastCross = crossOffset
            updateHandleParams(edge)
            val panelCrossLimit = EdgeSheetMotion.crossLimit(crossSpace, if (horizontal) cardWidth else panelHeight)
            val panelCross = crossOffset.coerceIn(-panelCrossLimit, panelCrossLimit)
            if (horizontal) panelParams.x = panelCross else panelParams.y = panelCross
            if (edge > 0) {
                panelParams.width = if (horizontal) cardWidth else edge
                panelParams.height = if (horizontal) edge else panelHeight
                if (!sheetAttached) {
                    if (runCatching { wm.addView(clip, panelParams) }.isSuccess) sheetAttached = true
                } else runCatching { wm.updateViewLayout(clip, panelParams) }
            } else if (sheetAttached) {
                runCatching { wm.removeViewImmediate(clip) }; sheetAttached = false
            }
            runCatching { wm.updateViewLayout(handle, visualParams) }
            if (railAttached) runCatching { wm.updateViewLayout(rail, railParams) }
        }

        private fun updateHandleParams(edge: Int) {
            // Keep room for the OS back gesture. The drag rail starts on the inward side of the painted strip.
            val safeOffset = (handleInset * (1f - shown / extent.coerceAtLeast(1f))).roundToInt()
            val center = gap + edge + ui.dp(9) + if (horizontal) 0 else safeOffset
            val visualOffset = center - stripThickness / 2
            val railOffset = center + railGap
            if (horizontal) {
                visualParams.x = crossOffset; visualParams.y = visualOffset
                railParams.x = crossOffset; railParams.y = railOffset
            } else {
                visualParams.x = visualOffset; visualParams.y = crossOffset
                railParams.x = railOffset; railParams.y = crossOffset
            }
        }

        private fun settle(open: Boolean, speed: Float) {
            animator?.cancel()
            if (open && !opening && question == null) ReminderBankSync.refresh(context)
            opening = open
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
            if (railAttached) runCatching { wm.removeViewImmediate(rail) }
            if (sheetAttached) runCatching { wm.removeViewImmediate(clip) }
            handleAttached = false; railAttached = false; sheetAttached = false
        }

        private inner class Handle : View(ui.context) {
            private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            private val bar = RectF()
            private val screenLocation = IntArray(2)
            private var tracker: VelocityTracker? = null
            private var startAxis = 0f
            private var startCross = 0f
            private var startOffset = 0f
            private var startCrossOffset = 0
            private var startTime = 0L
            private var fromDashboard = false
            private var startedOpen = false
            var drag: EdgeDrag? = null
                private set
            init {
                setLayerType(LAYER_TYPE_SOFTWARE, null)
                contentDescription = "专注提醒色带"
                importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
            }
            override fun onDraw(canvas: Canvas) {
                val x = width * .5f
                val y = height * .5f
                val halfLength = ui.dp(44).toFloat()
                val halfWidth = ui.dp(2).toFloat()
                bar.set(x - if (horizontal) halfLength else halfWidth, y - if (horizontal) halfWidth else halfLength,
                    x + if (horizontal) halfLength else halfWidth, y + if (horizontal) halfWidth else halfLength)
                paint.color = ui.accent
                paint.setShadowLayer(ui.dp(4).toFloat(), 0f, 0f, 0xB8FFFFFF.toInt())
                canvas.drawRoundRect(bar, halfWidth, halfWidth, paint)
                paint.clearShadowLayer()
            }

            override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
                super.onInitializeAccessibilityNodeInfo(info)
                val action = if (opening) AccessibilityNodeInfo.AccessibilityAction.ACTION_COLLAPSE
                    else AccessibilityNodeInfo.AccessibilityAction.ACTION_EXPAND
                info.addAction(action)
            }

            override fun performAccessibilityAction(action: Int, args: android.os.Bundle?): Boolean {
                if (action == AccessibilityNodeInfo.AccessibilityAction.ACTION_EXPAND.id && !opening ||
                    action == AccessibilityNodeInfo.AccessibilityAction.ACTION_COLLAPSE.id && opening) {
                    settle(!opening, 0f)
                    return true
                }
                return super.performAccessibilityAction(action, args)
            }

            private fun contains(event: MotionEvent): Boolean {
                if (!isLaidOut) return false
                getLocationOnScreen(screenLocation)
                val x = event.rawX - screenLocation[0]
                val y = event.rawY - screenLocation[1]
                return x >= 0 && x < width && y >= 0 && y < height
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

            fun touch(event: MotionEvent, dashboard: Boolean): Boolean {
                if (event.actionMasked != MotionEvent.ACTION_DOWN && (tracker == null || dashboard != fromDashboard)) return false
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        if (dashboard && !contains(event)) return false
                        releaseTracker()
                        fromDashboard = dashboard
                        tracker = VelocityTracker.obtain()
                        record(event)
                        startAxis = axis(event)
                        startCross = cross(event)
                        startCrossOffset = crossOffset
                        startTime = event.eventTime
                        return false
                    }
                    MotionEvent.ACTION_MOVE, MotionEvent.ACTION_UP -> {
                        record(event)
                        val pullDelta = axis(event) - startAxis
                        val crossDelta = cross(event) - startCross
                        if (drag == null) {
                            drag = EdgeSheetMotion.drag(pullDelta, crossDelta, viewConfig.scaledTouchSlop)
                            if (drag != null) {
                                animator?.cancel()
                                startOffset = shown
                                startedOpen = opening
                            }
                        }
                        when (drag) {
                            EdgeDrag.PULL -> position(startOffset + pullDelta)
                            EdgeDrag.REPOSITION -> {
                                crossOffset = (startCrossOffset + crossDelta.roundToInt()).coerceIn(-crossLimit, crossLimit)
                                position(shown)
                            }
                            null -> Unit
                        }
                        val claimed = drag != null
                        if (event.actionMasked == MotionEvent.ACTION_UP) finish(event, pullDelta)
                        return claimed
                    }
                    MotionEvent.ACTION_CANCEL, MotionEvent.ACTION_POINTER_DOWN -> {
                        val currentDrag = drag
                        releaseTracker()
                        if (currentDrag != null) {
                            if (currentDrag == EdgeDrag.REPOSITION) {
                                crossOffset = startCrossOffset
                                position(shown)
                            }
                            settle(startedOpen, 0f)
                        }
                        return currentDrag != null
                    }
                }
                return drag != null
            }

            private fun finish(event: MotionEvent, pullDelta: Float) {
                val currentDrag = drag
                val density = ui.context.resources.displayMetrics.density
                var speed = 0f
                if (currentDrag == EdgeDrag.PULL) {
                    tracker?.computeCurrentVelocity(1000, viewConfig.scaledMaximumFlingVelocity.toFloat())
                    val velocity = if (horizontal) tracker?.yVelocity ?: 0f else -(tracker?.xVelocity ?: 0f)
                    speed = EdgeSheetMotion.releaseSpeed(velocity, pullDelta, event.eventTime - startTime, density)
                }
                releaseTracker()
                when (currentDrag) {
                    EdgeDrag.PULL -> settle(EdgeSheetMotion.opens(shown, extent, speed, startedOpen, density), speed)
                    EdgeDrag.REPOSITION -> {
                        if (crossLimit > 0) prefs.saveEdgePosition(horizontal, crossOffset.toFloat() / crossLimit)
                        settle(startedOpen, 0f)
                    }
                    null -> Unit
                }
            }

            fun releaseTracker() { tracker?.recycle(); tracker = null; drag = null }
        }
    }
}

internal enum class EdgeDrag { PULL, REPOSITION }

internal object EdgeSheetMotion {
    fun drag(pull: Float, cross: Float, slop: Int): EdgeDrag? {
        if (maxOf(abs(pull), abs(cross)) < slop) return null
        return if (abs(pull) >= abs(cross)) EdgeDrag.PULL else EdgeDrag.REPOSITION
    }

    fun crossLimit(available: Int, size: Int): Int = ((available - size) / 2).coerceAtLeast(0)

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
