package com.mutsumi.focus

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Persist notification swipe dismissal even while the Activity is closed. */
class FocusActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) { FocusService.action(context, intent) }
}
