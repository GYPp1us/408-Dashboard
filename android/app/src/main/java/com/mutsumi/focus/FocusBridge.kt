package com.mutsumi.focus

import android.webkit.JavascriptInterface

class FocusBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun syncFocusState(raw: String) {
        val state = try {
            FocusRuntimeState.fromJson(raw)
        } catch (_: Exception) {
            return
        }
        activity.runOnUiThread {
            val store = FocusStateStore(activity)
            val reduced = FocusStateReducer.reduce(store.read(), state, store.endedAcknowledgedCount())
            store.write(reduced)
            FocusService.sync(activity, reduced)
        }
    }
}
