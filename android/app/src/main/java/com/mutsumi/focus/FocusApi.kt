package com.mutsumi.focus

import android.webkit.CookieManager
import java.net.HttpURLConnection
import java.net.URL

object FocusApi {
    data class Result(val successful: Boolean, val status: Int)

    fun heartbeat(state: FocusRuntimeState): Result = post(
        state,
        "/api/focus/heartbeat",
        "{\"session_id\":${state.sessionId},\"allow_recovery\":true}",
    )

    fun setPaused(state: FocusRuntimeState, paused: Boolean): Result = post(
        state,
        "/api/focus/pause",
        "{\"session_id\":${state.sessionId},\"paused\":$paused}",
    )

    fun end(state: FocusRuntimeState): Result = post(
        state,
        "/api/focus/end",
        "{\"session_id\":${state.sessionId}}",
    )

    private fun post(state: FocusRuntimeState, path: String, body: String): Result {
        if (state.sessionId <= 0) return Result(false, 0)
        val connection = (URL(state.baseUrl + path).openConnection() as HttpURLConnection)
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 8_000
            connection.readTimeout = 8_000
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Accept", "application/json")
            CookieManager.getInstance().getCookie(state.baseUrl)?.takeIf { it.isNotBlank() }?.let {
                connection.setRequestProperty("Cookie", it)
            }
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            Result(status in 200..299, status)
        } catch (_: Exception) {
            Result(false, 0)
        } finally {
            connection.disconnect()
        }
    }
}
