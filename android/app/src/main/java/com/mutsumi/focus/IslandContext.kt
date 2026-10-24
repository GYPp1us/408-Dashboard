package com.mutsumi.focus

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId

/** Account schedule for island displays and next-focus reminder eligibility; never changes a focus session. */
data class IslandContext(
    val timezone: String = "Asia/Shanghai",
    val sessions: List<Session> = emptyList(),
    val checkins: List<Checkin> = emptyList(),
    val receivedAt: Long = 0,
    val taskSync: TaskSync? = null,
) {
    data class Session(val start: LocalTime, val end: LocalTime)
    data class Checkin(val id: Long, val name: String, val start: LocalTime, val end: LocalTime, val completedDay: String = "")
    data class TaskSync(val eventId: String, val date: String, val status: String,
                        val completed: Int, val total: Int, val updatedAt: Long) {
        val key: String get() = "task-sync:$eventId:$status:$completed:$total:$updatedAt"
        val lifetime: Long get() = when (status) { "pending" -> 10 * 60_000L; "sent" -> 15_000L; else -> 30_000L }
        fun json() = JSONObject().put("event_id", eventId).put("date", date).put("status", status)
            .put("completed", completed).put("total", total).put("updated_at", Instant.ofEpochMilli(updatedAt).toString())
        companion object {
            fun fromJson(value: JSONObject?): TaskSync? = runCatching {
                if (value == null || value.optString("status") !in setOf("pending", "sent", "failed", "unconfigured")) return null
                val total = value.getInt("total").coerceIn(0, 100_000)
                TaskSync(value.getString("event_id").take(160), java.time.LocalDate.parse(value.getString("date")).toString(),
                    value.getString("status"), value.getInt("completed").coerceIn(0, total), total,
                    Instant.parse(value.getString("updated_at")).toEpochMilli())
            }.getOrNull()
        }
    }
    data class Countdown(val kind: Kind, val end: Long, val name: String = "", val id: Long = 0) {
        enum class Kind { AFTERNOON, CHECKIN, WAITING }
        fun remaining(now: Long): Long = if (kind == Kind.WAITING) (now - end).coerceAtLeast(0) / 1000
            else ((end - now).coerceAtLeast(0) + 999) / 1000
        val key: String get() = "$kind:$id:$end"
    }

    fun enabled(now: Long): Boolean = receivedAt > 0 && now - receivedAt in 0 until 36 * 3_600_000L &&
        (sessions.isNotEmpty() || checkins.isNotEmpty() || taskSync?.let { now - it.updatedAt in 0 until it.lifetime } == true)

    fun visibleTaskSync(state: FocusRuntimeState, due: DueReminder?, now: Long): TaskSync? {
        val sync = taskSync ?: return null
        if (!enabled(now) || state.mode != FocusMode.SETTLED || due != null) return null
        if (Instant.ofEpochMilli(now).atZone(ZoneId.of(timezone)).toLocalDate().toString() != sync.date) return null
        return sync.takeIf { now - it.updatedAt in 0 until it.lifetime }
    }

    fun allowsNextFocusReminder(now: Long): Boolean {
        // Retain compatibility before an older client has received a schedule.
        // Cached hours still suppress closed-period reminders if a refresh is late.
        if (sessions.isEmpty()) return receivedAt <= 0
        val time = Instant.ofEpochMilli(now).atZone(ZoneId.of(timezone)).toLocalTime()
        return sessions.any { time >= it.start && time < it.end }
    }

    fun nextBoundary(now: Long): Long {
        val local = Instant.ofEpochMilli(now).atZone(ZoneId.of(timezone))
        val times = sessions.flatMap { listOf(it.start, it.end) } + checkins.flatMap { listOf(it.start, it.end) } + LocalTime.MIDNIGHT
        return (0L..1L).flatMap { offset -> times.map { local.toLocalDate().plusDays(offset).atTime(it)
            .atZone(local.zone).toInstant().toEpochMilli() } }.filter { it > now }.minOrNull() ?: now + 15_000
    }

    fun countdown(state: FocusRuntimeState, due: DueReminder?, now: Long): Countdown? {
        if (!enabled(now) || state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.REST) ||
            due != null || state.summaryVisible(now)) return null
        val local = Instant.ofEpochMilli(now).atZone(ZoneId.of(timezone))
        val day = local.toLocalDate()
        val time = local.toLocalTime()
        sessions.zipWithNext().firstOrNull { (morning, afternoon) -> time >= morning.end && time < afternoon.start }?.let { (_, afternoon) ->
            return Countdown(Countdown.Kind.AFTERNOON, day.atTime(afternoon.start).atZone(local.zone).toInstant().toEpochMilli())
        }
        return checkins.mapNotNull { rule ->
            if (rule.completedDay == day.toString()) return@mapNotNull null
            val overnight = rule.start > rule.end
            val active = if (overnight) time >= rule.start || time < rule.end else time >= rule.start && time < rule.end
            if (!active) return@mapNotNull null
            val endDay = if (overnight && time >= rule.start) day.plusDays(1) else day
            Countdown(Countdown.Kind.CHECKIN, endDay.atTime(rule.end).atZone(local.zone).toInstant().toEpochMilli(), rule.name, rule.id)
        }.minWithOrNull(compareBy<Countdown> { it.end }.thenBy { it.id }) ?: openingWait(state, now)
    }

    /** Opening is only a display/reminder anchor, never a fabricated session. */
    fun openingWait(state: FocusRuntimeState, now: Long): Countdown? {
        // Daily settlement is a terminal opt-out, not another idle opening.
        // Its 30s summary may expire; that must never restart waiting/reminders.
        if (!enabled(now) || state.mode in setOf(FocusMode.FOCUSING, FocusMode.PAUSED, FocusMode.REST, FocusMode.SETTLED) || state.summaryVisible(now)) return null
        val local = Instant.ofEpochMilli(now).atZone(ZoneId.of(timezone))
        val session = sessions.firstOrNull { local.toLocalTime() >= it.start && local.toLocalTime() < it.end } ?: return null
        val opening = local.toLocalDate().atTime(session.start).atZone(local.zone).toInstant().toEpochMilli()
        // A real completion after opening retains its own waiting/reminder clock.
        if (state.mode == FocusMode.ENDED && state.endedAtEpochMs >= opening) return null
        return Countdown(Countdown.Kind.WAITING, opening)
    }

    fun toJson(): String = JSONObject().apply {
        put("timezone", timezone); put("received_at", receivedAt)
        taskSync?.let { put("task_sync", it.json()) }
        put("sessions", JSONArray().apply { sessions.forEach { put(JSONObject().put("start", it.start.toString()).put("end", it.end.toString())) } })
        put("checkins", JSONArray().apply { checkins.forEach { put(JSONObject().put("id", it.id).put("name", it.name)
            .put("start", it.start.toString()).put("end", it.end.toString()).put("completed_day", it.completedDay)) } })
    }.toString()

    companion object {
        fun fromJson(data: JSONObject?, receivedAt: Long = System.currentTimeMillis()): IslandContext? {
            if (data == null) return null
            return runCatching {
            val zone = ZoneId.of(data.getString("timezone")).id
            val windows = data.optJSONArray("sessions") ?: JSONArray()
            val rules = data.optJSONArray("checkins") ?: JSONArray()
            IslandContext(zone, (0 until windows.length().coerceAtMost(8)).map { windows.getJSONObject(it).let { row ->
                Session(LocalTime.parse(row.getString("start")), LocalTime.parse(row.getString("end")))
            } }.filter { it.end > it.start }.sortedBy { it.start },
                (0 until rules.length().coerceAtMost(50)).map { rules.getJSONObject(it).let { row ->
                    Checkin(row.getLong("id"), row.getString("name").take(40), LocalTime.parse(row.getString("start")),
                        LocalTime.parse(row.getString("end")), row.optString("completed_day").takeUnless { it == "null" }.orEmpty())
                } }.filter { it.id > 0 && it.start != it.end }, receivedAt, TaskSync.fromJson(data.optJSONObject("task_sync")))
            }.getOrNull()
        }
    }
}
