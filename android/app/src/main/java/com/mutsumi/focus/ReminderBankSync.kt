package com.mutsumi.focus

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

internal object ReminderBankSync {
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var refreshing = false

    fun refresh(context: Context, done: ((Int?) -> Unit)? = null) {
        if (refreshing && done == null) return
        val store = PopupReminderStore(context.applicationContext)
        val generation = store.accountGeneration
        refreshing = true
        worker.execute {
            val result = FocusApi.reminderBankRequest()
            main.post {
                refreshing = false
                val valid = result != null && result.optJSONArray("questions") != null && store.accountGeneration == generation
                if (valid) store.bankJson = result.toString()
                done?.invoke(if (valid) ReminderQuestions.decode(store.bankJson).size else null)
            }
        }
    }

    fun connection(context: Context, rotate: Boolean, done: (String?) -> Unit) {
        val store = PopupReminderStore(context.applicationContext)
        val generation = store.accountGeneration
        worker.execute {
            val result = FocusApi.reminderBankRequest(connectionDetails = true, rotate = rotate)
            main.post { done(result?.optString("prompt")?.takeIf { it.isNotBlank() && store.accountGeneration == generation }) }
        }
    }
}
