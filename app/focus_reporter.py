"""Small authenticated heartbeat protocol for external study applications."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import REPORTER_HEARTBEAT_TIMEOUT_SECONDS, finish_focus_session, get_daily_settlement, get_focus_item, get_settings


REPORT_BASE_URL = "https://platform.arcol.site"
SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
KEY_PATTERN = re.compile(r"^([1-9][0-9]{0,17})\.([0-9a-f]{64})$")


class ReporterError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _legacy_token(user_id: int, nonce: str, secret_key: str) -> str:
    message = f"focus-reporter-v1:{user_id}:{nonce}".encode("utf-8")
    digest = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{user_id}.{digest}"


def materialize_legacy_reporter_keys(connection: sqlite3.Connection, secret_key: str) -> int:
    """Persist issued v1 keys before a later app-secret rotation can change them."""

    if connection.execute("SELECT 1 FROM focus_reporter_keys WHERE token IS NULL LIMIT 1").fetchone() is None:
        return 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        rows = connection.execute(
            "SELECT user_id, nonce FROM focus_reporter_keys WHERE token IS NULL"
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE focus_reporter_keys SET token = ? WHERE user_id = ? AND token IS NULL",
                (_legacy_token(int(row["user_id"]), row["nonce"], secret_key), row["user_id"]),
            )
        connection.commit()
        return len(rows)
    except Exception:
        connection.rollback()
        raise


def connection_details(connection: sqlite3.Connection, user_id: int, secret_key: str, *, rotate: bool = False) -> dict[str, str]:
    """Issue a durable link; only explicit rotation invalidates the old key."""

    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute("SELECT nonce, token FROM focus_reporter_keys WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or rotate:
            nonce = secrets.token_urlsafe(24)
            token = f"{user_id}.{secrets.token_hex(32)}"
            connection.execute(
                "INSERT INTO focus_reporter_keys(user_id, nonce, created_at, token) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET nonce = excluded.nonce, created_at = excluded.created_at, token = excluded.token",
                (user_id, nonce, datetime.now(timezone.utc).isoformat(), token),
            )
        else:
            token = row["token"]
            if token is None:
                token = _legacy_token(user_id, row["nonce"], secret_key)
                connection.execute("UPDATE focus_reporter_keys SET token = ? WHERE user_id = ?", (token, user_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    base = f"{REPORT_BASE_URL}/api/focus-reporter/{token}"
    return {"report_url": f"{base}/frame", "catalog_url": f"{base}/catalog"}


def authenticate_reporter(connection: sqlite3.Connection, key: str, secret_key: str) -> int | None:
    match = KEY_PATTERN.fullmatch(key)
    if not match:
        return None
    user_id = int(match.group(1))
    row = connection.execute("SELECT nonce, token FROM focus_reporter_keys WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    expected = row["token"] or _legacy_token(user_id, row["nonce"], secret_key)
    return user_id if hmac.compare_digest(expected, key) else None


def _positive_id(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def apply_frame(connection: sqlite3.Connection, user_id: int, payload: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Apply one server-time state snapshot without counting duplicate frames twice."""

    source = payload.get("source")
    state = payload.get("state")
    if not isinstance(source, str) or not SOURCE_PATTERN.fullmatch(source):
        raise ReporterError("invalid_source")
    if state not in ("focus", "idle"):
        raise ReporterError("invalid_state")
    subject_id = _positive_id(payload.get("subject_id")) if state == "focus" else None
    item_id = _positive_id(payload.get("focus_item_id")) if state == "focus" else None
    if state == "focus" and (subject_id is None or item_id is None):
        raise ReporterError("subject_and_focus_item_required")

    now_utc = now.astimezone(timezone.utc)
    now_value = now_utc.isoformat()
    connection.execute("BEGIN IMMEDIATE")
    try:
        active = connection.execute(
            "SELECT id, reporter_source, focus_item_id, last_foreground_at FROM focus_sessions "
            "WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        stale_closed = False
        if active and active["reporter_source"]:
            last_seen = datetime.fromisoformat(active["last_foreground_at"]).astimezone(timezone.utc)
            if now_utc - last_seen > timedelta(seconds=REPORTER_HEARTBEAT_TIMEOUT_SECONDS):
                ended_at = (last_seen + timedelta(seconds=REPORTER_HEARTBEAT_TIMEOUT_SECONDS)).isoformat()
                finish_focus_session(connection, active["id"], ended_at, "reporter_timeout")
                active = None
                stale_closed = True

        if state == "idle":
            ended_session_id = None
            if active and active["reporter_source"] == source:
                ended_session_id = int(active["id"])
                finish_focus_session(connection, ended_session_id, now_value, "reporter_idle")
            connection.commit()
            return {"ok": True, "state": "idle", "session_id": ended_session_id, "changed": stale_closed or ended_session_id is not None, "accepted_at": now_value}

        selected = get_focus_item(connection, user_id, item_id)
        if not selected or int(selected["subject_id"]) != subject_id:
            raise ReporterError("focus_item_not_found", 404)
        settings = get_settings(connection, user_id)
        try:
            local_day = now_utc.astimezone(ZoneInfo(settings.get("timezone", "Asia/Shanghai"))).date().isoformat()
        except ZoneInfoNotFoundError:
            local_day = now_utc.date().isoformat()
        if get_daily_settlement(connection, user_id, local_day):
            raise ReporterError("daily_focus_already_settled", 409)
        if active and active["reporter_source"] != source:
            raise ReporterError("focus_already_active", 409)

        if active and int(active["focus_item_id"] or 0) == item_id:
            session_id = int(active["id"])
            connection.execute("UPDATE focus_sessions SET last_foreground_at = ? WHERE id = ?", (now_value, session_id))
            connection.execute("UPDATE focus_pauses SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL", (now_value, session_id))
        else:
            if active:
                finish_focus_session(connection, int(active["id"]), now_value, "reporter_item_changed")
            cursor = connection.execute(
                "INSERT INTO focus_sessions(user_id, subject_id, focus_item_id, subject, mode, planned_minutes, "
                "started_at, status, last_foreground_at, reporter_source) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, 'active', ?, ?)",
                (user_id, subject_id, item_id, selected["label"], selected["name"], now_value, now_value, source),
            )
            session_id = int(cursor.lastrowid)
        connection.commit()
        return {
            "ok": True,
            "state": "focus",
            "session_id": session_id,
            "changed": True,
            "accepted_at": now_value,
            "timeout_seconds": REPORTER_HEARTBEAT_TIMEOUT_SECONDS,
        }
    except Exception:
        connection.rollback()
        raise
