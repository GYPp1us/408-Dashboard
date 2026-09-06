package com.mutsumi.focus

import android.webkit.CookieManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.OffsetDateTime

object FocusApi {
    data class Result(val successful: Boolean, val status: Int)
    data class StateResult(val successful: Boolean, val status: Int, val state: FocusRuntimeState? = null)

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

    fun fetchState(localState: FocusRuntimeState): StateResult {
        val connection = (URL(localState.baseUrl + "/api/focus").openConnection() as HttpURLConnection)
        return try {
            connection.requestMethod = "GET"
            configure(connection, localState)
            val status = connection.responseCode
            if (status !in 200..299) return StateResult(false, status)
            val payload = connection.inputStream.bufferedReader().use { it.readText() }
            val active = JSONObject(payload).optJSONObject("active")
                ?: return StateResult(true, status, FocusRuntimeState(baseUrl = localState.baseUrl))
            val now = System.currentTimeMillis()
            StateResult(
                true,
                status,
                stateFromServerFields(
                    sessionId = active.optLong("id"),
                    subject = active.optString("subject"),
                    startedAt = active.optString("started_at"),
                    pausedAt = active.optString("paused_at").takeUnless { it.isBlank() || it == "null" },
                    effectiveSeconds = active.optLong("effective_seconds"),
                    baseUrl = localState.baseUrl,
                    observedAtEpochMs = now,
                ),
            )
        } catch (_: Exception) {
            StateResult(false, 0)
        } finally {
            connection.disconnect()
        }
    }

    private fun post(state: FocusRuntimeState, path: String, body: String): Result {
        if (state.sessionId <= 0) return Result(false, 0)
        val connection = (URL(state.baseUrl + path).openConnection() as HttpURLConnection)
        return try {
            connection.requestMethod = "POST"
            configure(connection, state)
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            Result(status in 200..299, status)
        } catch (_: Exception) {
            Result(false, 0)
        } finally {
            connection.disconnect()
        }
    }

    private fun configure(connection: HttpURLConnection, state: FocusRuntimeState) {
        connection.connectTimeout = 8_000
        connection.readTimeout = 8_000
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("User-Agent", "MutsumiFocus/${BuildConfig.VERSION_NAME}")
        CookieManager.getInstance().getCookie(state.baseUrl)?.takeIf { it.isNotBlank() }?.let {
            connection.setRequestProperty("Cookie", it)
        }
    }

    internal fun stateFromServerFields(
        sessionId: Long,
        subject: String,
        startedAt: String,
        pausedAt: String?,
        effectiveSeconds: Long,
        baseUrl: String,
        observedAtEpochMs: Long,
    ): FocusRuntimeState = FocusRuntimeState(
        mode = if (pausedAt == null) FocusMode.FOCUSING else FocusMode.PAUSED,
        sessionId = sessionId,
        subject = subject.take(120),
        startedAtEpochMs = epochMillis(startedAt),
        pausedAtEpochMs = pausedAt?.let(::epochMillis) ?: 0,
        elapsedSeconds = effectiveSeconds.coerceAtLeast(0),
        observedAtEpochMs = observedAtEpochMs,
        baseUrl = baseUrl,
    )

    internal fun epochMillis(value: String): Long = try {
        OffsetDateTime.parse(value).toInstant().toEpochMilli()
    } catch (_: Exception) {
        0
    }
}
