package com.mutsumi.focus

import android.webkit.JavascriptInterface

class FocusBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun imagePickerOwnsBack(): Boolean = activity.imagePickerOwnsBack()

    @JavascriptInterface
    fun syncFocusState(raw: String) {
        val state = try {
            FocusRuntimeState.fromJson(raw)
        } catch (_: Exception) {
            return
        }
        activity.runOnUiThread {
            if (!activity.hasTrustedDocument()) return@runOnUiThread
            val store = FocusStateStore(activity)
            val reduced = FocusStateReducer.reduce(store.read(), state, store.endedAcknowledgedCount())
            store.write(reduced)
            FocusService.sync(activity, reduced)
        }
    }

    @JavascriptInterface
    fun clearFocusState() {
        activity.runOnUiThread {
            if (activity.hasTrustedDocument()) FocusService.clear(activity)
        }
    }
}
