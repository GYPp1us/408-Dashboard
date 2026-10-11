package com.mutsumi.focus

import android.webkit.CookieManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.OffsetDateTime

object FocusApi {
    data class Result(val successful: Boolean, val status: Int, val state: FocusRuntimeState? = null)
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
        // The existing dashboard includes today's settlement, so a finish on
        // another device also cancels departure reminders without a new API.
        val connection = (URL(localState.baseUrl + "/api/dashboard").openConnection() as HttpURLConnection)
        return try {
            connection.requestMethod = "GET"
            configure(connection, localState)
            val status = connection.responseCode
            if (status !in 200..299) return StateResult(false, status)
            val payload = connection.inputStream.bufferedReader().use { it.readText() }
            val data = JSONObject(payload)
            val active = data.optJSONObject("focus")?.optJSONObject("active")
            if (active == null) {
                val settled = data.optJSONObject("daily_settlement")
                if (settled != null) return StateResult(true, status, localState.copy(
                    mode = FocusMode.SETTLED,
                    elapsedSeconds = localState.elapsedNow(),
                    todayFocusSeconds = settled.optLong("total_seconds").coerceAtLeast(0),
                    todaySessionCount = settled.optInt("session_count").coerceAtLeast(0),
                    endedAtEpochMs = epochMillis(settled.optString("settled_at")),
                    restStartedAtEpochMs = 0,
                    pausedAtEpochMs = 0,
                    observedAtEpochMs = System.currentTimeMillis(),
                ))
                // Resolve uncertain writes and remote finishes using the real
                // ended record, not the later time this poll happened to arrive.
                if (localState.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.ENDED) && localState.sessionId > 0) {
                    for (key in listOf("recent", "today")) {
                        val rows = data.optJSONObject("focus")?.optJSONArray(key) ?: continue
                        for (index in 0 until rows.length()) {
                            val row = rows.optJSONObject(index) ?: continue
                            if (row.optLong("id") == localState.sessionId && epochMillis(row.optString("ended_at")) > 0)
                                return StateResult(true, status, stateFromPayload(row, localState.baseUrl, System.currentTimeMillis()))
                        }
                    }
                }
                return StateResult(true, status, FocusRuntimeState(baseUrl = localState.baseUrl))
            }
            val now = System.currentTimeMillis()
            StateResult(
                true,
                status,
                stateFromPayload(active, localState.baseUrl, now),
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
            val session = if (status in 200..299) runCatching {
                JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).optJSONObject("session")
            }.getOrNull() else null
            Result(status in 200..299 && (path == "/api/focus/heartbeat" || session != null), status,
                session?.let { stateFromPayload(it, state.baseUrl, System.currentTimeMillis()) })
        } catch (_: Exception) {
            Result(false, 0)
        } finally {
            connection.disconnect()
        }
    }

    private fun configure(connection: HttpURLConnection, state: FocusRuntimeState) {
        connection.connectTimeout = 8_000
        connection.readTimeout = 8_000
        connection.instanceFollowRedirects = false
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("User-Agent", "MutsumiFocus/${BuildConfig.VERSION_NAME}")
        CookieManager.getInstance().getCookie(state.baseUrl)?.takeIf { it.isNotBlank() }?.let {
            connection.setRequestProperty("Cookie", it)
        }
    }

    private fun stateFromPayload(data: JSONObject, baseUrl: String, now: Long): FocusRuntimeState {
        val state = stateFromServerFields(data.optLong("id"), data.optString("subject"),
            data.optString("started_at"), data.optString("paused_at").takeUnless { it.isBlank() || it == "null" },
            data.optLong("effective_seconds"), baseUrl, now).copy(
                plannedSeconds = data.optLong("planned_minutes").coerceIn(0, 1440) * 60,
                focusItemId = data.optLong("focus_item_id"),
                pausedSeconds = data.optLong("paused_seconds").coerceAtLeast(0),
            )
        return if (data.optString("status") == "active" || data.optString("ended_at").let { it.isBlank() || it == "null" }) state
        else state.copy(mode = FocusMode.ENDED, endedAtEpochMs = epochMillis(data.optString("ended_at")), pausedAtEpochMs = 0)
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
