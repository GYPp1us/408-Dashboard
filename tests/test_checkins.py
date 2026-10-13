from datetime import datetime, timezone
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture()
def checkin_client(tmp_path, monkeypatch):
    from app import create_app
    clock = {"now": datetime(2026, 10, 13, 1, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr("app.checkins.current_time", lambda zone: clock["now"])
    monkeypatch.setattr("app.routes.current_time", lambda zone: clock["now"].astimezone(__import__('zoneinfo').ZoneInfo(zone)))
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "checkin.sqlite3"),
                      "SECRET_KEY": "checkin-test", "ADMIN_PASSWORD": "test-password", "COOKIE_SECURE": False})
    client = app.test_client()
    client.post("/login", data={"password": "test-password"})
    return client, clock


def create(client, **values):
    result = client.post("/api/checkins", json={"name": "晨间签到", **values})
    assert result.status_code == 201, result.get_json()
    return result.get_json()["id"]


def test_checkin_daily_idempotency_heatmap_and_day_rollover(checkin_client):
    client, clock = checkin_client
    item = create(client)
    frame = {"checkin_item_id": item}
    first = client.post("/api/checkins/frame", json=frame).get_json()
    second = client.post("/api/checkins/frame", json=frame).get_json()
    assert first["changed"] and not second["changed"] and first["record_id"] == second["record_id"]
    heat = client.get("/api/dashboard").get_json()["checkin_heatmap"]
    assert heat[-1] == {"date": "2026-10-13", "completed": 1, "total": 1, "completion": 1.0}
    assert heat[-2]["total"] == 0 and heat[-2]["completion"] is None
    clock["now"] = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
    assert client.post("/api/checkins/frame", json=frame).get_json()["changed"]
    assert client.get("/api/checkins").get_json()["date"] == "2026-10-14"


@pytest.mark.parametrize("minute,allowed", [("00:59", False), ("01:00", True), ("02:00", False)])
def test_time_condition_uses_account_zone_start_inclusive_end_exclusive(checkin_client, minute, allowed):
    client, clock = checkin_client
    item = create(client, time_start="09:00", time_end="10:00")
    clock["now"] = datetime.fromisoformat(f"2026-10-13T{minute}:00+00:00")
    result = client.post("/api/checkins/frame", json={"checkin_item_id": item, "at": "2026-10-13T09:30:00+08:00"})
    assert result.status_code == (200 if allowed else 409)


def test_overnight_window_and_optional_location_are_both_enforced(checkin_client):
    client, clock = checkin_client
    item = create(client, time_start="22:00", time_end="02:00", latitude=30.0, longitude=120.0, radius_meters=200)
    clock["now"] = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
    base = {"checkin_item_id": item, "latitude": 30.0, "longitude": 120.0, "accuracy": 10}
    assert client.post("/api/checkins/frame", json={"checkin_item_id": item}).get_json()["error"] == "checkin_location_required"
    assert client.post("/api/checkins/frame", json={**base, "accuracy": 500}).status_code == 409
    assert client.post("/api/checkins/frame", json={**base, "longitude": 121}).get_json()["error"] == "checkin_outside_location"
    assert client.post("/api/checkins/frame", json=base).status_code == 200
    clock["now"] = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)
    # Already completed today is idempotent even after the time window closes.
    assert not client.post("/api/checkins/frame", json=base).get_json()["changed"]
    clock["now"] = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
    assert client.post("/api/checkins/frame", json=base).get_json()["error"] == "checkin_outside_time_window"


@pytest.mark.parametrize("extra", [{"time_start": "9:00", "time_end": "10:00"}, {"time_start": "10:00", "time_end": "10:00"},
                                   {"latitude": True, "longitude": 120}, {"latitude": 91, "longitude": 120}, {"radius_meters": 1}])
def test_invalid_rule_conditions_are_rejected(checkin_client, extra):
    client, _ = checkin_client
    assert client.post("/api/checkins", json={"name": "打卡", **extra}).status_code == 400
    assert client.get("/api/checkins").get_json()["checkin_items"] == []


def test_archive_keeps_historical_accomplishments_and_removes_future_targets(checkin_client):
    client, clock = checkin_client
    item = create(client)
    assert client.post("/api/checkins/frame", json={"checkin_item_id": item}).status_code == 200
    assert client.delete(f"/api/checkins/{item}").status_code == 200
    assert client.post("/api/checkins/frame", json={"checkin_item_id": item}).status_code == 404
    assert client.get("/api/dashboard").get_json()["checkin_heatmap"][-1]["completed"] == 1
    clock["now"] = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)
    heat = client.get("/api/dashboard").get_json()["checkin_heatmap"]
    assert heat[-1]["total"] == 0 and heat[-2]["completed"] == 1


def test_reporter_protocol_rotation_scope_and_durable_key(checkin_client):
    client, _ = checkin_client
    item = create(client)
    connection = client.post("/api/checkin-reporter/connection").get_json()
    assert client.post("/api/checkin-reporter/connection").get_json() == connection
    assert client.get(urlparse(connection["catalog_url"]).path).get_json()["checkin_items"][0]["id"] == item
    frame_path = urlparse(connection["report_url"]).path
    assert client.post(frame_path, json={"source": "external.app", "state": "idle"}).status_code == 200
    frame = {"source": "external.app", "state": "checkin", "checkin_item_id": item}
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: client.application.test_client().post(frame_path, json=frame).get_json(), range(2)))
    assert sum(result["changed"] for result in results) == 1
    assert results[0]["record_id"] == results[1]["record_id"]
    rotated = client.post("/api/checkin-reporter/connection/rotate").get_json()
    assert rotated != connection and client.post(frame_path, json=frame).status_code == 401
    assert client.post("/api/focus-reporter/connection").status_code == 200
    guest = client.application.test_client()
    guest.get("/guest")
    assert guest.get("/api/checkins").status_code == 403
    assert guest.post("/api/checkin-reporter/connection").status_code == 403
    assert client.application.test_client().post("/api/checkins/frame", json=frame).status_code == 401


def test_rules_and_frames_cannot_cross_accounts(checkin_client):
    from app.db import connect, create_user
    from werkzeug.security import generate_password_hash
    client, clock = checkin_client
    item = create(client)
    conn = connect(client.application.config["DATABASE"])
    create_user(conn, "other", "other@example.invalid", generate_password_hash("other-password"), clock["now"].isoformat())
    conn.commit(); conn.close()
    other = client.application.test_client()
    other.post("/login", data={"identifier": "other", "password": "other-password"})
    assert other.put(f"/api/checkins/{item}", json={"name": "篡改"}).status_code == 404
    assert other.post("/api/checkins/frame", json={"checkin_item_id": item}).status_code == 404
    assert other.get("/api/checkins").get_json()["checkin_items"] == []


def test_checkin_history_preserves_account_time_and_keys_survive_app_secret_rotation(checkin_client):
    from app import create_app
    client, _ = checkin_client
    item = create(client)
    client.post("/api/checkins/frame", json={"checkin_item_id": item})
    records = client.get("/api/checkins/history?date=2026-10-13").get_json()["records"]
    assert records[0]["time"] == "09:00"
    assert client.get("/api/checkins/history?date=invalid").status_code == 400
    details = client.post("/api/checkin-reporter/connection").get_json()
    restarted = create_app({**client.application.config, "SECRET_KEY": "new-secret"}).test_client()
    assert restarted.get(urlparse(details["catalog_url"]).path).status_code == 200
