"""Local emulator service with an explicitly isolated .tmp SQLite database.

Never import this module into production. Test control routes exist only here.
"""
from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
import json
from pathlib import Path
import ssl
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPSHandler, HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = (ROOT / ".tmp").resolve()
sys.path.insert(0, str(ROOT))

from flask import jsonify, request
from werkzeug.security import generate_password_hash
from app import create_app
from app.auth import current_user_id, user_required
from app.db import connect, create_user, finish_focus_session, list_focus_items, list_subjects
from app.routes import _row

PASSWORD = "Emulator-only-2026"
SCENARIOS = ("idle", "focusing", "paused", "paused5min", "ended", "ended15min", "ended30min", "ended60min", "rest")
LOOPBACK_HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))


def loopback_host(raw):
    if str(raw).lower() not in LOOPBACK_HOSTS:
        raise ValueError("Fixture host must be localhost, 127.0.0.1 or ::1")
    return str(raw).lower()


def loopback_url(raw):
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https") or parsed.username is not None or parsed.password is not None:
        raise ValueError("Fixture URL must use HTTP(S) and a loopback host without credentials")
    loopback_host(parsed.hostname)
    # Accessing port also rejects malformed/non-numeric ports before networking.
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid fixture URL port")
    return raw


class LoopbackRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        loopback_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def isolated_database(raw):
    candidate = Path(raw).resolve()
    if candidate.parent != TEMP_ROOT or candidate.suffix != ".sqlite3":
        raise ValueError("Fixture DATABASE must be a .sqlite3 file inside this repository's .tmp directory")
    return candidate


def seed(app):
    connection = connect(app.config["DATABASE"])
    try:
        now = datetime.now(timezone.utc)
        if not connection.execute("SELECT id FROM users WHERE username = 'androidviewer'").fetchone():
            create_user(connection, "androidviewer", "androidviewer@example.invalid", generate_password_hash(PASSWORD), now.isoformat())
        users = connection.execute("SELECT id, username FROM users WHERE username IN ('androidowner','androidviewer')").fetchall()
        for user in users:
            if connection.execute("SELECT 1 FROM focus_sessions WHERE user_id = ?", (user["id"],)).fetchone():
                continue
            items = list_focus_items(connection, user["id"])
            local = now.astimezone(ZoneInfo("Asia/Shanghai"))
            for days_ago in range(28, 0, -1):
                for index in range(3):
                    item = items[(days_ago + index) % len(items)]
                    started = (local - timedelta(days=days_ago)).replace(hour=8 + index * 3, minute=15, second=0, microsecond=0)
                    ended = started + timedelta(minutes=45 + (days_ago * 17 + index * 13) % 100)
                    cursor = connection.execute("""INSERT INTO focus_sessions
                        (user_id,subject_id,focus_item_id,subject,mode,planned_minutes,started_at,ended_at,status,last_foreground_at,ended_reason)
                        VALUES (?,?,?,?,? ,0,?,?,'completed',?,'manual')""",
                        (user["id"], item["subject_id"], item["id"], item["label"], "专注", started.isoformat(), ended.isoformat(), ended.isoformat()))
                    if index == 1:
                        connection.execute("INSERT INTO focus_pauses(session_id,started_at,ended_at) VALUES (?,?,?)",
                                           (cursor.lastrowid, (started + timedelta(minutes=10)).isoformat(), (started + timedelta(minutes=15)).isoformat()))
            for subject in list_subjects(connection, user["id"]):
                for days_ago, score in ((14, 65), (7, 76), (1, 82)):
                    connection.execute("INSERT INTO scores(user_id,subject_id,subject,exam_date,score,target) VALUES (?,?,?,?,?,?)",
                                       (user["id"], subject["id"], subject["name"], (local - timedelta(days=days_ago)).date().isoformat(), score, subject.get("target", 100)))
        connection.commit()
    finally:
        connection.close()


