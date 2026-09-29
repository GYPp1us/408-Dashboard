from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import create_app, routes
from app.db import connect, create_user, list_focus_items


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    now = datetime(2026, 9, 28, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(routes, "_now", lambda timezone_name="UTC": now)
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "preferences.sqlite3"),
                      "SECRET_KEY": "test", "ADMIN_PASSWORD": "password", "COOKIE_SECURE": False})
    connection = connect(app.config["DATABASE"])
    owner_id = connection.execute("SELECT id FROM users WHERE role = 'site_owner'").fetchone()["id"]
    other_id = create_user(connection, "other", "other@example.com", "unused", now.isoformat())
    connection.commit()
    item = list_focus_items(connection, owner_id)[0]
    other_item = list_focus_items(connection, other_id)[0]
    connection.close()

    def client(user_id, guest=False):
        result = app.test_client()
        with result.session_transaction() as session:
            session.update(authenticated=True, role="guest" if guest else "user")
            session["profile_user_id" if guest else "user_id"] = user_id
        return result

    return app, client, owner_id, other_id, item, other_item


def test_preferences_are_typed_persistent_and_viewer_scoped(setup):
    app, client, owner, other, _, _ = setup
    owner_client = client(owner)
    defaults = owner_client.get("/api/dashboard").get_json()["preferences"]
    assert defaults == {"quick_focus_count": 4, "theme_mode": "system", "theme_palette": "clay", "viewer_id": owner}
    values = {"quick_focus_count": 8, "theme_mode": "dark", "theme_palette": "sage"}
    assert owner_client.patch("/api/settings", json=values).status_code == 200
    assert client(owner).get("/api/dashboard").get_json()["preferences"] == {**values, "viewer_id": owner}
    assert client(other).get("/api/dashboard").get_json()["preferences"]["quick_focus_count"] == 4
    guest = client(owner, guest=True)
    assert guest.get("/api/dashboard").get_json()["preferences"] == {**values, "viewer_id": owner}
    assert guest.patch("/api/settings", json=values).status_code == 403
    with app.test_request_context():
        from flask import session
        session.update(authenticated=True, role="guest", profile_user_id=owner, user_id=other)
        context = {}
        app.update_template_context(context)
        assert context["ui_preferences"] == {**values, "viewer_id": owner}


@pytest.mark.parametrize("key,value", [
    ("quick_focus_count", True), ("quick_focus_count", 3.0), ("quick_focus_count", "4"),
    ("quick_focus_count", 1), ("quick_focus_count", 9), ("quick_focus_count", None),
    ("theme_mode", "auto"), ("theme_mode", []), ("theme_palette", "red"), ("theme_palette", {}),
])
def test_invalid_preferences_do_not_write_other_settings(setup, key, value):
    _, client, owner, _, _, _ = setup
    result = client(owner)
    response = result.patch("/api/settings", json={"morning_start": "09:00", key: value})
    assert response.status_code == 400
    assert response.get_json()["error"] == f"invalid_{key}"
    assert result.get("/api/settings").get_json()["settings"]["morning_start"] == "08:00"


def test_invalid_settings_shape_and_atomic_message_validation(setup):
    _, client, owner, _, _, _ = setup
    result = client(owner)
    for payload in (None, [], "invalid"):
        assert result.patch("/api/settings", json=payload).status_code == 400
    before = result.get("/api/settings").get_json()
    assert result.patch("/api/settings", json={"focus_messages": [{"category": "new", "text": "new"}],
                                              "theme_mode": "dark", "library_close": "broken"}).status_code == 400
    after = result.get("/api/settings").get_json()
    assert after["focus_messages"] == before["focus_messages"]
    assert after["settings"]["theme_mode"] == "system"


def test_display_preferences_skip_index_refresh_but_sources_refresh(setup, monkeypatch):
    _, client, owner, _, _, _ = setup
    refreshes = []
    monkeypatch.setattr(routes, "_refresh_focus_kline", lambda connection, user_id: refreshes.append(user_id))
    result = client(owner)
    assert result.patch("/api/settings", json={"quick_focus_count": 6, "theme_mode": "dark", "theme_palette": "ocean"}).status_code == 200
    assert refreshes == []
    current = result.get("/api/settings").get_json()["settings"]
    # The settings form sends schedules along with appearance preferences.
    unchanged = {key: current[key] for key in ("timezone", "morning_start", "lunch_start", "library_open", "library_close")}
    assert result.patch("/api/settings", json={**unchanged, "theme_mode": "light"}).status_code == 200
    assert refreshes == []
    for values in ({"timezone": "UTC"}, {"focus_kline_a_mid": 8}, {"library_close": "21:00"}):
        assert result.patch("/api/settings", json=values).status_code == 200
    assert refreshes == [owner, owner, owner]


