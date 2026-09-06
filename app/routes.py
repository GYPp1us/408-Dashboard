from datetime import datetime, timedelta, timezone
import re

import secrets
import sqlite3

from flask import abort, jsonify, redirect, render_template, request, session, url_for

from .auth import admin_required, current_user_id, is_guest, login_required, user_required
from .db import add_friend, connect, consume_migration_code, create_focus_item, create_migration_code, create_subject, delete_focus_item, delete_subject, export_migration_data, finish_focus_session, get_daily_settlement, get_focus_item, get_focus_item_by_name, get_focus_messages, get_settings, get_subject, get_subject_by_name, get_user, get_user_by_username, issue_invitation, list_focus_items, list_focus_modes, list_friends, list_invitations, list_latest_scores, list_plans, list_public_users, list_scores, list_subjects, record_foreground_heartbeat, remove_friend, reorder_focus_items, save_focus_messages, update_focus_item, update_subject
from .services import aggregate_focus_heatmap, aggregate_focus_investment, calculate_window, current_time, focus_leaderboard, score_metrics, seconds_until_exam, summarize_today_focus


TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
HEATMAP_HOURS = tuple(range(0, 24, 2))
DAILY_TARGET_SECONDS = 7 * 3600


def _heatmap_hours(value: str) -> list[int]:
    parts = [part.strip() for part in str(value).split(",") if part.strip()]
    hours = [int(part) for part in parts]
    if not hours or len(hours) != len(set(hours)) or any(hour not in HEATMAP_HOURS for hour in hours):
        raise ValueError("invalid_heatmap_visible_hours")
    return [hour for hour in HEATMAP_HOURS if hour in hours]


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


