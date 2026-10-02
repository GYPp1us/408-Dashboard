from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app import create_app
from app.db import connect, create_user, export_migration_data, get_daily_settlement, init_db, list_focus_items
from app.focus_challenge import account_now


@pytest.fixture()
def settlement_app(tmp_path, monkeypatch):
    current = [datetime.fromisoformat("2026-10-02T16:00:00+08:00")]
    monkeypatch.setattr("app.routes._now", lambda zone="UTC": account_now(current[0], zone))
    # These tests exercise durable source writes and the pure report algorithm;
    # derived cache refresh has its own integration tests.
    monkeypatch.setattr("app.routes._refresh_focus_kline", lambda *args, **kwargs: None)
    application = create_app({
        "TESTING": True, "DATABASE": str(tmp_path / "settlement.sqlite3"),
        "SECRET_KEY": "test-secret", "ADMIN_PASSWORD": "test-password", "COOKIE_SECURE": False,
    })
    connection = connect(application.config["DATABASE"])
    owner = connection.execute("SELECT id FROM users WHERE role='site_owner'").fetchone()[0]
    connection.close()
    return application, owner, current


def signed_client(application, user_id):
    client = application.test_client()
    with client.session_transaction() as session:
        session.update(authenticated=True, role="user", user_id=user_id)
    return client


def seed_session(application, owner, start, end=None, *, subject="数学", trusted=True,
                 locked=False, pause_start=None, pause_end=None, reporter=None, last_seen=None,
                 ended_reason=None):
    connection = connect(application.config["DATABASE"])
    try:
        item = next(item for item in list_focus_items(connection, owner) if item["subject"] == subject)
        cursor = connection.execute(
            "INSERT INTO focus_sessions(user_id,subject_id,focus_item_id,subject,mode,planned_minutes,"
            "started_at,ended_at,status,last_foreground_at,focus_locked,trusted,reporter_source,ended_reason) "
            "VALUES (?,?,?,?,?,0,?,?,?,?,?,?,?,?)",
            (owner, item["subject_id"], item["id"], item["label"], "专注", start, end,
             "completed" if end else "active", last_seen or start, int(locked), int(trusted), reporter, ended_reason),
        )
        session_id = cursor.lastrowid
        if pause_start:
            connection.execute("INSERT INTO focus_pauses(session_id,started_at,ended_at) VALUES (?,?,?)",
                               (session_id, pause_start, pause_end))
        connection.commit()
        return session_id
    finally:
        connection.close()


