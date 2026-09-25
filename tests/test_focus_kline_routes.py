import pytest


@pytest.fixture()
def authenticated_client(tmp_path):
    from app import create_app

    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "focus-kline-routes.sqlite3"),
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "test-password",
        "COOKIE_SECURE": False,
    })
    client = app.test_client()
    client.post("/login", data={"password": "test-password"})
    return client


def test_focus_kline_page_exposes_chart_surface(authenticated_client):
    response = authenticated_client.get("/focus-kline")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-page="focus-kline"' in html
    assert 'id="kline-daily-chart"' in html
    assert 'id="kline-intraday-chart"' in html
    assert 'id="kline-tick-tape"' in html
    assert "1 分钟正式采样" in html
    assert 'id="kline-params-form"' in html
    assert "/static/focus_kline.js" in html


def test_focus_kline_api_recomputes_and_returns_market_contract(authenticated_client):
    response = authenticated_client.get("/api/focus-kline")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["initial_index"] == 100.0
    assert payload["price_tick"] == 0.001
    assert payload["price_floor"] == 0.001
    assert payload["reset_open_price"] == 10.0
    assert payload["intraday_bar_minutes"] == 1
    assert {"daily", "today", "intraday", "parameters", "limit_down", "limit_up"} <= payload.keys()
    assert payload["parameters"]["a_low_hours"] == 4.0
    assert payload["parameters"]["a_mid_hours"] == 7.0
    assert payload["parameters"]["a_high_hours"] == 9.0