def add_session(connection, user_id, item, start, end, pause=None):
    cursor = connection.execute("""INSERT INTO focus_sessions
        (user_id, subject_id, focus_item_id, subject, mode, planned_minutes, started_at, ended_at, status)
        VALUES (?, ?, ?, ?, '专注', 0, ?, ?, 'completed')""",
        (user_id, item["subject_id"], item["id"], item["subject"], start, end))
    if pause:
        connection.execute("INSERT INTO focus_pauses(session_id, started_at, ended_at) VALUES (?, ?, ?)",
                           (cursor.lastrowid, *pause))
    return cursor.lastrowid


def test_interval_clips_cross_day_sessions_and_subtracts_pauses(setup):
    app, client, owner, other, item, other_item = setup
    connection = connect(app.config["DATABASE"])
    session_id = add_session(connection, owner, item, "2026-09-27T23:30:00+08:00", "2026-09-28T02:30:00+08:00",
                             ("2026-09-28T00:30:00+08:00", "2026-09-28T01:00:00+08:00"))
    add_session(connection, other, other_item, "2026-09-28T00:00:00+08:00", "2026-09-28T02:00:00+08:00")
    connection.commit()
    before = [tuple(row) for row in connection.execute("SELECT * FROM focus_sessions ORDER BY id")]
    for viewer in (client(owner), client(owner, guest=True)):
        data = viewer.get("/api/focus/interval?date=2026-09-28&hour=0").get_json()
        assert data["total_seconds"] == 5400
        assert data["subjects"] == [{"subject": item["subject"], "seconds": 5400}]
        assert [row["id"] for row in data["sessions"]] == [session_id]
        assert data["sessions"][0]["started_at"] == "2026-09-28T00:00:00+08:00"
        assert data["sessions"][0]["ended_at"] == "2026-09-28T02:00:00+08:00"
        assert "user_id" not in data["sessions"][0]
    assert before == [tuple(row) for row in connection.execute("SELECT * FROM focus_sessions ORDER BY id")]
    connection.close()


@pytest.mark.parametrize("query", ["date=2026-02-30&hour=0", "date=2026-9-28&hour=0",
                                  "date=9999-12-31&hour=22", "date=2026-09-28&hour=1",
                                  "date=2026-09-28&hour=24", "date=2026-09-28&hour=bad", ""])
def test_interval_rejects_bad_bounds(setup, query):
    _, client, owner, _, _, _ = setup
    assert client(owner).get(f"/api/focus/interval?{query}").status_code == 400


def test_item_summary_is_scoped_and_limits_recent_sessions(setup):
    app, client, owner, other, item, other_item = setup
    connection = connect(app.config["DATABASE"])
    for hour in range(12):
        add_session(connection, owner, item, f"2026-09-27T{hour:02}:00:00+08:00", f"2026-09-27T{hour:02}:30:00+08:00")
    add_session(connection, owner, item, "2026-09-28T08:00:00+08:00", "2026-09-28T10:00:00+08:00",
                ("2026-09-28T08:30:00+08:00", "2026-09-28T09:00:00+08:00"))
    add_session(connection, other, other_item, "2026-09-28T08:00:00+08:00", "2026-09-28T10:00:00+08:00")
    connection.commit()
    connection.close()
    endpoint = f"/api/focus/items/{item['id']}/summary"
    data = client(owner).get(endpoint).get_json()
    assert data["item"] == item
    assert data["today_seconds"] == 5400
    assert data["all_time_seconds"] == 27000
    assert data["today_count"] == 1
    assert len(data["recent_sessions"]) == 10
    assert client(owner, guest=True).get(endpoint).get_json() == data
    assert client(other).get(endpoint).status_code == 404
    assert client(other, guest=True).get(endpoint).status_code == 404
    assert app.test_client().get(endpoint).status_code == 401
    assert app.test_client().get("/api/focus/interval?date=2026-09-28&hour=0").status_code == 401


def test_start_focus_idempotency_never_returns_another_accounts_session(setup):
    _, client, owner, other, item, other_item = setup
    token = "account-scoped-idempotency-test"
    owner_client = client(owner)
    payload = {"focus_item_id": item["id"], "mode": "专注", "client_token": token}
    first = owner_client.post("/api/focus/start", json=payload)
    assert first.status_code == 201
    retry = owner_client.post("/api/focus/start", json=payload)
    assert retry.status_code == 200
    assert retry.get_json()["idempotent"] is True
    assert retry.get_json()["session"]["id"] == first.get_json()["session"]["id"]
    other_client = client(other)
    conflict = other_client.post("/api/focus/start", json={"focus_item_id": other_item["id"], "mode": "专注", "client_token": token})
    assert conflict.status_code == 409
    assert conflict.get_json() == {"error": "client_token_conflict"}
    assert other_client.get("/api/focus").get_json()["active"] is None
    fresh = other_client.post("/api/focus/start", json={"focus_item_id": other_item["id"], "mode": "专注", "client_token": "other-unique-token"})
    assert fresh.status_code == 201
    assert fresh.get_json()["session"]["user_id"] == other