def test_active_settlement_freezes_rich_report_and_preserves_market_snapshot(settlement_app):
    application, owner, current = settlement_app
    client = signed_client(application, owner)
    seed_session(application, owner, "2026-10-01T08:00:00+08:00", "2026-10-01T13:00:00+08:00")
    seed_session(application, owner, "2026-10-02T08:00:00+08:00", "2026-10-02T12:00:00+08:00")
    seed_session(application, owner, "2026-10-02T13:00:00+08:00", "2026-10-02T15:00:00+08:00",
                 subject="英语", trusted=False, pause_start="2026-10-02T13:30:00+08:00",
                 pause_end="2026-10-02T14:00:00+08:00")
    active = seed_session(application, owner, "2026-10-02T15:30:00+08:00")
    assert client.patch("/api/focus-kline/challenge", json={"enabled": True}).status_code == 200
    quote = client.get("/api/focus-kline").get_json()["today"]
    assert client.get("/api/dashboard").get_json()["can_settle_today"] is True

    response = client.post("/api/daily-settlement", json={"expected_date": "2026-10-02", "session_id": active})
    assert response.status_code == 201
    payload = response.get_json()
    report = payload["report"]
    assert report == payload["settlement"]["report"]
    assert (report["total_seconds"], report["yesterday_seconds"], report["delta_seconds"]) == (21600, 18000, 3600)
    assert (report["trusted_seconds"], report["untrusted_seconds"]) == (16200, 5400)
    assert report["subject_totals"] == [
        {"subject": "数学", "seconds": 16200, "percent": 75},
        {"subject": "英语", "seconds": 5400, "percent": 25},
    ]
    assert (report["session_count"], report["longest_session_seconds"]) == (3, 14400)
    assert report["first_start"] == "2026-10-02T08:00:00+08:00"
    assert report["last_end"] == "2026-10-02T16:00:00+08:00"
    assert (report["rank"], report["percentile"], report["day_count"]) == (1, 100, 2)
    assert report["challenge"]["active_today"] is True
    assert report["index"]["current"] == quote["close"]
    assert report["index"]["is_market_closed"] is False
    assert "尚未收盘" in report["index"]["note"]
    assert {badge["id"] for badge in report["achievements"]} == {
        "ahead_of_yesterday", "personal_best", "one_hour_session",
    }
    assert payload["ended_session"]["ended_reason"] == "daily_settlement"
    assert payload["focus_state"] == {"state": "rest", "is_focusing": False, "is_paused": False}

    current[0] += timedelta(hours=1)
    client.patch("/api/focus-kline/challenge", json={"enabled": False})
    connection = connect(application.config["DATABASE"])
    connection.execute("UPDATE user_subjects SET name='改名数学' WHERE user_id=? AND name='数学'", (owner,))
    connection.execute("UPDATE focus_sessions SET trusted=1 WHERE user_id=?", (owner,))
    connection.commit()
    connection.close()
    repeated = client.post("/api/daily-settlement", json={"expected_date": "2026-10-02", "session_id": active})
    assert repeated.status_code == 200
    assert repeated.get_json()["idempotent"] is True
    assert repeated.get_json()["report"] == report
    assert client.get("/api/daily-settlement/report?date=2026-10-02").get_json()["report"] == report
    assert client.get("/api/dashboard").get_json()["daily_settlement"]["report"] == report
    assert client.post("/api/focus/start", json={"subject": "英语二轮", "mode": "专注"}).status_code == 409


def test_paused_locked_focus_closes_without_reclassifying_or_counting_pause(settlement_app):
    application, owner, _ = settlement_app
    active = seed_session(application, owner, "2026-10-02T14:00:00+08:00", trusted=False, locked=True,
                          pause_start="2026-10-02T15:00:00+08:00")
    client = signed_client(application, owner)
    response = client.post("/api/daily-settlement", json={"session_id": active})
    report = response.get_json()["report"]
    assert response.status_code == 201
    assert (report["total_seconds"], report["trusted_seconds"], report["untrusted_seconds"]) == (3600, 0, 3600)
    ended = response.get_json()["ended_session"]
    assert ended["focus_locked"] is True and ended["trusted"] is False
    assert ended["paused_at"] is None and ended["paused_seconds"] == 3600
    connection = connect(application.config["DATABASE"])
    assert connection.execute("SELECT COUNT(*) FROM focus_pauses WHERE ended_at IS NULL").fetchone()[0] == 0
    connection.close()


def test_reporter_timeout_cap_survives_durable_settlement(settlement_app):
    application, owner, _ = settlement_app
    active = seed_session(application, owner, "2026-10-02T14:00:00+08:00", reporter="android",
                          last_seen="2026-10-02T14:10:00+08:00")
    client = signed_client(application, owner)
    response = client.post("/api/daily-settlement", json={"session_id": active})
    assert response.status_code == 201
    assert response.get_json()["report"]["total_seconds"] == 645
    assert response.get_json()["ended_session"]["ended_at"] == "2026-10-02T06:10:45+00:00"
    assert client.get("/api/dashboard").get_json()["today_focus"]["seconds"] == 645


def test_report_failure_rolls_back_active_end_and_pause(settlement_app, monkeypatch):
    application, owner, _ = settlement_app
    active = seed_session(application, owner, "2026-10-02T14:00:00+08:00",
                          pause_start="2026-10-02T15:00:00+08:00")
    def failed_report(*args, **kwargs):
        raise RuntimeError("report generation failed")
    monkeypatch.setattr("app.routes.build_settlement_report", failed_report)
    client = signed_client(application, owner)
    with pytest.raises(RuntimeError, match="report generation failed"):
        client.post("/api/daily-settlement", json={"session_id": active})
    connection = connect(application.config["DATABASE"])
    assert connection.execute("SELECT status FROM focus_sessions WHERE id=?", (active,)).fetchone()[0] == "active"
    assert connection.execute("SELECT ended_at FROM focus_pauses WHERE session_id=?", (active,)).fetchone()[0] is None
    assert connection.execute("SELECT COUNT(*) FROM daily_settlements").fetchone()[0] == 0
    connection.close()