def test_focus_kline_api_reopens_after_sub_ten_close_and_keeps_live_status(authenticated_client, monkeypatch):
    from datetime import date, datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from app import routes
    from app.db import connect

    now = datetime(2026, 2, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(routes, "_now", lambda timezone_name="UTC": now if timezone_name != "UTC" else now.astimezone(timezone.utc))

    connection = connect(authenticated_client.application.config["DATABASE"])
    owner_id = connection.execute(
        "SELECT id FROM users WHERE role = 'site_owner' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    start_day = date(2026, 1, 1)
    connection.executemany(
        """
        INSERT INTO focus_sessions(
            user_id, subject, mode, planned_minutes, started_at, ended_at, status
        ) VALUES (?, '退市测试', '专注', 1, ?, ?, 'completed')
        """,
        [
            (
                owner_id,
                f"{day.isoformat()}T00:00:00+00:00",
                f"{day.isoformat()}T00:01:00+00:00",
            )
            for day in (start_day + timedelta(days=index) for index in range(36))
        ],
    )
    connection.execute(
        """
        INSERT INTO focus_sessions(
            user_id, subject, mode, planned_minutes, started_at, status
        ) VALUES (?, '退市后仍专注', '专注', 30, ?, 'active')
        """,
        (owner_id, (now - timedelta(minutes=1)).isoformat()),
    )
    connection.commit()

    payload = authenticated_client.get("/api/focus-kline").get_json()
    assert payload["today"]["open"] == 10.0
    assert payload["today"]["delisted"] is False
    assert payload["intraday"]
    assert payload["status"] == "focus"
    assert payload["focus_state"] == "focus"
    assert payload["is_focusing"] is True
    connection.close()


def test_focus_kline_api_uses_live_focus_after_market_close(authenticated_client, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import routes
    from app.db import connect

    now = datetime(2026, 7, 15, 22, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(routes, "_now", lambda timezone_name="UTC": now)
    connection = connect(authenticated_client.application.config["DATABASE"])
    owner_id = connection.execute(
        "SELECT id FROM users WHERE role = 'site_owner' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    connection.execute(
        """
        INSERT INTO focus_sessions(
            user_id, subject, mode, planned_minutes, started_at, status
        ) VALUES (?, '收盘后专注', '专注', 30, ?, 'active')
        """,
        (owner_id, "2026-07-15T22:01:00+08:00"),
    )
    connection.commit()
    connection.close()

    payload = authenticated_client.get("/api/focus-kline").get_json()
    assert payload["status"] == "focus"
    assert payload["focus_state"] == "focus"
    assert payload["is_focusing"] is True
    assert payload["is_paused"] is False


def test_focus_kline_api_uses_live_focus_and_pause_during_lunch(authenticated_client, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import routes
    from app.db import connect

    now = datetime(2026, 7, 16, 12, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(routes, "_now", lambda timezone_name="UTC": now)
    connection = connect(authenticated_client.application.config["DATABASE"])
    owner_id = connection.execute(
        "SELECT id FROM users WHERE role = 'site_owner' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    cursor = connection.execute(
        """
        INSERT INTO focus_sessions(
            user_id, subject, mode, planned_minutes, started_at, status
        ) VALUES (?, '午休开始专注', '专注', 30, ?, 'active')
        """,
        (owner_id, "2026-07-16T12:05:00+08:00"),
    )
    session_id = cursor.lastrowid
    connection.commit()
    connection.close()

    focusing = authenticated_client.get("/api/focus-kline").get_json()
    assert focusing["status"] == "focus"
    assert focusing["focus_state"] == "focus"
    assert focusing["is_focusing"] is True

    connection = connect(authenticated_client.application.config["DATABASE"])
    connection.execute(
        "INSERT INTO focus_pauses(session_id, started_at) VALUES (?, ?)",
        (session_id, "2026-07-16T12:15:00+08:00"),
    )
    connection.commit()
    connection.close()

    paused = authenticated_client.get("/api/focus-kline").get_json()
    assert paused["status"] == "rest"
    assert paused["focus_state"] == "rest"
    assert paused["is_focusing"] is False
    assert paused["is_paused"] is True


def test_focus_kline_parameter_post_accepts_five_public_controls(authenticated_client):
    response = authenticated_client.post(
        "/api/focus-kline/parameters",
        json={
            "a_low_hours": 3,
            "a_mid_hours": 6,
            "a_high_hours": 8,
            "k_low_percent_per_hour": 3.0,
            "k_high_percent_per_hour": 5.5,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["parameters"] == {
        "a_low_hours": 3.0,
        "a_mid_hours": 6.0,
        "a_high_hours": 8.0,
        "k_low_percent_per_hour": 3.0,
        "k_high_percent_per_hour": 5.5,
    }


def test_focus_kline_get_is_read_only_for_the_derived_cache(authenticated_client):
    from app.db import connect

    database_path = authenticated_client.application.config["DATABASE"]
    before = connect(database_path)
    try:
        assert before.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'focus_klines'"
        ).fetchone() is None
    finally:
        before.close()

    assert authenticated_client.get("/api/focus-kline").status_code == 200
    assert authenticated_client.get("/api/focus-kline/settings").status_code == 200

    after = connect(database_path)
    try:
        assert after.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'focus_klines'"
        ).fetchone() is None
    finally:
        after.close()


def test_focus_kline_guest_can_read_but_cannot_change_parameters(authenticated_client):
    guest = authenticated_client.application.test_client()
    assert guest.get("/guest").status_code == 200
    assert guest.get("/api/focus-kline").status_code == 200
    denied = guest.post("/api/focus-kline/parameters", json={"a_low_hours": 3})
    assert denied.status_code == 403
    assert denied.get_json() == {"error": "guest_read_only"}


def test_general_settings_patch_rebuilds_kline_cache(authenticated_client):
    response = authenticated_client.patch(
        "/api/settings",
        json={"focus_kline_a_mid": 6},
    )

    assert response.status_code == 200
    payload = authenticated_client.get("/api/focus-kline").get_json()
    assert payload["parameters"]["a_mid_hours"] == 6.0


def test_kline_get_uses_persisted_study_windows(authenticated_client):
    response = authenticated_client.patch(
        "/api/settings",
        json={
            "morning_start": "09:00",
            "lunch_start": "11:00",
            "library_open": "14:00",
            "library_close": "18:00",
        },
    )

    assert response.status_code == 200
    today = authenticated_client.get("/api/focus-kline").get_json()["today"]
    assert [item["start"][11:16] for item in today["trading_sessions"]] == ["09:00", "14:00"]
    assert [item["end"][11:16] for item in today["trading_sessions"]] == ["11:00", "18:00"]


def test_kline_get_reflects_historical_source_changes_after_cache_exists(authenticated_client):
    from app.db import connect

    connection = connect(authenticated_client.application.config["DATABASE"])
    owner_id = connection.execute(
        "SELECT id FROM users WHERE role = 'site_owner' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    connection.execute(
        """
        INSERT INTO focus_sessions(
            user_id, subject, mode, planned_minutes, started_at, ended_at, status
        ) VALUES (?, '历史记录', '专注', 120, ?, ?, 'completed')
        """,
        (
            owner_id,
            "2026-01-10T00:00:00+00:00",
            "2026-01-10T01:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()

    # A write path creates the optional cache; the GET must still use source
    # rows so an imported/edited historical session cannot remain stale.
    assert authenticated_client.post("/api/focus-kline/parameters", json={}).status_code == 200
    connection = connect(authenticated_client.application.config["DATABASE"])
    try:
        connection.execute(
            "UPDATE focus_sessions SET ended_at = ? WHERE user_id = ?",
            ("2026-01-10T02:00:00+00:00", owner_id),
        )
        connection.commit()
    finally:
        connection.close()

    payload = authenticated_client.get("/api/focus-kline").get_json()
    historical = next(item for item in payload["daily"] if item["date"] == "2026-01-10")
    assert historical["focus_seconds"] == 7200
