from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest


@pytest.fixture()
def reporter_client(tmp_path):
    from app import create_app

    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "reporter.sqlite3"),
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "test-password",
        "COOKIE_SECURE": False,
    })
    client = app.test_client()
    client.post("/login", data={"password": "test-password"})
    return client


def test_reporter_key_catalog_rotation_and_guest_boundary(reporter_client):
    details = reporter_client.post("/api/focus-reporter/connection").get_json()
    repeated = reporter_client.post("/api/focus-reporter/connection").get_json()
    assert details == repeated
    assert details["report_url"].startswith("https://platform.arcol.site/api/focus-reporter/")
    catalog_path = urlparse(details["catalog_url"]).path
    catalog = reporter_client.get(catalog_path)
    assert catalog.status_code == 200
    assert catalog.get_json()["subjects"]
    assert catalog.get_json()["focus_items"]
    assert reporter_client.get(catalog_path.replace("/catalog", "x/catalog")).status_code == 401

    rotated = reporter_client.post("/api/focus-reporter/connection/rotate").get_json()
    assert rotated["report_url"] != details["report_url"]
    assert reporter_client.get(catalog_path).status_code == 401
    assert reporter_client.get(urlparse(rotated["catalog_url"]).path).status_code == 200

    guest = reporter_client.application.test_client()
    guest.get("/guest")
    assert guest.post("/api/focus-reporter/connection").status_code == 403


def test_existing_key_is_preserved_through_schema_upgrade_and_secret_rotation(tmp_path):
    from app import create_app
    from app.db import connect
    from app.focus_reporter import _legacy_token

    database = str(tmp_path / "legacy-reporter.sqlite3")
    config = {
        "TESTING": True,
        "DATABASE": database,
        "SECRET_KEY": "old-app-secret",
        "ADMIN_PASSWORD": "test-password",
        "COOKIE_SECURE": False,
    }
    create_app(config)
    connection = connect(database)
    try:
        user_id = connection.execute("SELECT id FROM users WHERE role = 'site_owner'").fetchone()[0]
        connection.execute("DROP TABLE focus_reporter_keys")
        connection.execute(
            "CREATE TABLE focus_reporter_keys (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, "
            "nonce TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        nonce = "existing-issued-nonce"
        legacy_key = _legacy_token(user_id, nonce, config["SECRET_KEY"])
        connection.execute(
            "INSERT INTO focus_reporter_keys(user_id, nonce, created_at) VALUES (?, ?, ?)",
            (user_id, nonce, "2026-09-25T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()

    create_app(config)
    connection = connect(database)
    try:
        stored = connection.execute("SELECT token FROM focus_reporter_keys WHERE user_id = ?", (user_id,)).fetchone()
        assert stored["token"] == legacy_key
    finally:
        connection.close()

    rotated_app = create_app({**config, "SECRET_KEY": "new-app-secret"})
    client = rotated_app.test_client()
    assert client.get(f"/api/focus-reporter/{legacy_key}/catalog").status_code == 200
    assert client.post("/login", data={"password": "test-password"}).status_code in (200, 302)
    details = client.post("/api/focus-reporter/connection").get_json()
    assert f"/{legacy_key}/frame" in details["report_url"]


def test_new_key_survives_app_secret_rotation(tmp_path):
    from app import create_app

    config = {
        "TESTING": True,
        "DATABASE": str(tmp_path / "durable-reporter.sqlite3"),
        "SECRET_KEY": "first-secret",
        "ADMIN_PASSWORD": "test-password",
        "COOKIE_SECURE": False,
    }
    first = create_app(config).test_client()
    first.post("/login", data={"password": "test-password"})
    details = first.post("/api/focus-reporter/connection").get_json()
    second = create_app({**config, "SECRET_KEY": "second-secret"}).test_client()
    second.post("/login", data={"password": "test-password"})
    assert second.post("/api/focus-reporter/connection").get_json() == details
    assert second.get(urlparse(details["catalog_url"]).path).status_code == 200


def test_reporter_frames_form_one_session_and_reject_conflicts(reporter_client):
    from app.db import connect

    details = reporter_client.post("/api/focus-reporter/connection").get_json()
    path = urlparse(details["report_url"]).path
    catalog = reporter_client.get(urlparse(details["catalog_url"]).path).get_json()
    item = catalog["focus_items"][0]
    frame = {"source": "study_app", "state": "focus", "subject_id": item["subject_id"], "focus_item_id": item["id"]}
    assert reporter_client.post(path, json={**frame, "subject_id": -1}).status_code == 400
    assert reporter_client.post(path, json={**frame, "subject_id": catalog["subjects"][-1]["id"] + 1000}).status_code == 404

    started = reporter_client.post(path, json=frame)
    assert started.status_code == 200
    session_id = started.get_json()["session_id"]
    repeated = reporter_client.post(path, json=frame)
    assert repeated.status_code == 200
    assert repeated.get_json()["session_id"] == session_id
    assert reporter_client.post(path, json={**frame, "source": "other_app"}).status_code == 409
    assert reporter_client.get("/api/dashboard").status_code == 200

    connection = connect(reporter_client.application.config["DATABASE"])
    try:
        row = connection.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()
        assert row["reporter_source"] == "study_app"
        assert row["status"] == "active"
        assert connection.execute("SELECT COUNT(*) FROM focus_sessions WHERE reporter_source = 'study_app'").fetchone()[0] == 1
    finally:
        connection.close()

    stopped = reporter_client.post(path, json={"source": "study_app", "state": "idle"})
    assert stopped.status_code == 200
    assert stopped.get_json()["session_id"] == session_id
    assert reporter_client.post(path, json={"source": "study_app", "state": "idle"}).get_json()["session_id"] is None


def test_reporter_timeout_caps_focus_and_web_heartbeat_does_not_extend_it(reporter_client):
    from app.db import connect, expire_unattended_focus, record_foreground_heartbeat
    from app.focus_reporter import apply_frame
    from app.routes import _session_segments

    connection = connect(reporter_client.application.config["DATABASE"])
    try:
        user_id = connection.execute("SELECT id FROM users WHERE role = 'site_owner'").fetchone()[0]
        item = connection.execute("SELECT id, subject_id FROM user_focus_items WHERE user_id = ? ORDER BY id LIMIT 1", (user_id,)).fetchone()
        frame = {"source": "flashcards", "state": "focus", "subject_id": item["subject_id"], "focus_item_id": item["id"]}
        started_at = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
        started = apply_frame(connection, user_id, frame, started_at)
        record_foreground_heartbeat(connection, started_at + timedelta(seconds=25), user_id)
        active = dict(connection.execute("SELECT * FROM focus_sessions WHERE id = ?", (started["session_id"],)).fetchone())
        assert active["last_foreground_at"] == started_at.isoformat()
        segments = _session_segments(active, [], started_at + timedelta(minutes=5))
        assert int((segments[0][1] - segments[0][0]).total_seconds()) == 45

        expired_id = expire_unattended_focus(connection, started_at + timedelta(minutes=5))
        assert expired_id == started["session_id"]
        ended = connection.execute("SELECT ended_at, ended_reason FROM focus_sessions WHERE id = ?", (expired_id,)).fetchone()
        assert ended["ended_at"] == (started_at + timedelta(seconds=45)).isoformat()
        assert ended["ended_reason"] == "reporter_timeout"
    finally:
        connection.close()