def construct_scenario(app, user_id, name, seconds_before, base_url):
    if name not in SCENARIOS or not -3600 <= seconds_before <= 3600:
        raise ValueError("Invalid test scenario or boundary offset")
    connection = connect(app.config["DATABASE"])
    try:
        now = datetime.now(timezone.utc)
        for row in connection.execute("SELECT id FROM focus_sessions WHERE user_id=? AND status='active'", (user_id,)).fetchall():
            finish_focus_session(connection, row["id"], now.isoformat())
        # Fixture changes only this user's test sessions/settlement, never preferences or artwork.
        today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        connection.execute("DELETE FROM daily_settlements WHERE user_id=? AND settlement_date=?", (user_id, today))
        item = list_focus_items(connection, user_id)[0]
        mode = "idle" if name == "idle" else "rest" if name == "rest" else "ended" if name.startswith("ended") else "paused" if name.startswith("paused") else "focusing"
        session_id = 0
        paused_at = ended_at = None
        due = None
        if mode not in ("idle", "rest"):
            age_minutes = {"paused5min": 5, "ended15min": 15, "ended30min": 30, "ended60min": 60}.get(name, 0)
            age = timedelta(minutes=age_minutes) - timedelta(seconds=seconds_before) if age_minutes else timedelta(0)
            boundary_time = now - age
            started = boundary_time - timedelta(minutes=30) if mode in ("paused", "ended") else now - timedelta(minutes=30)
            cursor = connection.execute("""INSERT INTO focus_sessions
                (user_id,subject_id,focus_item_id,subject,mode,planned_minutes,started_at,status,last_foreground_at)
                VALUES (?,?,?,?,?,0,?,'active',?)""", (user_id, item["subject_id"], item["id"], item["label"], "专注", started.isoformat(), now.isoformat()))
            session_id = cursor.lastrowid
            if mode == "paused":
                paused_at = boundary_time
                connection.execute("INSERT INTO focus_pauses(session_id,started_at) VALUES (?,?)", (session_id, paused_at.isoformat()))
                connection.execute("UPDATE focus_sessions SET interruption_count=1 WHERE id=?", (session_id,))
                due = paused_at + timedelta(minutes=5)
            elif mode == "ended":
                ended_at = boundary_time
                finish_focus_session(connection, session_id, ended_at.isoformat(), "manual")
                due = ended_at + timedelta(minutes=age_minutes or 15)
        connection.commit()
        payload = _row(connection, session_id, now) if session_id else None
        username = connection.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()["username"]
        native = {"mode": mode, "sessionId": session_id, "subject": item["label"] if session_id else "",
                  "startedAtEpochMs": int(datetime.fromisoformat(payload["started_at"]).timestamp() * 1000) if payload else 0,
                  "pausedAtEpochMs": int(paused_at.timestamp() * 1000) if paused_at else 0,
                  "endedAtEpochMs": int(ended_at.timestamp() * 1000) if ended_at else 0,
                  "elapsedSeconds": payload["effective_seconds"] if payload else 0,
                  "pageUrl": f"{base_url.rstrip('/')}/{username}", "baseUrl": base_url.rstrip("/")}
        return {"scenario": name, "session": payload, "native_state": native,
                "reminder_due_at": due.isoformat() if due else None,
                "seconds_until_boundary": seconds_before if name.endswith("min") else None,
                "database": app.config["DATABASE"],
                "note": "ENDED_30/60 follow earlier reminders: acknowledge 15/30 first. REST is client/native state only; paused sessions remain status=active."}
    finally:
        connection.close()


def fixture_app(database, testing=False):
    database = isolated_database(database)
    app = create_app({"TESTING": testing, "DATABASE": str(database), "SECRET_KEY": "isolated-android-fixture-only",
                      "ADMIN_USERNAME": "androidowner", "ADMIN_EMAIL": "androidowner@example.invalid",
                      "ADMIN_PASSWORD": PASSWORD, "COOKIE_SECURE": False,
                      "FOREGROUND_TIMEOUT_SECONDS": 30, "FOREGROUND_MONITOR_INTERVAL": 0.5})
    seed(app)

    @app.get("/_test/info")
    def info():
        return jsonify(database=str(database), isolated=True, monitor_enabled=not testing,
                       accounts=["androidowner", "androidviewer"], password=PASSWORD, scenarios=SCENARIOS)

    @app.post("/api/_test/scenario")
    @user_required
    def scenario():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="invalid_fixture_payload"), 400
        try:
            return jsonify(construct_scenario(app, current_user_id(), str(payload.get("scenario", "idle")),
                                              float(payload.get("seconds_before", -2)), request.host_url.rstrip("/")))
        except (ValueError, TypeError):
            return jsonify(error="invalid_fixture_scenario"), 400

    return app


