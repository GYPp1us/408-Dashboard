from datetime import datetime, timedelta, timezone
import re

from flask import jsonify, redirect, render_template, request, session, url_for

from .auth import admin_required, is_guest, login_required
from .db import connect, get_settings, list_focus_modes, list_latest_scores, list_plans, list_scores
from .services import aggregate_focus_heatmap, calculate_window, current_time, score_metrics, seconds_until_exam, summarize_today_focus


TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _now(timezone_name: str = "UTC") -> datetime:
    return current_time(timezone_name)


def _row(connection, session_id: int):
    row = connection.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def _session_payload(row: dict | None) -> dict | None:
    if not row:
        return None
    return row


def _focus_rows(connection, limit: int = 20) -> list[dict]:
    rows = connection.execute("SELECT * FROM focus_sessions ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def _heatmap_sessions(connection, now: datetime) -> list[tuple[datetime, datetime]]:
    rows = connection.execute("SELECT started_at, ended_at FROM focus_sessions ORDER BY started_at").fetchall()
    sessions = []
    for row in rows:
        start = datetime.fromisoformat(row["started_at"]).astimezone(now.tzinfo)
        end = datetime.fromisoformat(row["ended_at"]).astimezone(now.tzinfo) if row["ended_at"] else now
        sessions.append((start, end))
    return sessions


def _today_focus_rows(connection, now: datetime) -> list[dict]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    rows = connection.execute("SELECT * FROM focus_sessions ORDER BY started_at").fetchall()
    result = []
    for row in rows:
        payload = dict(row)
        start = datetime.fromisoformat(payload["started_at"]).astimezone(now.tzinfo)
        end = datetime.fromisoformat(payload["ended_at"]).astimezone(now.tzinfo) if payload["ended_at"] else now
        if end <= day_start or start >= day_end:
            continue
        payload["started_at"] = max(start, day_start).isoformat()
        payload["ended_at"] = min(end, day_end).isoformat() if payload["ended_at"] else None
        result.append(payload)
    return result


def register_routes(app):
    @app.get("/")
    @login_required
    def dashboard():
        if is_guest():
            return redirect(url_for("guest_dashboard"))
        return render_template("dashboard.html", page_name="home", is_guest=False)

    @app.get("/guest")
    def guest_dashboard():
        if session.get("authenticated") and not is_guest():
            session["admin_authenticated"] = True
        session["authenticated"] = True
        session["role"] = "guest"
        return render_template("dashboard.html", page_name="home", is_guest=True)

    @app.get("/focus")
    @login_required
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
        settings = get_settings(connection)
        now = _now(settings.get("timezone", "Asia/Shanghai"))
        try:
            windows = {
                "morning": calculate_window(now, settings["morning_start"], settings["lunch_start"]),
                "library": calculate_window(now, settings["library_open"], settings["library_close"]),
            }
            active_row = connection.execute("SELECT * FROM focus_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
            sessions = _heatmap_sessions(connection, now)
            scores = score_metrics(list_latest_scores(connection))
            score_history = score_metrics(list_scores(connection))
            plans = list_plans(connection)
            return jsonify({
                "now": now.isoformat(),
                "exam": {"date": settings["exam_date"], "remaining_seconds": seconds_until_exam(now, settings["exam_date"])},
                "today_focus": summarize_today_focus(sessions, now),
                "windows": windows,
                "focus": {"active": _session_payload(dict(active_row) if active_row else None), "recent": _focus_rows(connection), "today": _today_focus_rows(connection, now)},
                "focus_modes": list_focus_modes(connection),
                "heatmap": aggregate_focus_heatmap(sessions, now),
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
            active = connection.execute("SELECT * FROM focus_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
            return jsonify({"active": _session_payload(dict(active) if active else None), "recent": _focus_rows(connection)})
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
                    return jsonify(session=dict(existing), idempotent=True), 200
            active = connection.execute("SELECT id FROM focus_sessions WHERE status = 'active' LIMIT 1").fetchone()
            if active:
                connection.rollback()
                return jsonify(error="focus_already_active"), 409
            started_at = _now("UTC").isoformat()
            cursor = connection.execute(
                "INSERT INTO focus_sessions(subject, mode, planned_minutes, started_at, status, client_token) VALUES (?, ?, ?, ?, 'active', ?)",
                (subject, mode, planned_minutes, started_at, client_token or None),
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
            if session_id is None:
                row = connection.execute("SELECT id FROM focus_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
                session_id = row["id"] if row else None
            row = connection.execute("SELECT * FROM focus_sessions WHERE id = ? AND status = 'active'", (session_id,)).fetchone()
            if not row:
                return jsonify(error="active_focus_not_found"), 404
            connection.execute("UPDATE focus_sessions SET ended_at = ?, status = 'completed' WHERE id = ? AND status = 'active'", (_now("UTC").isoformat(), session_id))
            connection.commit()
            return jsonify(session=_row(connection, int(session_id)))
        finally:
            connection.close()

    @app.route("/api/settings", methods=["GET", "PATCH"])
    @admin_required
    def settings_api():
        connection = connect(app.config["DATABASE"])
        try:
            if request.method == "PATCH":
                payload = request.get_json(silent=True) or {}
                allowed = {"morning_start", "lunch_start", "library_open", "library_close", "exam_date", "timezone"}
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
                    connection.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
                connection.commit()
            return jsonify(settings=get_settings(connection))
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
