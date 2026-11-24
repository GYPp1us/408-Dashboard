package com.mutsumi.focus

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

internal object ReminderBankSync {
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private class Refresh(val generation: Long) {
        val callbacks = mutableListOf<(Int?) -> Unit>()
    }

    private var pending: Refresh? = null

    fun refresh(context: Context, done: ((Int?) -> Unit)? = null) {
        val store = PopupReminderStore(context.applicationContext)
        val generation = store.accountGeneration
        val current = pending
        if (current?.generation == generation) {
            done?.let { current.callbacks.add(it) }
            return
        }
        val refresh = Refresh(generation)
        done?.let { refresh.callbacks.add(it) }
        pending = refresh
        worker.execute {
            val result = FocusApi.reminderBankRequest()
            main.post {
                if (pending === refresh) pending = null
                val valid = result != null && result.optJSONArray("questions") != null && store.accountGeneration == generation
                if (valid) store.bankJson = result.toString()
                val count = if (valid && refresh.callbacks.isNotEmpty()) ReminderQuestions.decode(store.bankJson).size else null
                refresh.callbacks.forEach { it(count) }
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
