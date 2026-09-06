package com.mutsumi.focus

import android.accessibilityservice.AccessibilityService
import android.graphics.PixelFormat
import android.os.Build
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import java.lang.ref.WeakReference

class FocusAccessibilityService : AccessibilityService() {
    private var overlay: ReminderOverlayView? = null

    override fun onServiceConnected() {
        instance = WeakReference(this)
        FocusService.requestReminderCheck(this)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        dismissOverlay()
        instance = null
        super.onDestroy()
    }

    fun showOverlay(kind: ReminderKind, onContinue: () -> Unit, onOpen: () -> Unit): Boolean {
        dismissOverlay()
        return try {
            val view = ReminderOverlayView(this, kind, onContinue, onOpen)
            val params = overlayLayoutParams(WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY)
            getSystemService(WindowManager::class.java).addView(view, params)
            overlay = view
            true
        } catch (_: Exception) {
            false
        }
    }

    fun dismissOverlay() {
        overlay?.let { view ->
            try { getSystemService(WindowManager::class.java).removeView(view) } catch (_: Exception) {}
        }
        overlay = null
    }

    companion object {
        private var instance: WeakReference<FocusAccessibilityService>? = null

        fun isConnected(): Boolean = instance?.get() != null

        fun show(kind: ReminderKind, onContinue: () -> Unit, onOpen: () -> Unit): Boolean =
            instance?.get()?.showOverlay(kind, onContinue, onOpen) == true

        fun dismiss() {
            instance?.get()?.dismissOverlay()
        }

        fun overlayLayoutParams(type: Int): WindowManager.LayoutParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_BLUR_BEHIND,
            PixelFormat.TRANSLUCENT,
        ).apply {
            if (Build.VERSION.SDK_INT >= 31) blurBehindRadius = 28
        }
    }
}