def test_concurrent_settlement_is_one_atomic_end_and_one_frozen_report(settlement_app):
    application, owner, _ = settlement_app
    active = seed_session(application, owner, "2026-10-02T14:00:00+08:00")
    barrier = Barrier(2)
    def submit():
        client = signed_client(application, owner)
        barrier.wait(timeout=10)
        response = client.post("/api/daily-settlement", json={"expected_date": "2026-10-02", "session_id": active})
        return response.status_code, response.get_json()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(status for status, _ in results) == [200, 201]
    assert results[0][1]["report"] == results[1][1]["report"]
    assert sum(payload["ended_session"] is not None for _, payload in results) == 1
    connection = connect(application.config["DATABASE"])
    assert connection.execute("SELECT COUNT(*) FROM daily_settlements WHERE user_id=?", (owner,)).fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM focus_sessions WHERE user_id=? AND status='active'", (owner,)).fetchone()[0] == 0
    connection.close()


def test_stale_date_and_stale_session_cannot_close_current_focus(settlement_app):
    application, owner, _ = settlement_app
    active = seed_session(application, owner, "2026-10-02T14:00:00+08:00")
    client = signed_client(application, owner)
    changed_date = client.post("/api/daily-settlement", json={"expected_date": "2026-10-01", "session_id": active})
    assert changed_date.status_code == 409
    assert changed_date.get_json()["error"] == "settlement_date_changed"
    for stale_id in (None, active + 1):
        changed_session = client.post("/api/daily-settlement", json={"expected_date": "2026-10-02", "session_id": stale_id})
        assert changed_session.status_code == 409
        assert changed_session.get_json()["error"] == "focus_session_changed"
    assert client.get("/api/focus").get_json()["active"]["id"] == active
    assert client.get("/api/daily-settlement/report?date=2026-10-02").status_code == 404


def test_cross_midnight_session_uses_account_day_and_old_retry_leaves_new_focus(settlement_app):
    application, owner, current = settlement_app
    current[0] = datetime.fromisoformat("2026-10-02T01:00:00+08:00")
    active = seed_session(application, owner, "2026-10-01T23:30:00+08:00")
    client = signed_client(application, owner)
    response = client.post("/api/daily-settlement", json={"expected_date": "2026-10-02", "session_id": active})
    report = response.get_json()["report"]
    assert report["date"] == "2026-10-02" and report["settled_at"].startswith("2026-10-01")
    assert (report["total_seconds"], report["yesterday_seconds"]) == (3600, 1800)
    current[0] = datetime.fromisoformat("2026-10-03T01:00:00+08:00")
    new_active = seed_session(application, owner, "2026-10-03T00:30:00+08:00")
    repeated = client.post("/api/daily-settlement", json={"expected_date": "2026-10-02", "session_id": active})
    assert repeated.status_code == 200 and repeated.get_json()["report"] == report
    assert repeated.get_json()["ended_session"] is None
    assert client.get("/api/focus").get_json()["active"]["id"] == new_active
    assert client.get("/api/dashboard").get_json()["can_settle_today"] is True


def test_utc_account_settles_utc_day_and_can_start_next_day(settlement_app):
    application, owner, current = settlement_app
    connection = connect(application.config["DATABASE"])
    connection.execute("UPDATE user_settings SET value='UTC' WHERE user_id=? AND key='timezone'", (owner,))
    connection.commit()
    connection.close()
    current[0] = datetime.fromisoformat("2026-10-02T01:00:00+08:00")
    seed_session(application, owner, "2026-10-01T23:30:00+08:00")
    client = signed_client(application, owner)
    response = client.post("/api/daily-settlement", json={"expected_date": "2026-10-01"})
    assert response.status_code == 201
    report = response.get_json()["report"]
    assert report["date"] == "2026-10-01" and report["timezone"] == "UTC"
    assert report["total_seconds"] == 5400
    current[0] = datetime.fromisoformat("2026-10-02T09:00:00+08:00")
    assert client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"}).status_code == 201


