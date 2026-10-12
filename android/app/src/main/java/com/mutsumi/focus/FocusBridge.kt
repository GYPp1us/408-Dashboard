package com.mutsumi.focus

import android.webkit.JavascriptInterface

class FocusBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun getFocusRuntime(): String = FocusService.snapshot(activity)

    @JavascriptInterface
    fun getFocusDestination(): String = activity.focusDestination()

    @JavascriptInterface
    fun clearFocusDestination() = activity.runOnUiThread { activity.clearFocusDestination() }

    @JavascriptInterface
    fun openFocusSettings() = activity.runOnUiThread {
        if (activity.hasTrustedDocument()) activity.openPermissionSetup()
    }

    @JavascriptInterface
    fun performFocusAction(action: String, revision: Long, token: String) {
        val nativeAction = when (action) {
            "pause" -> FocusService.ACTION_PAUSE
            "resume" -> FocusService.ACTION_RESUME
            "end" -> FocusService.ACTION_END
            "endRest" -> FocusService.ACTION_END_REST
            "snooze" -> FocusService.ACTION_SNOOZE
            "dismiss" -> FocusService.ACTION_DISMISS
            else -> return
        }
        activity.runOnUiThread {
            if (!activity.hasTrustedDocument()) return@runOnUiThread
            FocusService.action(activity, android.content.Intent().setAction(nativeAction).apply {
                putExtra(FocusService.EXTRA_REVISION, revision)
                if (token.isNotBlank()) putExtra(FocusService.EXTRA_REMINDER_TOKEN, token)
            })
        }
    }

    @JavascriptInterface
    fun setAppearance(mode: String, palette: String, accent: String) {
        if (mode !in setOf("light", "dark", "system") || palette !in setOf("clay", "sage", "ocean")) return
        activity.runOnUiThread {
            if (!activity.hasTrustedDocument()) return@runOnUiThread
            val state = FocusStateStore(activity).read()
            val group = IslandPalette.group(state.mode)
            val color = runCatching { android.graphics.Color.parseColor(accent) }.getOrElse {
                IslandPalette.fallback(palette, state.mode).accent
            }
            val prefs = activity.getSharedPreferences("focus_runtime", android.content.Context.MODE_PRIVATE)
            if (prefs.getString("theme_mode", "system") == mode && prefs.getString("theme_palette", "clay") == palette &&
                prefs.getString("theme_runtime_group", "") == group && prefs.getInt("theme_runtime_accent", 0) == color) return@runOnUiThread
            prefs.edit().putString("theme_mode", mode).putString("theme_palette", palette)
                .putString("theme_runtime_group", group).putString("theme_runtime_palette", palette)
                .putInt("theme_runtime_accent", color).apply()
            FocusService.requestReminderCheck(activity)
        }
    }
    @JavascriptInterface
    fun setAccountTimeZone(zone: String) {
        if (runCatching { java.time.ZoneId.of(zone) }.isFailure) return
        activity.runOnUiThread {
            if (!activity.hasTrustedDocument()) return@runOnUiThread
            val store = FocusStateStore(activity)
            val state = store.read()
            if (state.accountTimeZone == zone) return@runOnUiThread
            store.write(state.copy(accountTimeZone = zone))
            FocusService.requestReminderCheck(activity)
        }
    }

    @JavascriptInterface
    fun getDisplayOrientation(): String = activity.getDisplayOrientation()

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
            if (FocusService.isBusy()) return@runOnUiThread
            val revision = runCatching { org.json.JSONObject(raw).optLong("revision", -1) }.getOrDefault(-1)
            if (revision >= 0 && revision != store.transitionRevision()) return@runOnUiThread
            val reduced = FocusStateReducer.reduce(store.read(), state, store.endedAcknowledgedCount())
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
