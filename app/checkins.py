"""Daily check-ins: server-time conditions, account scope and durable external keys."""
from __future__ import annotations

import hmac
import math
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, request

from .auth import current_user_id, user_required
from .db import connect, get_settings
from .focus_reporter import KEY_PATTERN, SOURCE_PATTERN, REPORT_BASE_URL, ReporterError
from .services import current_time

TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def account_now(connection, user_id, now):
    return now.astimezone(ZoneInfo(get_settings(connection, user_id).get("timezone", "Asia/Shanghai")))


def number(value, low, high, code):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ReporterError(code)
    return float(value)


def validate_rule(payload):
    name = payload.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
        raise ReporterError("invalid_checkin_name")
    start, end = payload.get("time_start"), payload.get("time_end")
    if start is not None or end is not None:
        if not isinstance(start, str) or not isinstance(end, str) or not TIME_PATTERN.fullmatch(start) or not TIME_PATTERN.fullmatch(end) or start == end:
            raise ReporterError("invalid_checkin_time_window")
    lat, lon = payload.get("latitude"), payload.get("longitude")
    if lat is not None or lon is not None:
        lat = number(lat, -90, 90, "invalid_checkin_location")
        lon = number(lon, -180, 180, "invalid_checkin_location")
    radius = payload.get("radius_meters", 200)
    if type(radius) is not int or not 50 <= radius <= 10000:
        raise ReporterError("invalid_checkin_radius")
    label = payload.get("place_label", "")
    if not isinstance(label, str) or len(label) > 60:
        raise ReporterError("invalid_checkin_place_label")
    return (name.strip(), start, end, label.strip(), lat, lon, radius)


def catalog(connection, user_id, now):
    day = account_now(connection, user_id, now).date().isoformat()
    rows = connection.execute("""SELECT r.*, c.accepted_at AS completed_at FROM checkin_rules r
        LEFT JOIN checkin_records c ON c.rule_id=r.id AND c.user_id=r.user_id AND c.local_day=?
        WHERE r.user_id=? AND r.archived_at IS NULL ORDER BY r.id""", (day, user_id)).fetchall()
    return {"date": day, "timezone": get_settings(connection, user_id).get("timezone", "Asia/Shanghai"),
            "checkin_items": [dict(row) for row in rows]}


def heatmap(connection, user_id, now, day_count):
    first = now.date() - timedelta(days=day_count - 1)
    rules = connection.execute("SELECT id,created_day,archived_day FROM checkin_rules WHERE user_id=?", (user_id,)).fetchall()
    completed = {}
    for row in connection.execute("SELECT local_day,rule_id FROM checkin_records WHERE user_id=? AND local_day>=?", (user_id, first.isoformat())):
        completed.setdefault(row["local_day"], set()).add(row["rule_id"])
    result = []
    for index in range(day_count):
        day = (first + timedelta(days=index)).isoformat()
        done = completed.get(day, set())
        # Archived tasks leave future targets; saved accomplishments stay visible.
        eligible = {r["id"] for r in rules if r["created_day"] <= day and (not r["archived_day"] or day < r["archived_day"])} | done
        total = len(eligible)
        result.append({"date": day, "completed": len(done), "total": total,
                       "completion": len(done) / total if total else None})
    return result


def apply_frame(connection, user_id, payload, now):
    source = payload.get("source", "app")
    if not isinstance(source, str) or not SOURCE_PATTERN.fullmatch(source):
        raise ReporterError("invalid_source")
    state = payload.get("state", "checkin")
    if state not in ("checkin", "idle"):
        raise ReporterError("invalid_state")
    if state == "idle":
        return {"ok": True, "state": "idle", "changed": False, "accepted_at": now.isoformat()}
    rule_id = payload.get("checkin_item_id")
    if type(rule_id) is not int or rule_id <= 0:
        raise ReporterError("checkin_item_required")
    local = account_now(connection, user_id, now)
    day = local.date().isoformat()
    connection.execute("BEGIN IMMEDIATE")
    try:
        rule = connection.execute("SELECT * FROM checkin_rules WHERE id=? AND user_id=? AND archived_at IS NULL", (rule_id, user_id)).fetchone()
        if not rule:
            raise ReporterError("checkin_item_not_found", 404)
        existing = connection.execute("SELECT * FROM checkin_records WHERE user_id=? AND rule_id=? AND local_day=?", (user_id, rule_id, day)).fetchone()
        if existing:
            connection.commit()
            return {"ok": True, "state": "checkin", "changed": False, "record_id": existing["id"],
                    "date": day, "accepted_at": existing["accepted_at"]}
        if rule["time_start"]:
            current = local.strftime("%H:%M")
            start, end = rule["time_start"], rule["time_end"]
            in_window = start <= current < end if start < end else current >= start or current < end
            if not in_window:
                raise ReporterError("checkin_outside_time_window", 409)
        if rule["latitude"] is not None:
            lat = number(payload.get("latitude"), -90, 90, "checkin_location_required")
            lon = number(payload.get("longitude"), -180, 180, "checkin_location_required")
            accuracy = number(payload.get("accuracy"), 0, 100000, "checkin_location_accuracy_required")
            if accuracy > rule["radius_meters"]:
                raise ReporterError("checkin_location_too_inaccurate", 409)
            lat1, lat2 = math.radians(rule["latitude"]), math.radians(lat)
            a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(lon-rule["longitude"])/2)**2
            distance = 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, a))))
            if distance > rule["radius_meters"]:
                raise ReporterError("checkin_outside_location", 409)
        accepted = now.astimezone(timezone.utc).isoformat()
        cursor = connection.execute("INSERT INTO checkin_records(user_id,rule_id,local_day,accepted_at,source) VALUES (?,?,?,?,?)",
                                    (user_id, rule_id, day, accepted, source))
        connection.commit()
        return {"ok": True, "state": "checkin", "changed": True, "record_id": cursor.lastrowid,
                "date": day, "accepted_at": accepted}
    except Exception:
        connection.rollback()
        raise