def test_report_owner_isolation_and_guest_read_only(settlement_app):
    application, owner, current = settlement_app
    owner_client = signed_client(application, owner)
    report = owner_client.post("/api/daily-settlement", json={}).get_json()["report"]
    connection = connect(application.config["DATABASE"])
    other = create_user(connection, "other", "other@example.com", "hash", current[0].isoformat())
    connection.commit()
    connection.close()
    other_active = seed_session(application, other, "2026-10-02T15:00:00+08:00")
    other_client = signed_client(application, other)
    assert other_client.get(f"/api/daily-settlement/report?date=2026-10-02&user_id={owner}").status_code == 404
    guest = application.test_client()
    with guest.session_transaction() as session:
        session.update(authenticated=True, role="guest", profile_user_id=owner)
    assert guest.get(f"/api/daily-settlement/report?date=2026-10-02&user_id={other}").get_json()["report"] == report
    assert guest.post("/api/daily-settlement", json={}).get_json() == {"error": "guest_read_only"}
    assert guest.get("/api/dashboard").get_json()["can_settle_today"] is False
    assert other_client.get("/api/focus").get_json()["active"]["id"] == other_active
    assert application.test_client().get("/api/daily-settlement/report").status_code == 401


def test_guest_dashboard_does_not_extend_the_viewed_accounts_heartbeat(settlement_app):
    application, owner, current = settlement_app
    active = seed_session(application, owner, "2026-10-02T14:00:00+08:00",
                          last_seen="2026-10-02T14:10:00+08:00")
    guest = application.test_client()
    with guest.session_transaction() as session:
        session.update(authenticated=True, role="guest", profile_user_id=owner)
    assert guest.get("/api/dashboard").status_code == 200
    connection = connect(application.config["DATABASE"])
    assert connection.execute("SELECT last_foreground_at FROM focus_sessions WHERE id=?", (active,)).fetchone()[0] == "2026-10-02T14:10:00+08:00"
    connection.close()
    assert signed_client(application, owner).get("/api/dashboard").status_code == 200
    connection = connect(application.config["DATABASE"])
    assert connection.execute("SELECT last_foreground_at FROM focus_sessions WHERE id=?", (active,)).fetchone()[0] == current[0].astimezone(timezone.utc).isoformat()
    connection.close()


def test_legacy_upgrade_and_export_keep_summary_without_fabricating_details(settlement_app):
    application, owner, current = settlement_app
    connection = connect(application.config["DATABASE"])
    connection.execute("DROP TABLE daily_settlements")
    connection.execute(
        "CREATE TABLE daily_settlements (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, settlement_date TEXT NOT NULL, "
        "settled_at TEXT NOT NULL, total_seconds INTEGER NOT NULL, yesterday_seconds INTEGER NOT NULL, "
        "delta_seconds INTEGER NOT NULL, target_seconds INTEGER NOT NULL, completion REAL NOT NULL, "
        "session_count INTEGER NOT NULL, top_subject TEXT, top_subject_seconds INTEGER NOT NULL DEFAULT 0, "
        "UNIQUE(user_id,settlement_date))"
    )
    connection.execute(
        "INSERT INTO daily_settlements(user_id,settlement_date,settled_at,total_seconds,yesterday_seconds,"
        "delta_seconds,target_seconds,completion,session_count,top_subject,top_subject_seconds) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (owner, "2026-10-01", "2026-10-01T14:00:00+00:00", 28800, 18000, 10800, 25200, 1.1429, 4, "数学二轮", 14400),
    )
    connection.commit()
    init_db(connection)
    report = get_daily_settlement(connection, owner, "2026-10-01")["report"]
    assert report["snapshot_kind"] == "legacy_summary"
    assert report["completion_percent"] > 100
    assert report["trusted_seconds"] is None and report["rank"] is None and report["index"] is None
    assert report["subject_breakdown_complete"] is False
    assert report["subject_totals"] == [{"subject": "数学二轮", "seconds": 14400, "percent": 50}]
    assert {badge["id"] for badge in report["achievements"]} == {"goal_met", "ahead_of_yesterday"}
    package = export_migration_data(connection, current[0])
    assert package["version"] == 3 and package["daily_settlements"][0]["report_json"] is None
    connection.close()
    client = signed_client(application, owner)
    assert client.get("/api/daily-settlement/report?date=2026-10-01").get_json()["report"] == report


