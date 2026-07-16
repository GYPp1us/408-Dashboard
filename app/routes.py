from datetime import datetime, timedelta, timezone
import re

from flask import jsonify, redirect, render_template, request, session, url_for

from .auth import admin_required, is_guest, login_required
from .db import connect, finish_focus_session, get_focus_messages, get_settings, list_focus_modes, list_latest_scores, list_plans, list_scores, replace_focus_modes, save_focus_messages
from .services import aggregate_focus_heatmap, aggregate_focus_investment, calculate_window, current_time, score_metrics, seconds_until_exam, summarize_today_focus


TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
HEATMAP_HOURS = tuple(range(0, 24, 2))


def _heatmap_hours(value: str) -> list[int]:
    parts = [part.strip() for part in str(value).split(",") if part.strip()]
    hours = [int(part) for part in parts]
    if not hours or len(hours) != len(set(hours)) or any(hour not in HEATMAP_HOURS for hour in hours):
        raise ValueError("invalid_heatmap_visible_hours")
    return [hour for hour in HEATMAP_HOURS if hour in hours]


def _focus_subjects(value) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("invalid_focus_subjects")
    subjects = [str(subject).strip() for subject in value]
    if not 1 <= len(subjects) <= 12 or any(not subject or len(subject) > 24 for subject in subjects) or len(subjects) != len(set(subjects)):
        raise ValueError("invalid_focus_subjects")
    return subjects


def _focus_messages(value) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError("invalid_focus_messages")
    messages = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid_focus_messages")
        category = str(item.get("category", "")).strip()
        text = str(item.get("text", "")).strip()
        if not category or not text or len(category) > 20 or len(text) > 120:
            raise ValueError("invalid_focus_messages")
        messages.append({"category": category, "text": text})
    return messages


def _now(timezone_name: str = "UTC") -> datetime:
    return current_time(timezone_name)


def _pause_map(connection) -> dict[int, list[dict]]:
    pauses: dict[int, list[dict]] = {}
    for row in connection.execute("SELECT * FROM focus_pauses ORDER BY started_at"):
        pauses.setdefault(row["session_id"], []).append(dict(row))
    return pauses


def _session_segments(row: dict, pauses: list[dict], now: datetime) -> list[tuple[datetime, datetime]]:
    start = datetime.fromisoformat(row["started_at"]).astimezone(now.tzinfo)
    end = datetime.fromisoformat(row["ended_at"]).astimezone(now.tzinfo) if row.get("ended_at") else now
    cursor = start
    segments = []
    for pause in pauses:
        pause_start = datetime.fromisoformat(pause["started_at"]).astimezone(now.tzinfo)
        pause_end = datetime.fromisoformat(pause["ended_at"]).astimezone(now.tzinfo) if pause.get("ended_at") else end
        if pause_end <= cursor or pause_start >= end:
            continue
        pause_start = max(start, pause_start)
        pause_end = min(end, pause_end)
        if pause_start > cursor:
            segments.append((cursor, pause_start))
        cursor = max(cursor, pause_end)
    if cursor < end:
        segments.append((cursor, end))
    return segments


def _session_payload(row: dict | None, pauses: list[dict], now: datetime) -> dict | None:
    if not row:
        return None
    payload = dict(row)
    closed_paused_seconds = 0
    paused_at = None
    for pause in pauses:
        if pause.get("ended_at"):
            closed_paused_seconds += max(0, int((datetime.fromisoformat(pause["ended_at"]) - datetime.fromisoformat(pause["started_at"])).total_seconds()))
        else:
            paused_at = pause["started_at"]
    payload["paused_at"] = paused_at
    payload["paused_seconds"] = closed_paused_seconds
    payload["effective_seconds"] = sum(int((end - start).total_seconds()) for start, end in _session_segments(payload, pauses, now))
    payload["focus_locked"] = bool(payload.get("focus_locked"))
    payload["trusted"] = bool(payload.get("trusted", 1))
    return payload


def _row(connection, session_id: int, now: datetime | None = None):
    row = connection.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    current = now or _now("UTC")
    return _session_payload(dict(row), _pause_map(connection).get(session_id, []), current)