def _focus_rows(connection, now: datetime, limit: int = 20, pauses: dict[int, list[dict]] | None = None, user_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM focus_sessions"
    params: tuple = ()
    if user_id is not None:
        query += " WHERE user_id = ?"
        params = (user_id,)
    query += " ORDER BY started_at DESC LIMIT ?"
    rows = connection.execute(query, (*params, limit)).fetchall()
    pause_rows = pauses if pauses is not None else _pause_map(connection)
    return [_session_payload(dict(row), pause_rows.get(row["id"], []), now) for row in rows]


def _focus_sessions(connection, now: datetime, pauses: dict[int, list[dict]] | None = None, user_id: int | None = None) -> list[tuple[str, datetime, datetime]]:
    query = "SELECT * FROM focus_sessions"
    params: tuple = ()
    if user_id is not None:
        query += " WHERE user_id = ?"
        params = (user_id,)
    rows = connection.execute(query + " ORDER BY started_at", params).fetchall()
    pause_rows = pauses if pauses is not None else _pause_map(connection)
    sessions = []
    for row in rows:
        for start, end in _session_segments(dict(row), pause_rows.get(row["id"], []), now):
            sessions.append((row["subject"], start, end))
    return sessions


def _today_focus_rows(connection, now: datetime, pauses: dict[int, list[dict]] | None = None, user_id: int | None = None) -> list[dict]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    if user_id is None:
        rows = connection.execute("SELECT * FROM focus_sessions ORDER BY started_at").fetchall()
    else:
        rows = connection.execute("SELECT * FROM focus_sessions WHERE user_id = ? ORDER BY started_at", (user_id,)).fetchall()
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


def _focus_day_metrics(focus_sessions: list[tuple[str, datetime, datetime]], day_start: datetime) -> tuple[int, dict[str, int]]:
    day_end = day_start + timedelta(days=1)
    subject_totals: dict[str, int] = {}
    for subject, start, end in focus_sessions:
        overlap_start = max(start.astimezone(day_start.tzinfo), day_start)
        overlap_end = min(end.astimezone(day_start.tzinfo), day_end)
        seconds = max(0, int((overlap_end - overlap_start).total_seconds()))
        if seconds:
            subject_totals[subject] = subject_totals.get(subject, 0) + seconds
    return sum(subject_totals.values()), subject_totals


def _viewer_user_id(connection) -> int | None:
    if is_guest() and session.get("profile_user_id") is not None:
        return int(session["profile_user_id"])
    user_id = current_user_id()
    if user_id is not None:
        return user_id
    if is_guest():
        row = connection.execute("SELECT id FROM users WHERE role = 'site_owner' ORDER BY id LIMIT 1").fetchone()
        return int(row["id"]) if row else None
    return None


def _friend_diff_payload(connection, now: datetime, user_id: int | None) -> list[dict]:
    if user_id is None or is_guest():
        return []
    pauses = _pause_map(connection)
    own_seconds = summarize_today_focus([(start, end) for _, start, end in _focus_sessions(connection, now, pauses, user_id)], now)["seconds"]
    result = []
    for friend in list_friends(connection, user_id):
        friend_seconds = summarize_today_focus([(start, end) for _, start, end in _focus_sessions(connection, now, pauses, friend["id"])], now)["seconds"]
        result.append({
            "id": friend["id"],
            "username": friend["username"],
            "today_seconds": friend_seconds,
            "delta_seconds": own_seconds - friend_seconds,
        })
    return result


def register_routes(app):
    @app.get("/")
    def dashboard():
        connection = connect(app.config["DATABASE"])
        try:
            users = list_public_users(connection)
        finally:
            connection.close()
        return render_template("site_home.html", page_name="site", users=users)

    @app.get("/guest", strict_slashes=False)
    def guest_dashboard():
        session.clear()
        session["authenticated"] = True
        session["role"] = "guest"
        session.pop("profile_user_id", None)
        return render_template("dashboard.html", page_name="home", is_guest=True)

    @app.get("/<username>/guest", strict_slashes=False)
    def profile_guest(username):
        connection = connect(app.config["DATABASE"])
        try:
            user = get_user_by_username(connection, username)
        finally:
            connection.close()
        if not user:
            abort(404)
        if not session.get("authenticated"):
            session.clear()
            session["authenticated"] = True
            session["role"] = "guest"
        session["viewing_as_guest"] = True
        session["profile_user_id"] = user["id"]
        session["profile_username"] = user["username"]
        return render_template("dashboard.html", page_name="home", is_guest=True, profile_user=user)

    @app.get("/<username>", strict_slashes=False)
    def user_dashboard(username):
        connection = connect(app.config["DATABASE"])
        try:
            user = get_user_by_username(connection, username)
        finally:
            connection.close()
        if not user:
            abort(404)
        if not session.get("authenticated") or is_guest() or session.get("username", "").casefold() != user["username"].casefold():
            return redirect(url_for("profile_guest", username=user["username"]))
        return render_template("dashboard.html", page_name="home", is_guest=False)

    @app.get("/focus")
    def focus_compatibility_redirect():
        if session.get("authenticated") and not is_guest() and session.get("username"):
            return redirect(url_for("user_dashboard", username=session["username"]))
        return redirect(url_for("dashboard"))

    @app.get("/account")
    @user_required
    def account_page():
        return render_template("settings.html", page_name="account", settings_tab="account", is_guest=False)

    @app.get("/settings")
    @user_required
    def settings_page():
        tab = request.args.get("tab", "system").strip().lower()
        if tab not in {"system", "account"}:
            tab = "system"
        return render_template("settings.html", page_name="settings", settings_tab=tab, is_guest=False)

    @app.get("/api/dashboard")
    @login_required
    def dashboard_api():
        connection = connect(app.config["DATABASE"])
        viewer_id = _viewer_user_id(connection)
        connection.execute("UPDATE focus_sessions SET last_foreground_at = ? WHERE status = 'active' AND user_id = ?", (_now("UTC").isoformat(), viewer_id))
        connection.commit()
        settings = get_settings(connection, viewer_id)
        now = _now(settings.get("timezone", "Asia/Shanghai"))
        try:
            windows = {
                "morning": calculate_window(now, settings["morning_start"], settings["lunch_start"]),
                "library": calculate_window(now, settings["library_open"], settings["library_close"]),
            }
            pauses = _pause_map(connection)
            active_row = connection.execute("SELECT * FROM focus_sessions WHERE status = 'active' AND user_id = ? ORDER BY id DESC LIMIT 1", (viewer_id,)).fetchone()
            settlement_date = now.date().isoformat()
            daily_settlement = get_daily_settlement(connection, viewer_id, settlement_date)
            focus_sessions = _focus_sessions(connection, now, pauses, viewer_id)
            sessions = [(start, end) for _, start, end in focus_sessions]
            today_rows = _today_focus_rows(connection, now, pauses, viewer_id)
            today_focus = summarize_today_focus(sessions, now)
            today_focus["count"] = len(today_rows)
            scores = score_metrics(list_latest_scores(connection, viewer_id))
            score_history = score_metrics(list_scores(connection, viewer_id))
            plans = list_plans(connection, viewer_id)
            try:
                heatmap_visible_hours = _heatmap_hours(settings.get("heatmap_visible_hours", ""))
            except (TypeError, ValueError):
                heatmap_visible_hours = list(HEATMAP_HOURS)
            return jsonify({
                "now": now.isoformat(),
                "exam": {"date": settings["exam_date"], "remaining_seconds": seconds_until_exam(now, settings["exam_date"])},
                "today_focus": today_focus,
                "focus_investment": aggregate_focus_investment(focus_sessions, now),
                "focus_leaderboard": focus_leaderboard(focus_sessions, now),
                "daily_settlement": daily_settlement,
                "can_settle_today": bool(
                    not is_guest()
                    and windows["library"]["state"] == "complete"
                    and active_row is None
                    and daily_settlement is None
                ),
                "windows": windows,
                "focus": {
                    "active": _session_payload(dict(active_row), pauses.get(active_row["id"], []), now) if active_row else None,
                    "recent": _focus_rows(connection, now, pauses=pauses, user_id=viewer_id),
                    "today": today_rows,
                },
                "focus_items": list_focus_items(connection, viewer_id) if viewer_id is not None else [],
                "focus_modes": list_focus_modes(connection, viewer_id),
                "subjects": list_subjects(connection, viewer_id) if viewer_id is not None else [],
                "focus_messages": get_focus_messages(connection, viewer_id),
                "heatmap": aggregate_focus_heatmap(sessions, now),
                "heatmap_visible_hours": heatmap_visible_hours,
                "scores": scores,
                "score_history": score_history,
                "plans": plans,
                "friends": _friend_diff_payload(connection, now, viewer_id),
                "viewer": get_user(connection, viewer_id),
            })
        finally:
            connection.close()

    @app.get("/api/focus")
    @login_required
    def focus_api():
        connection = connect(app.config["DATABASE"])
        try:
            now = _now("UTC")
            viewer_id = _viewer_user_id(connection)
            active = connection.execute("SELECT * FROM focus_sessions WHERE status = 'active' AND user_id = ? ORDER BY id DESC LIMIT 1", (viewer_id,)).fetchone()
            pauses = _pause_map(connection)
            return jsonify({
                "active": _session_payload(dict(active), pauses.get(active["id"], []), now) if active else None,
                "recent": _focus_rows(connection, now, pauses=pauses, user_id=viewer_id),
            })
        finally:
            connection.close()

    @app.post("/api/focus/start")
    @user_required
    def start_focus():
        payload = request.get_json(silent=True) or {}
        focus_item_id = payload.get("focus_item_id")
        legacy_focus_item = str(payload.get("focus_item", payload.get("subject", ""))).strip()
        mode = str(payload.get("mode", "")).strip()
        client_token = str(payload.get("client_token", "")).strip()
        try:
            planned_minutes = int(payload.get("planned_minutes", 0))
        except (TypeError, ValueError):
            planned_minutes = 0
        if planned_minutes < 0:
            return jsonify(error="planned_minutes_must_be_non_negative"), 400
        if focus_item_id is not None:
            try:
                focus_item_id = int(focus_item_id)
            except (TypeError, ValueError):
                return jsonify(error="focus_item_and_mode_required"), 400
        if focus_item_id is None and not legacy_focus_item:
            return jsonify(error="focus_item_and_mode_required"), 400
        if not mode:
            return jsonify(error="focus_item_and_mode_required"), 400
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            settings = get_settings(connection, current_user_id())
            local_date = _now(settings.get("timezone", "Asia/Shanghai")).date().isoformat()
            if get_daily_settlement(connection, current_user_id(), local_date):
                connection.rollback()
                return jsonify(error="daily_focus_already_settled"), 409
            if client_token:
                existing = connection.execute("SELECT * FROM focus_sessions WHERE client_token = ?", (client_token,)).fetchone()
                if existing:
                    connection.commit()
                    return jsonify(session=_row(connection, existing["id"]), idempotent=True), 200
            selected_item = (
                get_focus_item(connection, current_user_id(), focus_item_id)
                if focus_item_id is not None
                else get_focus_item_by_name(connection, current_user_id(), legacy_focus_item)
            )
            if not selected_item:
                connection.rollback()
                return jsonify(error="focus_item_not_found" if focus_item_id is not None else "subject_not_found"), 404
            subject_id = int(selected_item["subject_id"])
            subject = selected_item["label"]
            active = connection.execute("SELECT id FROM focus_sessions WHERE status = 'active' AND user_id = ? LIMIT 1", (current_user_id(),)).fetchone()
            if active:
                connection.rollback()
                return jsonify(error="focus_already_active"), 409
            started_at = _now("UTC").isoformat()
            cursor = connection.execute(
                "INSERT INTO focus_sessions(user_id, subject_id, focus_item_id, subject, mode, planned_minutes, started_at, status, client_token, last_foreground_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (current_user_id(), subject_id, focus_item_id, subject, mode, planned_minutes, started_at, client_token or None, started_at),
            )
            connection.commit()
            return jsonify(session=_row(connection, cursor.lastrowid)), 201
        finally:
            connection.close()

    @app.post("/api/daily-settlement")
    @user_required
    def settle_today():
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            user_id = current_user_id()
            settings = get_settings(connection, user_id)
            now = _now(settings.get("timezone", "Asia/Shanghai"))
            settlement_date = now.date().isoformat()
            existing = get_daily_settlement(connection, user_id, settlement_date)
            if existing:
                connection.commit()
                existing_sessions = _focus_sessions(connection, now, _pause_map(connection), user_id)
                return jsonify(settlement=existing, leaderboard=focus_leaderboard(existing_sessions, now), idempotent=True), 200
            library_window = calculate_window(now, settings["library_open"], settings["library_close"])
            active = connection.execute(
                "SELECT id FROM focus_sessions WHERE status = 'active' AND user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
            if library_window["state"] != "complete":
                connection.rollback()
                return jsonify(error="settlement_not_available"), 409
            if active:
                connection.rollback()
                return jsonify(error="focus_still_active"), 409
            pauses = _pause_map(connection)
            focus_sessions = _focus_sessions(connection, now, pauses, user_id)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_seconds, today_subject_totals = _focus_day_metrics(focus_sessions, today_start)
            yesterday_seconds, _ = _focus_day_metrics(focus_sessions, today_start - timedelta(days=1))
            today_rows = _today_focus_rows(connection, now, pauses, user_id)
            top_subject, top_subject_seconds = (None, 0)
            if today_subject_totals:
                top_subject, top_subject_seconds = sorted(
                    today_subject_totals.items(), key=lambda item: (-item[1], item[0])
                )[0]
            payload = {
                "user_id": user_id,
                "settlement_date": settlement_date,
                "settled_at": _now("UTC").isoformat(),
                "total_seconds": today_seconds,
                "yesterday_seconds": yesterday_seconds,
                "delta_seconds": today_seconds - yesterday_seconds,
                "target_seconds": DAILY_TARGET_SECONDS,
                "completion": round(today_seconds / DAILY_TARGET_SECONDS, 4),
                "session_count": len(today_rows),
                "top_subject": top_subject,
                "top_subject_seconds": top_subject_seconds,
            }
            cursor = connection.execute(
                """INSERT INTO daily_settlements(
                    user_id, settlement_date, settled_at, total_seconds, yesterday_seconds,
                    delta_seconds, target_seconds, completion, session_count,
                    top_subject, top_subject_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(payload[key] for key in (
                    "user_id", "settlement_date", "settled_at", "total_seconds", "yesterday_seconds",
                    "delta_seconds", "target_seconds", "completion", "session_count",
                    "top_subject", "top_subject_seconds",
                )),
            )
            connection.commit()
            payload["id"] = cursor.lastrowid
            return jsonify(settlement=payload, leaderboard=focus_leaderboard(focus_sessions, now)), 201
        except sqlite3.IntegrityError:
            connection.rollback()
            existing = get_daily_settlement(connection, current_user_id(), settlement_date)
            existing_sessions = _focus_sessions(connection, now, _pause_map(connection), current_user_id())
            return jsonify(settlement=existing, leaderboard=focus_leaderboard(existing_sessions, now), idempotent=True), 200
        finally:
            connection.close()

    @app.post("/api/focus/end")
    @user_required
    def end_focus():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            if session_id is None:
                row = connection.execute("SELECT id FROM focus_sessions WHERE status = 'active' AND user_id = ? ORDER BY id DESC LIMIT 1", (current_user_id(),)).fetchone()
                session_id = row["id"] if row else None
            row = connection.execute("SELECT * FROM focus_sessions WHERE id = ? AND user_id = ? AND status = 'active'", (session_id, current_user_id())).fetchone()
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
    @user_required
    def pause_focus():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        should_pause = payload.get("paused")
        if not isinstance(should_pause, bool):
            return jsonify(error="paused_boolean_required"), 400
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM focus_sessions WHERE id = ? AND user_id = ? AND status = 'active'", (session_id, current_user_id())).fetchone()
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
    @user_required
    def lock_focus():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        connection = connect(app.config["DATABASE"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT id FROM focus_sessions WHERE id = ? AND user_id = ? AND status = 'active'", (session_id, current_user_id())).fetchone()
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
        payload = request.get_json(silent=True) or {}
        try:
            session_id = int(payload["session_id"]) if payload.get("session_id") is not None else None
        except (TypeError, ValueError):
            return jsonify(error="invalid_session_id"), 400
        connection = connect(app.config["DATABASE"])
        try:
            return jsonify(record_foreground_heartbeat(
                connection,
                _now("UTC"),
                user_id=None if is_guest() else current_user_id(),
                session_id=session_id,
                allow_recovery=payload.get("allow_recovery") is True,
            ))
        finally:
            connection.close()

    @app.post("/api/migration/code")
    @admin_required
    def migration_code():
        connection = connect(app.config["DATABASE"])
        try:
            return jsonify(create_migration_code(connection, _now("UTC")))
        finally:
            connection.close()

    @app.get("/api/migration/export")
    def migration_export():
        code = request.headers.get("X-Migration-Code", "").strip()
        if not code:
            return jsonify(error="migration_code_required"), 401
        connection = connect(app.config["DATABASE"])
        try:
            now = _now("UTC")
            if not consume_migration_code(connection, code, now):
                return jsonify(error="invalid_or_expired_migration_code"), 401
            package = export_migration_data(connection, now)
            response = jsonify(package)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Disposition"] = 'attachment; filename="408-dashboard-migration.json"'
            return response
        finally:
            connection.close()

    @app.route("/api/subjects", methods=["GET", "POST"])
    @user_required
    def subjects_api():
        connection = connect(app.config["DATABASE"])
        try:
            user_id = current_user_id()
            if request.method == "POST":
                payload = request.get_json(silent=True) or {}
                try:
                    create_subject(connection, user_id, payload.get("name", ""), payload.get("target", 100))
                except ValueError as error:
                    return jsonify(error=str(error)), 400
                except sqlite3.IntegrityError:
                    return jsonify(error="duplicate_subject"), 409
                connection.commit()
            return jsonify(subjects=list_subjects(connection, user_id)), 201 if request.method == "POST" else 200
        finally:
            connection.close()

    @app.route("/api/subjects/<int:subject_id>", methods=["PATCH", "DELETE"])
    @user_required
    def subject_api(subject_id: int):
        connection = connect(app.config["DATABASE"])
        try:
            user_id = current_user_id()
            if request.method == "DELETE":
                if not delete_subject(connection, user_id, subject_id):
                    return jsonify(error="subject_not_found"), 404
                connection.commit()
                return jsonify(subjects=list_subjects(connection, user_id))
            existing = get_subject(connection, user_id, subject_id)
            if not existing:
                return jsonify(error="subject_not_found"), 404
            payload = request.get_json(silent=True) or {}
            try:
                update_subject(
                    connection,
                    user_id,
                    subject_id,
                    payload.get("name", existing["name"]),
                    payload.get("target", existing["target_score"]),
                )
            except ValueError as error:
                return jsonify(error=str(error)), 400
            except sqlite3.IntegrityError:
                return jsonify(error="duplicate_subject"), 409
            connection.commit()
            return jsonify(subjects=list_subjects(connection, user_id))
        finally:
            connection.close()

    @app.route("/api/focus-items", methods=["GET", "POST"])
    @user_required
    def focus_items_api():
        connection = connect(app.config["DATABASE"])
        try:
            user_id = current_user_id()
            if request.method == "POST":
                payload = request.get_json(silent=True) or {}
                try:
                    subject_id = int(payload.get("subject_id"))
                    create_focus_item(connection, user_id, subject_id, payload.get("name", ""))
                except (TypeError, ValueError) as error:
                    if str(error) == "subject_not_found":
                        return jsonify(error="subject_not_found"), 404
                    return jsonify(error=str(error)), 400
                except sqlite3.IntegrityError:
                    return jsonify(error="duplicate_focus_item"), 409
                connection.commit()
            return jsonify(focus_items=list_focus_items(connection, user_id)), 201 if request.method == "POST" else 200
        finally:
            connection.close()

    @app.route("/api/focus-items/<int:focus_item_id>", methods=["PATCH", "DELETE"])
    @user_required
    def focus_item_api(focus_item_id: int):
        connection = connect(app.config["DATABASE"])
        try:
            user_id = current_user_id()
            if request.method == "DELETE":
                if not delete_focus_item(connection, user_id, focus_item_id):
                    return jsonify(error="focus_item_not_found"), 404
                connection.commit()
                return jsonify(focus_items=list_focus_items(connection, user_id))
            existing = get_focus_item(connection, user_id, focus_item_id)
            if not existing:
                return jsonify(error="focus_item_not_found"), 404
            payload = request.get_json(silent=True) or {}
            try:
                subject_id = int(payload.get("subject_id", existing["subject_id"]))
                update_focus_item(
                    connection,
                    user_id,
                    focus_item_id,
                    subject_id,
                    payload.get("name", existing["name"]),
                )
            except (TypeError, ValueError) as error:
                if str(error) == "subject_not_found":
                    return jsonify(error="subject_not_found"), 404
                return jsonify(error=str(error)), 400
            except sqlite3.IntegrityError:
                return jsonify(error="duplicate_focus_item"), 409
            connection.commit()
            return jsonify(focus_items=list_focus_items(connection, user_id))
        finally:
            connection.close()

    @app.put("/api/focus-items/order")
    @user_required
    def focus_item_order_api():
        payload = request.get_json(silent=True) or {}
        focus_item_ids = payload.get("focus_item_ids")
        if not isinstance(focus_item_ids, list):
            return jsonify(error="invalid_focus_item_order"), 400
        connection = connect(app.config["DATABASE"])
        try:
            try:
                items = reorder_focus_items(connection, current_user_id(), focus_item_ids)
            except (TypeError, ValueError):
                return jsonify(error="invalid_focus_item_order"), 400
            connection.commit()
            return jsonify(focus_items=items)
        finally:
            connection.close()

    @app.route("/api/settings", methods=["GET", "PATCH"])
    @user_required
    def settings_api():
        connection = connect(app.config["DATABASE"])
        try:
            if request.method == "PATCH":
                payload = request.get_json(silent=True) or {}
                if "focus_subjects" in payload:
                    return jsonify(error="subject_crud_required"), 400
                try:
                    if "focus_messages" in payload:
                        save_focus_messages(connection, _focus_messages(payload["focus_messages"]), current_user_id())
                except ValueError as error:
                    return jsonify(error=str(error)), 400
                except sqlite3.IntegrityError:
                    return jsonify(error="duplicate_subject"), 409
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
                    connection.execute(
                        "INSERT INTO user_settings(user_id, key, value) VALUES (?, ?, ?) ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                        (current_user_id(), key, str(value)),
                    )
                connection.commit()
            user_id = current_user_id()
            return jsonify(
                settings=get_settings(connection, user_id),
                focus_items=list_focus_items(connection, user_id),
                focus_modes=list_focus_modes(connection, user_id),
                subjects=list_subjects(connection, user_id),
                focus_messages=get_focus_messages(connection, user_id),
            )
        finally:
            connection.close()

    @app.route("/api/invitations", methods=["GET", "POST"])
    @admin_required
    def invitations_api():
        connection = connect(app.config["DATABASE"])
        try:
            if request.method == "POST":
                owner_id = current_user_id()
                while True:
                    code = secrets.token_urlsafe(7).replace("-", "").replace("_", "")[:10].upper()
                    if not connection.execute("SELECT 1 FROM invitations WHERE code = ?", (code,)).fetchone():
                        break
                issue_invitation(connection, owner_id, code, _now("UTC").isoformat())
                connection.commit()
            invitations = list_invitations(connection, current_user_id())
            for invitation in invitations:
                invitation["url"] = url_for("register", code=invitation["code"], _external=True)
            return jsonify(invitations=invitations)
        finally:
            connection.close()

    @app.get("/api/friends/search")
    @user_required
    def search_friends():
        query = request.args.get("q", "").strip()
        if len(query) < 1:
            return jsonify(users=[])
        connection = connect(app.config["DATABASE"])
        try:
            users = connection.execute(
                "SELECT id, username FROM users WHERE id != ? AND username LIKE ? COLLATE NOCASE ORDER BY username COLLATE NOCASE LIMIT 10",
                (current_user_id(), f"%{query}%"),
            ).fetchall()
            friend_ids = {row["id"] for row in list_friends(connection, current_user_id())}
            return jsonify(users=[{"id": row["id"], "username": row["username"], "is_friend": row["id"] in friend_ids} for row in users])
        finally:
            connection.close()

    @app.route("/api/friends", methods=["GET", "POST"])
    @user_required
    def friends_api():
        connection = connect(app.config["DATABASE"])
        try:
            if request.method == "POST":
                payload = request.get_json(silent=True) or {}
                friend = get_user_by_username(connection, str(payload.get("username", "")).strip())
                if not friend:
                    return jsonify(error="user_not_found"), 404
                try:
                    add_friend(connection, current_user_id(), friend["id"], _now("UTC").isoformat())
                except ValueError as error:
                    return jsonify(error=str(error)), 400
                except sqlite3.IntegrityError:
                    return jsonify(error="already_friend"), 409
                connection.commit()
            friends = list_friends(connection, current_user_id())
            return jsonify(friends=friends)
        finally:
            connection.close()

    @app.delete("/api/friends/<username>")
    @user_required
    def delete_friend(username):
        connection = connect(app.config["DATABASE"])
        try:
            friend = get_user_by_username(connection, username)
            if not friend:
                return jsonify(error="user_not_found"), 404
            remove_friend(connection, current_user_id(), friend["id"])
            connection.commit()
            return jsonify(ok=True)
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
                except (KeyError, TypeError, ValueError):
                    return jsonify(error="invalid_score_payload"), 400
                subject_id = payload.get("subject_id")
                subject = str(payload.get("subject", "")).strip()
                if subject_id is not None:
                    try:
                        selected_subject = get_subject(connection, current_user_id(), int(subject_id))
                    except (TypeError, ValueError):
                        selected_subject = None
                    if not selected_subject:
                        return jsonify(error="subject_not_found"), 404
                    subject_id = int(selected_subject["id"])
                    subject = selected_subject["name"]
                    target = float(selected_subject["target_score"])
                else:
                    selected_subject = get_subject_by_name(connection, current_user_id(), subject) if subject else None
                    if not selected_subject:
                        return jsonify(error="subject_not_found"), 404
                    subject_id = int(selected_subject["id"])
                    subject = selected_subject["name"]
                    target = float(selected_subject["target_score"])
                # The paper-tape UI intentionally exposes 000–199, but the
                # endpoint remains compatible with existing clients and
                # historical score scales that can exceed 199.
                if not subject or score < 0 or target <= 0:
                    return jsonify(error="invalid_score_payload"), 400
                settings = get_settings(connection, current_user_id())
                exam_date = payload.get("exam_date") or _now(settings.get("timezone", "Asia/Shanghai")).date().isoformat()
                connection.execute(
                    "INSERT INTO scores(user_id, subject_id, subject, exam_date, score, target) VALUES (?, ?, ?, ?, ?, ?)",
                    (current_user_id(), subject_id, subject, exam_date, score, target),
                )
                connection.commit()
            return jsonify(scores=score_metrics(list_latest_scores(connection, current_user_id())))
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
                subject_id = payload.get("subject_id")
                subject = str(payload.get("subject", "")).strip()
                if subject_id is not None:
                    try:
                        selected_subject = get_subject(connection, current_user_id(), int(subject_id))
                    except (TypeError, ValueError):
                        selected_subject = None
                    if not selected_subject:
                        return jsonify(error="subject_not_found"), 404
                    subject_id = int(selected_subject["id"])
                    subject = selected_subject["name"]
                elif subject:
                    selected_subject = get_subject_by_name(connection, current_user_id(), subject)
                    if not selected_subject:
                        return jsonify(error="subject_not_found"), 404
                    subject_id = int(selected_subject["id"])
                    subject = selected_subject["name"]
                if not payload.get("week_start") or not subject or not payload.get("title") or target_minutes <= 0 or completed_minutes < 0:
                    return jsonify(error="invalid_plan_payload"), 400
                connection.execute("INSERT INTO plans(user_id, subject_id, week_start, subject, title, target_minutes, completed_minutes) VALUES (?, ?, ?, ?, ?, ?, ?)", (current_user_id(), subject_id, payload["week_start"], subject, payload["title"], target_minutes, completed_minutes))
                connection.commit()
            return jsonify(plans=list_plans(connection, current_user_id()))
        finally:
            connection.close()