def test_empty_day_and_over_target_achievements_use_actual_values(settlement_app):
    application, owner, current = settlement_app
    client = signed_client(application, owner)
    empty = client.post("/api/daily-settlement", json={}).get_json()["report"]
    assert empty["total_seconds"] == 0 and empty["achievements"] == []
    assert empty["rank"] is None and empty["first_start"] is None
    current[0] += timedelta(days=1)
    seed_session(application, owner, "2026-10-03T07:00:00+08:00", "2026-10-03T15:00:00+08:00")
    full = client.post("/api/daily-settlement", json={}).get_json()["report"]
    assert full["completion"] > 1 and full["completion_percent"] > 100
    assert {badge["id"] for badge in full["achievements"]} == {"goal_met", "one_hour_session", "trusted_day"}


def test_settlement_blocks_native_recovery_of_foreground_timeout(settlement_app):
    application, owner, _ = settlement_app
    old = seed_session(application, owner, "2026-10-02T14:00:00+08:00", "2026-10-02T14:30:00+08:00",
                       ended_reason="foreground_timeout")
    client = signed_client(application, owner)
    assert client.post("/api/daily-settlement", json={}).status_code == 201
    result = client.post("/api/focus/heartbeat", json={"session_id": old, "allow_recovery": True}).get_json()
    assert result["recovered"] is False and result["status"] == "completed"
    assert client.get("/api/focus").get_json()["active"] is None


@pytest.mark.parametrize("payload", [{"expected_date": "2026-02-30"}, {"expected_date": "20261002"},
                                     {"session_id": True}, {"session_id": "1"}])
def test_invalid_settlement_guard_payload_has_no_effect(settlement_app, payload):
    application, owner, _ = settlement_app
    client = signed_client(application, owner)
    assert client.post("/api/daily-settlement", json=payload).status_code == 400
    assert client.get("/api/daily-settlement/report?date=2026-10-02").status_code == 404


@pytest.mark.parametrize("body,content_type", [
    pytest.param("[]", "application/json", id="array"),
    pytest.param("false", "application/json", id="false"),
    pytest.param("0", "application/json", id="zero"),
    pytest.param('""', "application/json", id="empty-string"),
    pytest.param("null", "application/json", id="null"),
    pytest.param('{"session_id":', "application/json", id="malformed-json"),
    pytest.param("", "application/json", id="empty-json-body"),
    pytest.param("", None, id="missing-body"),
    pytest.param("{}", "text/plain", id="non-json-content-type"),
])
@pytest.mark.parametrize("paused,locked", [
    pytest.param(False, False, id="active"),
    pytest.param(True, False, id="paused"),
    pytest.param(False, True, id="locked"),
    pytest.param(True, True, id="paused-locked"),
])
def test_non_object_or_invalid_json_cannot_settle_or_change_active_focus(
    settlement_app, body, content_type, paused, locked,
):
    application, owner, _ = settlement_app
    active = seed_session(
        application, owner, "2026-10-02T14:00:00+08:00", trusted=not locked, locked=locked,
        pause_start="2026-10-02T15:00:00+08:00" if paused else None,
    )
    connection = connect(application.config["DATABASE"])
    before_session = dict(connection.execute("SELECT * FROM focus_sessions WHERE id=?", (active,)).fetchone())
    before_pauses = [dict(row) for row in connection.execute("SELECT * FROM focus_pauses WHERE session_id=?", (active,))]
    connection.close()

    response = signed_client(application, owner).post(
        "/api/daily-settlement", data=body, content_type=content_type,
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "json_object_required"}
    connection = connect(application.config["DATABASE"])
    assert dict(connection.execute("SELECT * FROM focus_sessions WHERE id=?", (active,)).fetchone()) == before_session
    assert [dict(row) for row in connection.execute("SELECT * FROM focus_pauses WHERE session_id=?", (active,))] == before_pauses
    assert connection.execute("SELECT COUNT(*) FROM daily_settlements").fetchone()[0] == 0
    connection.close()