def selfcheck(database):
    for invalid in ("0.0.0.0", "192.168.1.2", "example.com", "localhost.example.com"):
        try:
            loopback_host(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Non-loopback host accepted")
    for valid in ("http://localhost:43129", "https://127.0.0.1:43128", "https://[::1]:43128"):
        assert loopback_url(valid) == valid
    for invalid in ("file:///tmp/test", "https://example.com", "http://localhost.example.com", "http://user@localhost", "http://localhost:bad"):
        try:
            loopback_url(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe scenario URL accepted")
    for invalid in (ROOT / "data" / "fixture.sqlite3", TEMP_ROOT / "nested" / "fixture.sqlite3", TEMP_ROOT / "fixture.db"):
        try:
            isolated_database(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Non-isolated database accepted")
    app = fixture_app(database, testing=True)
    client = app.test_client()
    assert client.post("/login", data={"identifier": "androidowner", "password": PASSWORD}).status_code == 302
    items = client.get("/api/dashboard").get_json()["focus_items"]
    assert client.post("/api/_test/scenario", json={"scenario": "idle"}).status_code == 200
    started = client.post("/api/focus/start", json={"focus_item_id": items[0]["id"], "mode": "专注"})
    assert started.status_code == 201
    session_id = started.get_json()["session"]["id"]
    for paused in (True, False):
        response = client.post("/api/focus/pause", json={"session_id": session_id, "paused": paused})
        assert response.status_code == 200
        assert bool(response.get_json()["session"]["paused_at"]) == paused
    ended = client.post("/api/focus/end", json={"session_id": session_id})
    assert ended.status_code == 200 and ended.get_json()["session"]["ended_reason"] == "manual"
    for name in SCENARIOS:
        response = client.post("/api/_test/scenario", json={"scenario": name})
        assert response.status_code == 200
        data = response.get_json()
        if name.startswith("paused"):
            assert data["session"]["status"] == "active" and data["session"]["paused_at"]
            assert data["session"]["effective_seconds"] == 1800
        if name.startswith("ended"):
            assert data["session"]["status"] == "completed" and data["session"]["ended_reason"] == "manual"
            assert data["session"]["effective_seconds"] == 1800
            assert data["native_state"]["endedAtEpochMs"] == int(datetime.fromisoformat(data["session"]["ended_at"]).timestamp() * 1000)
    client.get("/androidowner/guest")
    assert client.post("/api/_test/scenario", json={"scenario": "idle"}).status_code == 403
    assert app.test_client().post("/api/_test/scenario", json={"scenario": "idle"}).status_code == 401
    assert not fixture_app(database, testing=True).config["DATABASE"].startswith(str(ROOT / "data"))
    production = create_app({"TESTING": True, "DATABASE": str(isolated_database(database)), "SECRET_KEY": "fixture-route-check-only"})
    assert not any("_test" in rule.rule for rule in production.url_map.iter_rules())
    print("Fixture selfcheck passed: loopback/URL/DB isolation, no production test routes, real login/start/pause/resume/end, 9 accelerated states, guest/anonymous controls denied.")


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "init", "selfcheck", "scenario"))
    parser.add_argument("--db", default=str(TEMP_ROOT / "android-emulator-test.sqlite3"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=43129)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--url", default="http://127.0.0.1:43129")
    parser.add_argument("--user", choices=("androidowner", "androidviewer"), default="androidowner")
    parser.add_argument("--scenario", choices=SCENARIOS, default="idle")
    parser.add_argument("--seconds-before", type=float, default=-2)
    parser.add_argument("--insecure", action="store_true", help="Allow this local test service's self-signed HTTPS certificate")
    args = parser.parse_args()
    if bool(args.cert) != bool(args.key):
        parser.error("--cert and --key must be provided together")
    try:
        database = isolated_database(args.db)
        if args.command == "serve":
            loopback_host(args.host)
            if not 1 <= args.port <= 65535:
                raise ValueError("Fixture port must be 1..65535")
        if args.command == "scenario":
            loopback_url(args.url)
    except ValueError as error:
        parser.error(str(error))
    if args.command == "scenario":
        context = ssl._create_unverified_context() if args.insecure else ssl.create_default_context()
        opener = build_opener(HTTPCookieProcessor(CookieJar()), HTTPSHandler(context=context), LoopbackRedirectHandler())
        opener.open(Request(args.url.rstrip("/") + "/login", data=urlencode({"identifier": args.user, "password": PASSWORD}).encode())).read()
        body = json.dumps({"scenario": args.scenario, "seconds_before": args.seconds_before}).encode()
        response = opener.open(Request(args.url.rstrip("/") + "/api/_test/scenario", data=body, headers={"Content-Type": "application/json"})).read()
        # Escaped Unicode keeps the payload safe to copy through Windows terminals.
        print(json.dumps(json.loads(response), ensure_ascii=True, indent=2))
    elif args.command == "selfcheck":
        selfcheck(database)
    else:
        app = fixture_app(database, testing=args.command == "init")
        if args.command == "init":
            print(json.dumps({"database": str(database), "owner": "androidowner", "member": "androidviewer", "password": PASSWORD}))
        else:
            print(f"Isolated fixture DATABASE={database}; monitor enabled; credentials androidowner / {PASSWORD}", flush=True)
            app.run(host=args.host, port=args.port, ssl_context=(args.cert, args.key) if args.cert else None, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
