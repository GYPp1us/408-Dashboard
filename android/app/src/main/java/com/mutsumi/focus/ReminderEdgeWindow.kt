package com.mutsumi.focus

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
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
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.HapticFeedbackConstants
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

internal class ReminderEdgeWindow(private val context: Context, private val onChanged: () -> Unit) {
    private val prefs = PopupReminderStore(context)
    private var sheet: Sheet? = null
    private var phase: String? = null
    private var styleKey = ""
    private var color = PopupReminderPolicy.WAITING_COLOR
    private var dashboardVisible = false
    private var duration = 0
    private var question: ReminderQuestion? = null
    private var reviewing = false

    fun update(key: String?, signalColor: Int, accent: Int, appVisible: Boolean) {
        if (key == null || phase != key) dismiss()
        phase = key
        if (key == null) return
        color = signalColor
        dashboardVisible = appVisible
        val specific = if (Settings.canDrawOverlays(context)) context else FocusAccessibilityService.connectedContext()
        if (specific == null) { dismiss(); return }
        val type = if (specific === context) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
        val config = context.resources.configuration
        val horizontal = config.orientation == Configuration.ORIENTATION_LANDSCAPE
        val layout = "$type:$horizontal:$accent:${config.screenWidthDp}:${config.screenHeightDp}:${config.fontScale}"
        if (layout == styleKey && sheet != null) {
            if (!appVisible) sheet?.releaseDashboardTouch()
            sheet?.feedback()
            return
        }
        val reopen = sheet?.opened == true
        sheet?.remove()
        val windowContext = if (type == WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY && Build.VERSION.SDK_INT >= 30)
            runCatching { specific.createWindowContext(type, null) }.getOrDefault(specific) else specific
        sheet = Sheet(ReminderUi(windowContext, accent), type, horizontal).takeIf { it.attach(reopen) }
        styleKey = layout
    }

    private fun nextQuestion() = ReminderQuestions.next(ReminderQuestions.decode(prefs.bankJson), question)
    fun dismiss() {
        sheet?.remove(); sheet = null; phase = null; styleKey = ""
        duration = 0; question = null; reviewing = false
    }
    fun trackDashboardTouch(event: MotionEvent, claim: (MotionEvent) -> Unit) { sheet?.dashboardTouch(event, claim) }

    private inner class Sheet(private val ui: ReminderUi, private val type: Int, private val horizontal: Boolean) {
        private val wm = ui.context.getSystemService(WindowManager::class.java)
        private val config = ui.context.resources.configuration
        private val density = ui.context.resources.displayMetrics.density
        private val grip = ui.dp(56)
        private val handleLength = ui.dp(168)
        private val gap = ui.dp(8)
        private val thickness = ui.dp(16)
        private val cardWidth = (ui.dp(config.screenWidthDp) - grip - gap * 2).coerceIn(ui.dp(150), ui.dp(if (horizontal) 550 else 330))
        private val maxHeight = (ui.dp(config.screenHeightDp) - ui.dp(44) - if (horizontal) grip else 0).coerceAtLeast(ui.dp(100))
        private var panelHeight = 1
        private var shown = 0f
        private var animator: ValueAnimator? = null
        private var animating = false
        var opened = false
            private set
        private val extent get() = (if (horizontal) panelHeight else cardWidth).toFloat()
        private val crossSpace = crossSpace()
        private val crossLimit = EdgeSheetMotion.crossLimit(crossSpace, handleLength)
        private var crossOffset = (prefs.edgePosition(horizontal).coerceIn(-1f, 1f) * crossLimit).roundToInt()
        private var sheetAttached = false
        private var collapsedAttached = false
        private val gesture = Gesture()
        private val folded = Bar()
        private val openBar = Bar().apply {
            setOnTouchListener { _, event -> gesture.touch(event, 1, allowMove = true); true }
        }
        private val moving = FrameLayout(ui.context)
        private val viewport = object : FrameLayout(ui.context) {
            override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
                if (event.actionMasked == MotionEvent.ACTION_DOWN) {
                    val point = IntArray(2); openBar.getLocationOnScreen(point)
                    if (event.rawX >= point[0] && event.rawX < point[0] + openBar.width &&
                        event.rawY >= point[1] && event.rawY < point[1] + openBar.height) return false
                    // Buttons and vertical scrolling keep taps until an outward pull claims this gesture.
                    gesture.touch(event, 2, allowMove = false)
                    return false
                }
                return gesture.touch(event, 2, allowMove = false)
            }
            override fun onTouchEvent(event: MotionEvent): Boolean {
                gesture.touch(event, 2, allowMove = false)
                return true
            }
        }.apply { clipChildren = true; addView(moving) }
        private val panelParams = params(1, 1, "Focus reminder choices")
        private val visualParams = params(if (horizontal) handleLength else thickness,
            if (horizontal) thickness else handleLength, "Focus reminder edge").apply {
            flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            if (type == WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY && Build.VERSION.SDK_INT >= 31)
                alpha = ui.context.getSystemService(InputManager::class.java).maximumObscuringOpacityForTouch
        }