def connection_details(connection, user_id, rotate=False):
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute("SELECT token FROM checkin_reporter_keys WHERE user_id=?", (user_id,)).fetchone()
        if row is None or rotate:
            token = f"{user_id}.{secrets.token_hex(32)}"
            connection.execute("INSERT INTO checkin_reporter_keys(user_id,token,created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET token=excluded.token,created_at=excluded.created_at",
                               (user_id, token, datetime.now(timezone.utc).isoformat()))
        else:
            token = row["token"]
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    base = f"{REPORT_BASE_URL}/api/checkin-reporter/{token}"
    return {"report_url": f"{base}/frame", "catalog_url": f"{base}/catalog"}


def authenticate(connection, key):
    match = KEY_PATTERN.fullmatch(key)
    if not match:
        return None
    row = connection.execute("SELECT token FROM checkin_reporter_keys WHERE user_id=?", (int(match[1]),)).fetchone()
    return int(match[1]) if row and hmac.compare_digest(row["token"], key) else None


def register_checkins(app):
    def run(callback):
        connection = connect(app.config["DATABASE"])
        try:
            return callback(connection)
        except ReporterError as error:
            return jsonify(error=error.code), error.status
        finally:
            connection.close()

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ReporterError("invalid_json")
        return data

    @app.get("/api/checkins")
    @user_required
    def checkin_catalog():
        return run(lambda conn: jsonify(catalog(conn, current_user_id(), current_time("UTC"))))

    @app.post("/api/checkins")
    @user_required
    def checkin_create():
        def create(conn):
            values = validate_rule(payload())
            user = current_user_id()
            now = current_time("UTC")
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT count(*) FROM checkin_rules WHERE user_id=? AND archived_at IS NULL", (user,)).fetchone()[0] >= 50:
                raise ReporterError("too_many_checkin_items", 409)
            cursor = conn.execute("INSERT INTO checkin_rules(user_id,name,time_start,time_end,place_label,latitude,longitude,radius_meters,created_at,created_day) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                  (user, *values, now.isoformat(), account_now(conn, user, now).date().isoformat()))
            conn.commit()
            return jsonify(id=cursor.lastrowid), 201
        return run(create)

    @app.get("/api/checkins/history")
    @user_required
    def checkin_history():
        def read(conn):
            try:
                day = date.fromisoformat(request.args.get("date", "")).isoformat()
            except ValueError:
                raise ReporterError("invalid_date")
            user = current_user_id()
            zone = account_now(conn, user, current_time("UTC")).tzinfo
            rows = conn.execute("SELECT r.name,c.accepted_at,c.source FROM checkin_records c JOIN checkin_rules r ON r.id=c.rule_id WHERE c.user_id=? AND c.local_day=? ORDER BY c.id", (user, day)).fetchall()
            return jsonify(records=[dict(row, time=datetime.fromisoformat(row["accepted_at"]).astimezone(zone).strftime("%H:%M")) for row in rows])
        return run(read)

    @app.route("/api/checkins/<int:item_id>", methods=["PUT", "DELETE"])
    @user_required
    def checkin_edit(item_id):
        def edit(conn):
            user = current_user_id()
            values = validate_rule(payload()) if request.method == "PUT" else None
            now = current_time("UTC")
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT id FROM checkin_rules WHERE id=? AND user_id=? AND archived_at IS NULL", (item_id, user)).fetchone():
                raise ReporterError("checkin_item_not_found", 404)
            if values:
                conn.execute("UPDATE checkin_rules SET name=?,time_start=?,time_end=?,place_label=?,latitude=?,longitude=?,radius_meters=? WHERE id=? AND user_id=?", (*values, item_id, user))
            else:
                conn.execute("UPDATE checkin_rules SET archived_at=?,archived_day=? WHERE id=? AND user_id=?", (now.isoformat(), account_now(conn, user, now).date().isoformat(), item_id, user))
            conn.commit()
            return jsonify(ok=True)
        return run(edit)

    @app.post("/api/checkins/frame")
    @user_required
    def checkin_trigger():
        return run(lambda conn: jsonify(apply_frame(conn, current_user_id(), payload(), current_time("UTC"))))

    @app.post("/api/checkin-reporter/connection")
    @app.post("/api/checkin-reporter/connection/rotate")
    @user_required
    def checkin_connection():
        return run(lambda conn: jsonify(connection_details(conn, current_user_id(), request.path.endswith("/rotate"))))

    @app.get("/api/checkin-reporter/<key>/catalog")
    def checkin_external_catalog(key):
        def read(conn):
            user = authenticate(conn, key)
            if user is None:
                raise ReporterError("invalid_reporter_key", 401)
            return jsonify(catalog(conn, user, current_time("UTC")))
        return run(read)

    @app.post("/api/checkin-reporter/<key>/frame")
    def checkin_external_frame(key):
        def report(conn):
            user = authenticate(conn, key)
            if user is None:
                raise ReporterError("invalid_reporter_key", 401)
            data = payload()
            if "source" not in data or "state" not in data:
                raise ReporterError("source_and_state_required")
            return jsonify(apply_frame(conn, user, data, current_time("UTC")))
        return run(report)