def _focus_rows(connection, now: datetime, limit: int = 20, pauses: dict[int, list[dict]] | None = None) -> list[dict]:
    rows = connection.execute("SELECT * FROM focus_sessions ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    pause_rows = pauses if pauses is not None else _pause_map(connection)
    return [_session_payload(dict(row), pause_rows.get(row["id"], []), now) for row in rows]


def _focus_sessions(connection, now: datetime, pauses: dict[int, list[dict]] | None = None) -> list[tuple[str, datetime, datetime]]:
    rows = connection.execute("SELECT * FROM focus_sessions ORDER BY started_at").fetchall()
    pause_rows = pauses if pauses is not None else _pause_map(connection)
    sessions = []
    for row in rows:
        for start, end in _session_segments(dict(row), pause_rows.get(row["id"], []), now):
            sessions.append((row["subject"], start, end))
    return sessions


def _today_focus_rows(connection, now: datetime, pauses: dict[int, list[dict]] | None = None) -> list[dict]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    rows = connection.execute("SELECT * FROM focus_sessions ORDER BY started_at").fetchall()
    pause_rows = pauses if pauses is not None else _pause_map(connection)
    result = []
    for row in rows:
        row_data = dict(row)
        payload = _session_payload(row_data, pause_rows.get(row["id"], []), now)
        start = datetime.fromisoformat(payload["started_at"]).astimezone(now.tzinfo)
        end = datetime.fromisoformat(payload["ended_at"]).astimezone(now.tzinfo) if payload["ended_at"] else now
        if end <= day_start or start >= day_end:
            continue
        payload["started_at"] = max(start, day_start).isoformat()
        payload["ended_at"] = min(end, day_end).isoformat() if payload["ended_at"] else None
        payload["segments"] = []
        for segment_start, segment_end in _session_segments(row_data, pause_rows.get(row["id"], []), now):
            clipped_start = max(segment_start, day_start)
            clipped_end = min(segment_end, day_end)
            if clipped_end <= clipped_start:
                continue
            is_running = not row_data.get("ended_at") and not payload["paused_at"] and clipped_end >= now
            payload["segments"].append({
                "started_at": clipped_start.isoformat(),
                "ended_at": None if is_running else clipped_end.isoformat(),
            })
        payload["effective_seconds"] = sum(
            max(0, int(((datetime.fromisoformat(segment["ended_at"]) if segment["ended_at"] else now) - datetime.fromisoformat(segment["started_at"])).total_seconds()))
            for segment in payload["segments"]
        )
        result.append(payload)
    return result


def register_routes(app):
    @app.get("/")
    def dashboard():
        if not session.get("authenticated") or is_guest():
            return redirect(url_for("guest_dashboard"))
        return render_template("dashboard.html", page_name="home", is_guest=False)

    @app.get("/guest")
    def guest_dashboard():
        session.clear()
        session["authenticated"] = True
        session["role"] = "guest"
        return render_template("dashboard.html", page_name="home", is_guest=True)

    @app.get("/focus")
    def focus_compatibility_redirect():
        return redirect(url_for("dashboard"))

    @app.get("/settings")
    @admin_required
    def settings_page():
        return render_template("settings.html", page_name="settings", is_guest=False)

    @app.get("/api/dashboard")
    @login_required
    def dashboard_api():
        connection = connect(app.config["DATABASE"])
        connection.execute("UPDATE focus_sessions SET last_foreground_at = ? WHERE status = 'active'", (_now("UTC").isoformat(),))
        connection.commit()
        settings = get_settings(connection)
        now = _now(settings.get("timezone", "Asia/Shanghai"))
        try:
            windows = {
                "morning": calculate_window(now, settings["morning_start"], settings["lunch_start"]),
                "library": calculate_window(now, settings["library_open"], settings["library_close"]),
            }
            pauses = _pause_map(connection)
            active_row = connection.execute("SELECT * FROM focus_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
            focus_sessions = _focus_sessions(connection, now, pauses)
            sessions = [(start, end) for _, start, end in focus_sessions]
            today_rows = _today_focus_rows(connection, now, pauses)
            today_focus = summarize_today_focus(sessions, now)
            today_focus["count"] = len(today_rows)
            scores = score_metrics(list_latest_scores(connection))
            score_history = score_metrics(list_scores(connection))
            plans = list_plans(connection)
            try:
                heatmap_visible_hours = _heatmap_hours(settings.get("heatmap_visible_hours", ""))
            except (TypeError, ValueError):
                heatmap_visible_hours = list(HEATMAP_HOURS)
            return jsonify({
                "now": now.isoformat(),
                "exam": {"date": settings["exam_date"], "remaining_seconds": seconds_until_exam(now, settings["exam_date"])},
                "today_focus": today_focus,
                "focus_investment": aggregate_focus_investment(focus_sessions, now),
                "windows": windows,
                "focus": {
                    "active": _session_payload(dict(active_row), pauses.get(active_row["id"], []), now) if active_row else None,
                    "recent": _focus_rows(connection, now, pauses=pauses),
                    "today": today_rows,
                },
                "focus_modes": list_focus_modes(connection),
                "focus_messages": get_focus_messages(connection),
                "heatmap": aggregate_focus_heatmap(sessions, now),
                "heatmap_visible_hours": heatmap_visible_hours,
                "scores": scores,
                "score_history": score_history,
                "plans": plans,
            })
        finally:
            connection.close()

    @app.get("/api/focus")
    @login_required
    def focus_api():
        connection = connect(app.config["DATABASE"])
        try:
            now = _now("UTC")
            active = connection.execute("SELECT * FROM focus_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
            pauses = _pause_map(connection)
            return jsonify({
                "active": _session_payload(dict(active), pauses.get(active["id"], []), now) if active else None,
                "recent": _focus_rows(connection, now, pauses=pauses),
            })
        finally:
            connection.close()

    @app.post("/api/focus/start")
    @admin_required
    def start_focus():
        payload = request.get_json(silent=True) or {}
        subject = str(payload.get("subject", "")).strip()
        mode = str(payload.get("mode", "")).strip()
        client_token = str(payload.get("client_token", "")).strip()
        try:
            planned_minutes = int(payload.get("planned_minutes", 0))
        except (TypeError, ValueError):
            planned_minutes = 0
        if planned_minutes < 0:
            return jsonify(error="planned_minutes_must_be_non_negative"), 400
        if not subject or not mode:
            return jsonify(error="subject_and_mode_required"), 400
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            if client_token:
                existing = connection.execute("SELECT * FROM focus_sessions WHERE client_token = ?", (client_token,)).fetchone()
                if existing:
                    connection.commit()
                    return jsonify(session=_row(connection, existing["id"]), idempotent=True), 200
            active = connection.execute("SELECT id FROM focus_sessions WHERE status = 'active' LIMIT 1").fetchone()
            if active:
                connection.rollback()
                return jsonify(error="focus_already_active"), 409
            started_at = _now("UTC").isoformat()
            cursor = connection.execute(
                "INSERT INTO focus_sessions(subject, mode, planned_minutes, started_at, status, client_token, last_foreground_at) VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (subject, mode, planned_minutes, started_at, client_token or None, started_at),
            )
            connection.commit()
            return jsonify(session=_row(connection, cursor.lastrowid)), 201
        finally:
            connection.close()

    @app.post("/api/focus/end")
    @admin_required
    def end_focus():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            if session_id is None:
                row = connection.execute("SELECT id FROM focus_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
                session_id = row["id"] if row else None
            row = connection.execute("SELECT * FROM focus_sessions WHERE id = ? AND status = 'active'", (session_id,)).fetchone()
            if not row:
                connection.rollback()
                return jsonify(error="active_focus_not_found"), 404
            ended_at = _now("UTC").isoformat()
            finish_focus_session(connection, int(session_id), ended_at)
            connection.commit()
            return jsonify(session=_row(connection, int(session_id)))
        finally:
            connection.close()

    @app.post("/api/focus/pause")
    @admin_required
    def pause_focus():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        should_pause = payload.get("paused")
        if not isinstance(should_pause, bool):
            return jsonify(error="paused_boolean_required"), 400
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM focus_sessions WHERE id = ? AND status = 'active'", (session_id,)).fetchone()
            if not row:
                connection.rollback()
                return jsonify(error="active_focus_not_found"), 404
            open_pause = connection.execute("SELECT id FROM focus_pauses WHERE session_id = ? AND ended_at IS NULL", (session_id,)).fetchone()
            now = _now("UTC").isoformat()
            if should_pause and not open_pause:
                connection.execute("INSERT INTO focus_pauses(session_id, started_at) VALUES (?, ?)", (session_id, now))
                connection.execute("UPDATE focus_sessions SET interruption_count = interruption_count + 1, last_foreground_at = ? WHERE id = ?", (now, session_id))
            elif not should_pause and open_pause:
                connection.execute("UPDATE focus_pauses SET ended_at = ? WHERE id = ?", (now, open_pause["id"]))
                connection.execute("UPDATE focus_sessions SET last_foreground_at = ? WHERE id = ?", (now, session_id))
            connection.commit()
            return jsonify(session=_row(connection, int(session_id)))
        finally:
            connection.close()

    @app.post("/api/focus/lock")
    @admin_required
    def lock_focus():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT id FROM focus_sessions WHERE id = ? AND status = 'active'", (session_id,)).fetchone()
            if not row:
                connection.rollback()
                return jsonify(error="active_focus_not_found"), 404
            connection.execute("UPDATE focus_sessions SET focus_locked = 1, trusted = 0 WHERE id = ?", (session_id,))
            connection.commit()
            return jsonify(session=_row(connection, int(session_id)))
        finally:
            connection.close()

    @app.post("/api/focus/heartbeat")
    @login_required
    def focus_heartbeat():
        now = _now("UTC").isoformat()
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("UPDATE focus_sessions SET last_foreground_at = ? WHERE status = 'active'", (now,))
            connection.commit()
            return jsonify(ok=True)
        finally:
            connection.close()

    @app.route("/api/settings", methods=["GET", "PATCH"])
    @admin_required
    def settings_api():
        connection = connect(app.config["DATABASE"])
        try:
            if request.method == "PATCH":
                payload = request.get_json(silent=True) or {}
                try:
                    if "focus_subjects" in payload:
                        replace_focus_modes(connection, _focus_subjects(payload["focus_subjects"]))
                    if "focus_messages" in payload:
                        save_focus_messages(connection, _focus_messages(payload["focus_messages"]))
                except ValueError as error:
                    return jsonify(error=str(error)), 400
                allowed = {"morning_start", "lunch_start", "library_open", "library_close", "exam_date", "timezone", "heatmap_visible_hours"}
                for key, value in payload.items():
                    if key not in allowed:
                        continue
                    if key.endswith("_start") or key.endswith("_close") or key == "library_open":
                        if not isinstance(value, str) or not TIME_RE.fullmatch(value):
                            return jsonify(error=f"invalid_time:{key}"), 400
                    if key == "exam_date":
                        try:
                            datetime.fromisoformat(value)
                        except (TypeError, ValueError):
                            return jsonify(error="invalid_exam_date"), 400
                    if key == "heatmap_visible_hours":
                        try:
                            value = ",".join(str(hour) for hour in _heatmap_hours(value))
                        except (TypeError, ValueError):
                            return jsonify(error="invalid_heatmap_visible_hours"), 400
                    connection.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
                connection.commit()
            return jsonify(settings=get_settings(connection), focus_modes=list_focus_modes(connection), focus_messages=get_focus_messages(connection))
        finally:
            connection.close()

    @app.route("/api/scores", methods=["GET", "POST"])
    @login_required
    def scores_api():
        if request.method == "POST" and is_guest():
            return jsonify(error="guest_read_only"), 403
        connection = connect(app.config["DATABASE"])
        try:
            if request.method == "POST":
                payload = request.get_json(silent=True) or {}
                try:
                    score = float(payload["score"])
                    target = float(payload["target"])
                except (KeyError, TypeError, ValueError):
                    return jsonify(error="invalid_score_payload"), 400
                if not payload.get("subject") or score < 0 or target <= 0:
                    return jsonify(error="invalid_score_payload"), 400
                connection.execute("INSERT INTO scores(subject, exam_date, score, target) VALUES (?, ?, ?, ?)", (payload["subject"], payload.get("exam_date", _now().date().isoformat()), score, target))
                connection.commit()
            return jsonify(scores=score_metrics(list_latest_scores(connection)))
        finally:
            connection.close()

    @app.route("/api/plans", methods=["GET", "POST"])
    @login_required
    def plans_api():
        if request.method == "POST" and is_guest():
            return jsonify(error="guest_read_only"), 403
        connection = connect(app.config["DATABASE"])
        try:
            if request.method == "POST":
                payload = request.get_json(silent=True) or {}
                try:
                    target_minutes = int(payload["target_minutes"])
                    completed_minutes = int(payload.get("completed_minutes", 0))
                except (KeyError, TypeError, ValueError):
                    return jsonify(error="invalid_plan_payload"), 400
                if not payload.get("week_start") or not payload.get("subject") or not payload.get("title") or target_minutes <= 0 or completed_minutes < 0:
                    return jsonify(error="invalid_plan_payload"), 400
                connection.execute("INSERT INTO plans(week_start, subject, title, target_minutes, completed_minutes) VALUES (?, ?, ?, ?, ?)", (payload["week_start"], payload["subject"], payload["title"], target_minutes, completed_minutes))
                connection.commit()
            return jsonify(plans=list_plans(connection))
        finally:
            connection.close()
