package com.mutsumi.focus

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import java.lang.ref.WeakReference

class FocusAccessibilityService : AccessibilityService() {
    override fun onServiceConnected() {
        instance = WeakReference(this)
        FocusService.requestReminderCheck(this)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        instance = null
        FocusService.requestReminderCheck(this)
        super.onDestroy()
    }

    companion object {
        private var instance: WeakReference<FocusAccessibilityService>? = null

        fun isConnected(): Boolean = instance?.get() != null
        internal fun connectedContext(): FocusAccessibilityService? = instance?.get()
    }
}
