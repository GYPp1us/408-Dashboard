package com.mutsumi.focus

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.FrameLayout

internal class ReminderEdgeWindow(private val context: Context, private val onChoose: (Int) -> Unit) {
    private var view: View? = null
    private var manager: WindowManager? = null
    private var styleKey = ""
    private var expanded = false

    fun update(show: Boolean, accent: Int) {
        if (!show) { dismiss(); return }
        val specific = if (Settings.canDrawOverlays(context)) context else FocusAccessibilityService.connectedContext()
        if (specific == null) { dismiss(); return }
        val type = if (specific === context) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
        val horizontal = context.resources.configuration.orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE
        val key = "$type:$horizontal:$accent"
        if (key == styleKey && view != null) return
        dismiss()
        val windowContext = if (type == WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY && Build.VERSION.SDK_INT >= 30) {
            runCatching { specific.createWindowContext(type, null) }.getOrDefault(specific)
        } else specific
        val style = ReminderUi(windowContext, accent)
        manager = windowContext.getSystemService(WindowManager::class.java)
        val edge = object : View(windowContext) {
            private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            private val bar = RectF()
            private var x0 = 0f
            private var y0 = 0f
            private var distance = 0f
            init {
                setLayerType(LAYER_TYPE_SOFTWARE, null)
                contentDescription = "专注提醒设置"; isClickable = true; isFocusable = true
                setOnClickListener { openCard(style, type, horizontal) }
            }
            override fun onDraw(canvas: Canvas) {
                val travel = (distance / style.dp(55)).coerceIn(0f, 1f) * style.dp(6)
                val halfLength = style.dp(30).toFloat()
                val halfWidth = style.dp(2).toFloat()
                val cx = if (horizontal) width * .5f else width - style.dp(15) - travel
                val cy = if (horizontal) style.dp(12) + travel else height * .5f
                bar.set(cx - if (horizontal) halfLength else halfWidth, cy - if (horizontal) halfWidth else halfLength,
                    cx + if (horizontal) halfLength else halfWidth, cy + if (horizontal) halfWidth else halfLength)
                paint.color = accent; paint.setShadowLayer(style.dp(8).toFloat(), 0f, 0f, accent)
                canvas.drawRoundRect(bar, halfWidth, halfWidth, paint)
                paint.clearShadowLayer()
            }
            override fun onTouchEvent(event: MotionEvent): Boolean {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> { x0 = event.rawX; y0 = event.rawY; distance = 0f; return true }
                    MotionEvent.ACTION_MOVE -> { distance = if (horizontal) event.rawY - y0 else x0 - event.rawX; invalidate(); return true }
                    MotionEvent.ACTION_UP -> {
                        val delta = if (horizontal) event.rawY - y0 else x0 - event.rawX
                        if (delta >= style.dp(26) || (kotlin.math.abs(event.rawX - x0) < style.dp(8) &&
                                kotlin.math.abs(event.rawY - y0) < style.dp(8))) performClick()
                        distance = 0f; invalidate(); return true
                    }
                    MotionEvent.ACTION_CANCEL -> { distance = 0f; invalidate(); return true }
                }
                return false
            }
            override fun performClick(): Boolean = super.performClick()
        }
        if (attach(edge, params(style, type, horizontal, false))) styleKey = key
    }

    private fun openCard(style: ReminderUi, type: Int, horizontal: Boolean) {
        if (expanded) return
        val card = style.vertical().apply {
            setPadding(style.dp(16), style.dp(13), style.dp(16), style.dp(13))
            background = style.surface(Color.WHITE, 10, style.border)
            style.add(this, style.tag("M  /  专注提醒"))
            style.add(this, style.label("关闭所有提醒", 21f, bold = true), 4)
            style.add(this, style.label("选一个时长，再答一道题。", 14f, style.muted), 3)
            style.add(this, style.durations(PopupReminderStore(context).muteOptions, onChoose), 11)
            style.add(this, style.button("收起") { dismiss(); FocusService.requestReminderCheck(context) }, 8)
        }
        val host = object : FrameLayout(style.context) {
            override fun dispatchTouchEvent(event: MotionEvent): Boolean {
                if (event.action == MotionEvent.ACTION_OUTSIDE) { dismiss(); FocusService.requestReminderCheck(context); return true }
                return super.dispatchTouchEvent(event)
            }
        }.apply {
            setPadding(style.dp(7), style.dp(7), style.dp(7), style.dp(12)); clipToPadding = false
            addView(card, FrameLayout.LayoutParams(-1, -2)); card.elevation = style.dp(5).toFloat()
        }
        removeView()
        if (attach(host, params(style, type, horizontal, true))) {
            expanded = true
            card.alpha = 0f
            if (horizontal) card.translationY = -style.dp(20).toFloat() else card.translationX = style.dp(25).toFloat()
            card.animate().alpha(1f).translationX(0f).translationY(0f).setDuration(230).start()
        }
    }

    private fun params(style: ReminderUi, type: Int, horizontal: Boolean, card: Boolean): WindowManager.LayoutParams {
        val maxWidth = style.context.resources.configuration.screenWidthDp.takeIf { it > 0 } ?: 360
        return WindowManager.LayoutParams(
            if (card) style.dp(minOf(356, maxWidth - 24)) else style.dp(if (horizontal) 116 else 46),
            if (card) -2 else style.dp(if (horizontal) 38 else 116), type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                (if (card) WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH else 0), PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = if (horizontal) Gravity.TOP or Gravity.CENTER_HORIZONTAL else Gravity.RIGHT or Gravity.CENTER_VERTICAL
            if (horizontal) y = style.dp(if (card) 10 else 3) else x = style.dp(if (card) 11 else 8)
            if (Build.VERSION.SDK_INT >= 30) {
                setFitInsetsTypes(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                setFitInsetsIgnoringVisibility(true)
            }
            setTitle(if (card) "Focus reminder choices" else "Focus reminder edge")
        }
    }

    private fun attach(candidate: View, params: WindowManager.LayoutParams) = runCatching {
        requireNotNull(manager).addView(candidate, params); view = candidate
    }.isSuccess

    private fun removeView() {
        view?.let { runCatching { manager?.removeViewImmediate(it) } }; view = null
    }

    fun dismiss() { removeView(); manager = null; styleKey = ""; expanded = false }
}
