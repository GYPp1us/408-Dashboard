package com.mutsumi.focus

import android.content.Context
import android.provider.Settings
import android.view.WindowManager

class ApplicationOverlay(private val context: Context) {
    private var view: ReminderOverlayView? = null

    fun show(kind: ReminderKind, onContinue: () -> Unit, onOpen: () -> Unit): Boolean {
        dismiss()
        if (!Settings.canDrawOverlays(context)) return false
        return try {
            val overlay = ReminderOverlayView(context, kind, onContinue, onOpen)
            val params = FocusAccessibilityService.overlayLayoutParams(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY)
            context.getSystemService(WindowManager::class.java).addView(overlay, params)
            view = overlay
            true
        } catch (_: Exception) {
            false
        }
    }

    fun dismiss() {
        view?.let { overlay ->
            try { context.getSystemService(WindowManager::class.java).removeView(overlay) } catch (_: Exception) {}
        }
        view = null
    }
}