        @Suppress("DEPRECATION")
        private fun crossSpace(): Int {
            if (Build.VERSION.SDK_INT >= 30) {
                val metrics = wm.currentWindowMetrics
                val insets = metrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                return if (horizontal) metrics.bounds.width() - insets.left - insets.right else metrics.bounds.height() - insets.top - insets.bottom
            }
            val size = Point(); wm.defaultDisplay.getSize(size)
            return if (horizontal) size.x else size.y
        }

        private fun params(width: Int, height: Int, title: String) = WindowManager.LayoutParams(width, height, type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT).apply {
            gravity = if (horizontal) Gravity.TOP or Gravity.CENTER_HORIZONTAL else Gravity.RIGHT or Gravity.CENTER_VERTICAL
            if (horizontal) y = gap else x = gap
            if (Build.VERSION.SDK_INT >= 30) {
                setFitInsetsTypes(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                setFitInsetsIgnoringVisibility(true)
            }
            setTitle(title)
        }

        fun attach(reopen: Boolean): Boolean = runCatching {
            populate()
            updateCross()
            wm.addView(folded, visualParams); collapsedAttached = true
            opened = reopen
            position(if (reopen) extent else 0f)
            true
        }.onFailure { remove() }.getOrDefault(false)

        private fun choose(minutes: Int, extraMinute: Boolean = false) {
            if (prefs.delayWithoutQuestion(minutes, System.currentTimeMillis(), extraMinute)) {
                duration = 0; question = null; reviewing = false
                populate(); settle(false, 0f); onChanged()
                return
            }
            if (extraMinute || minutes !in prefs.muteOptions) return
            duration = minutes; reviewing = false; question = nextQuestion(); populate(); position(extent)
        }
        private fun changeDuration() {
            duration = 0; question = null; reviewing = false; populate(); position(extent)
        }
        private fun populate() {
            val selected = question
            val body = ui.vertical().apply {
                setPadding(ui.dp(12), ui.dp(10), ui.dp(12), ui.dp(10))
                ui.add(this, ui.tag(if (selected == null) "专注提醒" else "延迟 $duration 分钟"))
                if (selected == null) {
                    ui.add(this, ui.label("稍后提醒", 17f, bold = true), 2)
                    ui.delayChoices(this, prefs, compact = true, onChoose = { choose(it) }, onExtraMinute = { choose(1, true) })
                } else if (reviewing) ui.revealedAnswer(this, selected, compact = true)
                else {
                    ui.add(this, ui.label("答对一题，延迟提醒", 16f, bold = true), 2)
                    ui.quiz(this, selected, compact = true, wide = horizontal && config.fontScale <= 1.25f) { index ->
                        if (question !== selected || reviewing) return@quiz
                        if (index != selected.answer) { reviewing = true; populate(); position(extent) }
                        else {
                            prefs.mute(duration, System.currentTimeMillis())
                            duration = 0; question = null; reviewing = false
                            populate(); settle(false, 0f); onChanged()
                        }
                    }
                    ui.add(this, ui.button("更改延迟时长", compact = true, action = ::changeDuration), 6)
                }
            }
            val panel = if (reviewing) ui.reviewCard(body, compact = true, onNext = {
                if (reviewing && question === selected) {
                    question = nextQuestion(); reviewing = false; populate(); position(extent)
                }
            }, onChangeDuration = ::changeDuration) else ScrollView(ui.context).apply { isFillViewport = true; addView(body) }
            panel.background = ui.surface(Color.WHITE, 8, ui.border); panel.clipToOutline = true
            panel.measure(View.MeasureSpec.makeMeasureSpec(cardWidth, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(maxHeight, View.MeasureSpec.AT_MOST))
            panelHeight = panel.measuredHeight.coerceAtLeast(1)
            moving.removeAllViews()
            val totalWidth = cardWidth + if (horizontal) 0 else grip
            val totalHeight = panelHeight + if (horizontal) grip else 0
            viewport.getChildAt(0).layoutParams = FrameLayout.LayoutParams(totalWidth, totalHeight)
            moving.addView(panel, FrameLayout.LayoutParams(cardWidth, panelHeight).apply { if (!horizontal) leftMargin = grip })
            moving.addView(openBar, FrameLayout.LayoutParams(if (horizontal) minOf(cardWidth, handleLength) else grip,
                if (horizontal) grip else minOf(panelHeight, handleLength),
                if (horizontal) Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL else Gravity.LEFT or Gravity.CENTER_VERTICAL))
            panelParams.width = totalWidth; panelParams.height = totalHeight
            updateCross()
        }

        private fun updateCross() {
            val limit = EdgeSheetMotion.crossLimit(crossSpace, if (horizontal) cardWidth else panelHeight)
            if (horizontal) {
                panelParams.x = crossOffset.coerceIn(-limit, limit)
                visualParams.x = crossOffset; visualParams.y = gap + grip / 2 - thickness / 2
            } else {
                panelParams.y = crossOffset.coerceIn(-limit, limit)
                visualParams.y = crossOffset; visualParams.x = gap + grip / 2 - thickness / 2
            }
            if (collapsedAttached) runCatching { wm.updateViewLayout(folded, visualParams) }
            if (sheetAttached) runCatching { wm.updateViewLayout(viewport, panelParams) }
        }

        /** A stable window and hardware view translations keep layout and input coordinates out of the drag loop. */
        private fun position(value: Float) {
            shown = value.coerceIn(0f, extent)
            if (shown > 0f && !sheetAttached) {
                sheetAttached = runCatching { wm.addView(viewport, panelParams) }.isSuccess
            }
            if (horizontal) moving.translationY = shown - extent else moving.translationX = extent - shown
            folded.visibility = if (shown > 0f) View.INVISIBLE else View.VISIBLE
            if (shown <= 0f && sheetAttached) { runCatching { wm.removeViewImmediate(viewport) }; sheetAttached = false }
            feedback()
        }

        private fun settle(open: Boolean, speed: Float) {
            animator?.cancel()
            opened = open
            if (open && question == null) ReminderBankSync.refresh(context)
            val target = if (open) extent else 0f
            if (abs(shown - target) < 1f) { position(target); return }
            animator = ValueAnimator.ofFloat(shown, target).apply {
                duration = EdgeSheetMotion.duration(abs(shown - target), speed, density)
                interpolator = DecelerateInterpolator(1.4f)
                addUpdateListener { position(it.animatedValue as Float) }
                addListener(object : AnimatorListenerAdapter() {
                    override fun onAnimationStart(animation: Animator) { animating = true; feedback() }
                    override fun onAnimationEnd(animation: Animator) { animating = false; feedback() }
                })
                start()
            }
        }

        fun dashboardTouch(event: MotionEvent, claim: (MotionEvent) -> Unit) {
            if (dashboardVisible) gesture.touch(event, 0, allowMove = true, claim = claim)
        }
        fun releaseDashboardTouch() { if (gesture.fromDashboard) gesture.cancel() }
        fun feedback() {
            folded.invalidate(); openBar.invalidate()
        }
        fun remove() {
            animator?.cancel(); gesture.release()
            if (sheetAttached) runCatching { wm.removeViewImmediate(viewport) }
            if (collapsedAttached) runCatching { wm.removeViewImmediate(folded) }
            sheetAttached = false; collapsedAttached = false
        }

        private inner class Bar : View(ui.context) {
            private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            private val rect = RectF()
            init { importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES; contentDescription = "专注提醒，拖动展开或收起" }
            override fun onDraw(canvas: Canvas) {
                val engaged = gesture.activated || animating
                val halfWidth = ui.dp(if (engaged) 3 else 2).toFloat()
                val length = minOf(ui.dp(if (engaged) 100 else 88), (if (horizontal) width else height) - ui.dp(16)).toFloat() / 2
                val cx = width / 2f; val cy = height / 2f
                if (engaged) {
                    paint.color = Color.argb(30, Color.red(color), Color.green(color), Color.blue(color))
                    val halfTouch = ui.dp(12).toFloat()
                    rect.set(cx - if (horizontal) length + ui.dp(6) else halfTouch, cy - if (horizontal) halfTouch else length + ui.dp(6),
                        cx + if (horizontal) length + ui.dp(6) else halfTouch, cy + if (horizontal) halfTouch else length + ui.dp(6))
                    canvas.drawRoundRect(rect, ui.dp(6).toFloat(), ui.dp(6).toFloat(), paint)
                }
                val halo = halfWidth + ui.dp(2)
                rect.set(cx - if (horizontal) length + ui.dp(2) else halo, cy - if (horizontal) halo else length + ui.dp(2),
                    cx + if (horizontal) length + ui.dp(2) else halo, cy + if (horizontal) halo else length + ui.dp(2))
                paint.color = Color.argb(95, 255, 255, 255)
                canvas.drawRoundRect(rect, halo, halo, paint)
                rect.set(cx - if (horizontal) length else halfWidth, cy - if (horizontal) halfWidth else length,
                    cx + if (horizontal) length else halfWidth, cy + if (horizontal) halfWidth else length)
                paint.color = color; paint.alpha = if (engaged || opened) 255 else 205
                canvas.drawRoundRect(rect, halfWidth, halfWidth, paint)
                contentDescription = when {
                    gesture.drag == EdgeDrag.REPOSITION -> "正在移动提醒条"
                    gesture.drag == EdgeDrag.PULL -> "正在拖动提醒卡"
                    animating -> if (opened) "正在展开提醒卡" else "正在收起提醒卡"
                    gesture.activated -> "提醒条已激活"
                    opened -> "向外拖动收起提醒卡"
                    else -> "向内拖动展开提醒卡"
                }
            }
            override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
                super.onInitializeAccessibilityNodeInfo(info)
                info.addAction(if (opened) AccessibilityNodeInfo.AccessibilityAction.ACTION_COLLAPSE else AccessibilityNodeInfo.AccessibilityAction.ACTION_EXPAND)
            }
            override fun performAccessibilityAction(action: Int, args: android.os.Bundle?): Boolean {
                if (action == AccessibilityNodeInfo.AccessibilityAction.ACTION_EXPAND.id || action == AccessibilityNodeInfo.AccessibilityAction.ACTION_COLLAPSE.id) {
                    settle(action == AccessibilityNodeInfo.AccessibilityAction.ACTION_EXPAND.id, 0f); return true
                }
                return super.performAccessibilityAction(action, args)
            }
        }

        private inner class Gesture {
            private val handler = Handler(Looper.getMainLooper())
            private var initialTouch: MotionEvent? = null
            private var claimDashboard: ((MotionEvent) -> Unit)? = null
            private val activate = Runnable {
                val event = initialTouch ?: return@Runnable
                activated = true
                claimDashboard?.invoke(event)
                folded.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                feedback()
            }
            var tracker: VelocityTracker? = null
                private set
            var drag: EdgeDrag? = null
                private set
            private var source = -1
            val fromDashboard get() = source == 0
            var activated = false
                private set
            private var startAxis = 0f
            private var startCross = 0f
            private var startOffset = 0f
            private var startCrossOffset = 0
            private var startTime = 0L
            private var startedOpen = false
            private fun axis(event: MotionEvent) = if (horizontal) event.rawY else -event.rawX
            private fun cross(event: MotionEvent) = if (horizontal) event.rawX else event.rawY
            fun touch(event: MotionEvent, origin: Int, allowMove: Boolean, claim: ((MotionEvent) -> Unit)? = null): Boolean {
                if (event.actionMasked == MotionEvent.ACTION_DOWN) {
                    // A child ScrollView may take its UP/CANCEL after the card contents are replaced.
                    // A new pointer sequence always owns a fresh tracker.
                    release()
                    if (origin == 0) {
                        if (shown > 0 || !folded.isLaidOut) return false
                        val location = IntArray(2); folded.getLocationOnScreen(location)
                        val halfLong = ui.dp(48)
                        val halfShort = thickness / 2
                        val x = location[0] + folded.width / 2f
                        val y = location[1] + folded.height / 2f
                        if (abs(event.rawX - x) > (if (horizontal) halfLong else halfShort) ||
                            abs(event.rawY - y) > (if (horizontal) halfShort else halfLong)) return false
                        initialTouch = MotionEvent.obtain(event)
                        claimDashboard = claim
                        handler.postAtTime(activate, event.eventTime + 500)
                    }
                    animator?.cancel()
                    source = origin; startAxis = axis(event); startCross = cross(event); startOffset = shown
                    startCrossOffset = crossOffset; startTime = event.eventTime; startedOpen = opened
                    tracker = VelocityTracker.obtain()
                    activated = origin != 0
                    record(event); feedback()
                    return false
                }
                if (tracker == null || source != origin) return false
                if (!activated) {
                    val moved = maxOf(abs(axis(event) - startAxis), abs(cross(event) - startCross))
                    if (event.actionMasked != MotionEvent.ACTION_MOVE || moved > ui.dp(6)) release()
                    return false
                }
                if (event.actionMasked == MotionEvent.ACTION_POINTER_DOWN || event.actionMasked == MotionEvent.ACTION_CANCEL) {
                    return cancel()
                }
                record(event)
                val pull = axis(event) - startAxis
                val along = cross(event) - startCross
                if (drag == null) {
                    val candidate = EdgeSheetMotion.drag(pull, along, ui.dp(4))
                    if (allowMove || candidate == EdgeDrag.PULL && pull < 0) drag = candidate
                }
                when (drag) {
                    EdgeDrag.PULL -> position(startOffset + pull)
                    EdgeDrag.REPOSITION -> {
                        crossOffset = (startCrossOffset + along.roundToInt()).coerceIn(-crossLimit, crossLimit)
                        // Only movement along the screen edge changes a window's geometry.
                        updateCross(); feedback()
                    }
                    null -> Unit
                }
                val claimed = drag != null
                if (event.actionMasked == MotionEvent.ACTION_UP) {
                    tracker?.computeCurrentVelocity(1000, ViewConfiguration.get(ui.context).scaledMaximumFlingVelocity.toFloat())
                    val velocity = if (horizontal) tracker?.yVelocity ?: 0f else -(tracker?.xVelocity ?: 0f)
                    val speed = EdgeSheetMotion.releaseSpeed(velocity, pull, event.eventTime - startTime, density)
                    if (BuildConfig.DEBUG) android.util.Log.d("FocusEdgeGesture",
                        "release source=$source drag=$drag pull=$pull elapsed=${event.eventTime - startTime} velocity=$velocity shown=$shown extent=$extent speed=$speed")
                    val current = drag
                    release()
                    if (current == EdgeDrag.REPOSITION && crossLimit > 0) prefs.saveEdgePosition(horizontal, crossOffset.toFloat() / crossLimit)
                    if (current == EdgeDrag.PULL) settle(EdgeSheetMotion.opens(shown, extent, speed, startedOpen, density), speed)
                    else settle(startedOpen, 0f)
                }
                return claimed
            }
            private fun record(event: MotionEvent) {
                val raw = MotionEvent.obtain(event)
                raw.offsetLocation(event.rawX - event.x, event.rawY - event.y)
                tracker?.addMovement(raw); raw.recycle()
            }
            fun cancel(): Boolean {
                val claimed = drag != null
                if (drag == EdgeDrag.REPOSITION) { crossOffset = startCrossOffset; updateCross() }
                release()
                if (claimed) settle(startedOpen, 0f)
                return claimed
            }
            fun release() {
                handler.removeCallbacks(activate)
                initialTouch?.recycle(); initialTouch = null; claimDashboard = null
                tracker?.recycle(); tracker = null; drag = null; source = -1; activated = false
                feedback()
            }
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
        if (abs(speed) >= 320 * density) return speed > 0
        val projected = (offset + speed * .12f).coerceIn(0f, extent)
        return projected >= extent * if (opened) .60f else .35f
    }
    fun duration(remaining: Float, speed: Float, density: Float): Long =
        (90 + remaining / (density.coerceAtLeast(1f) * 1.4f + abs(speed) / 1000f)).toLong().coerceIn(100, 240)
}
