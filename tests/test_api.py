import pytest


@pytest.fixture()
def app(tmp_path):
    from app import create_app

    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "api.sqlite3"),
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "test-password",
        "COOKIE_SECURE": False,
    })


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def authenticated_client(client):
    client.post("/login", data={"password": "test-password"})
    return client


def test_unauthenticated_dashboard_api_returns_json_401(client):
    response = client.get("/api/dashboard")

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication_required"}


def test_dashboard_payload_contains_home_and_focus_data(authenticated_client):
    response = authenticated_client.get("/api/dashboard")
    payload = response.get_json()

    assert response.status_code == 200
    assert {"now", "windows", "focus", "today_focus", "focus_investment", "heatmap", "scores", "score_history", "plans"} <= payload.keys()
    assert len(payload["heatmap"]) == 25
    assert all(len(day) == 12 for day in payload["heatmap"])
    assert payload["heatmap_visible_hours"] == list(range(0, 24, 2))
    assert payload["focus"]["today"] == []
    assert payload["focus_investment"]["daily_average_seconds"] == 0
    assert payload["focus_investment"]["today_subjects"] == []
    assert payload["focus_investment"]["yesterday_seconds"] == 0
    assert payload["focus_investment"]["subjects"] == []
    assert payload["focus_investment"]["all_time_seconds"] == 0
    assert payload["focus_investment"]["all_time_subjects"] == []
    assert [mode["subject"] for mode in payload["focus_modes"]] == ["408二轮", "数学二轮", "英语二轮", "政治一轮", "408模拟", "数学模拟"]
    assert len(payload["focus_messages"]) == 31
    assert payload["focus_messages"][-1]["text"] == "忽略该忽略的，专注该专注的"


def test_dashboard_score_history_keeps_all_submissions(authenticated_client):
    authenticated_client.post("/api/scores", json={"subject": "数学二轮", "score": 80, "target": 100, "exam_date": "2026-07-01"})
    authenticated_client.post("/api/scores", json={"subject": "英语二轮", "score": 90, "target": 100, "exam_date": "2026-07-03"})
    authenticated_client.post("/api/scores", json={"subject": "数学二轮", "score": 85, "target": 100, "exam_date": "2026-07-05"})

    payload = authenticated_client.get("/api/dashboard").get_json()

    assert len(payload["score_history"]) == 3
    assert len(payload["scores"]) == 2


def test_subject_crud_uses_ids_and_keeps_historical_score_snapshots(authenticated_client, app):
    initial = authenticated_client.get("/api/subjects").get_json()["subjects"]
    assert initial

    created = authenticated_client.post("/api/subjects", json={"name": "物理", "target": 130})
    assert created.status_code == 201
    subject = next(item for item in created.get_json()["subjects"] if item["name"] == "物理")
    subject_id = subject["id"]
    assert authenticated_client.post("/api/subjects", json={"name": "物理", "target": 120}).status_code == 409
    assert authenticated_client.post("/api/subjects", json={"name": " 物理　", "target": 120}).status_code == 409
    assert authenticated_client.post("/api/subjects", json={"name": "化学", "target": "NaN"}).get_json() == {"error": "invalid_subject"}

    renamed = authenticated_client.patch(f"/api/subjects/{subject_id}", json={"name": "物理综合", "target": 135})
    assert renamed.status_code == 200
    assert next(item for item in renamed.get_json()["subjects"] if item["id"] == subject_id) == {
        "id": subject_id,
        "name": "物理综合",
        "target": 135.0,
    }

    score = authenticated_client.post("/api/scores", json={"subject_id": subject_id, "score": 128})
    assert score.status_code == 200
    focus_items = authenticated_client.post(
        "/api/focus-items",
        json={"subject_id": subject_id, "name": "二轮"},
    )
    assert focus_items.status_code == 201
    focus_item = next(item for item in focus_items.get_json()["focus_items"] if item["subject_id"] == subject_id)
    started = authenticated_client.post("/api/focus/start", json={"focus_item_id": focus_item["id"], "mode": "专注"})
    assert started.status_code == 201
    session_id = started.get_json()["session"]["id"]
    authenticated_client.post("/api/focus/end", json={"session_id": session_id})

    deleted = authenticated_client.delete(f"/api/subjects/{subject_id}")
    assert deleted.status_code == 200
    assert all(item["id"] != subject_id for item in deleted.get_json()["subjects"])

    from app.db import connect
    database = connect(app.config["DATABASE"])
    try:
        score_row = database.execute("SELECT subject_id, subject, target FROM scores WHERE subject = '物理综合'").fetchone()
        focus_row = database.execute("SELECT subject_id, subject FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        database.close()
    assert dict(score_row) == {"subject_id": None, "subject": "物理综合", "target": 135.0}
    assert dict(focus_row) == {"subject_id": None, "subject": "物理综合 · 二轮"}


def test_focus_item_crud_and_questionnaire_order_are_scoped_by_subject(authenticated_client):
    subjects = authenticated_client.get("/api/subjects").get_json()["subjects"]
    math = next(subject for subject in subjects if subject["name"] == "数学")
    major = next(subject for subject in subjects if subject["name"] == "408")

    math_item_response = authenticated_client.post(
        "/api/focus-items",
        json={"subject_id": math["id"], "name": "冲刺"},
    )
    assert math_item_response.status_code == 201
    math_item = next(
        item
        for item in math_item_response.get_json()["focus_items"]
        if item["subject_id"] == math["id"] and item["name"] == "冲刺"
    )
    assert authenticated_client.post(
        "/api/focus-items",
        json={"subject_id": math["id"], "name": " 冲刺　"},
    ).status_code == 409

    major_item_response = authenticated_client.post(
        "/api/focus-items",
        json={"subject_id": major["id"], "name": "冲刺"},
    )
    assert major_item_response.status_code == 201
    major_item = next(
        item
        for item in major_item_response.get_json()["focus_items"]
        if item["subject_id"] == major["id"] and item["name"] == "冲刺"
    )

    renamed = authenticated_client.patch(
        f"/api/focus-items/{math_item['id']}",
        json={"subject_id": math["id"], "name": "三轮"},
    )
    assert renamed.status_code == 200
    assert any(
        item["id"] == math_item["id"] and item["label"] == "数学 · 三轮"
        for item in renamed.get_json()["focus_items"]
    )

    existing_ids = [item["id"] for item in renamed.get_json()["focus_items"]]
    requested_order = [major_item["id"], *[item_id for item_id in existing_ids if item_id != major_item["id"]]]
    ordered = authenticated_client.put(
        "/api/focus-items/order",
        json={"focus_item_ids": requested_order},
    )
    assert ordered.status_code == 200
    assert [item["id"] for item in ordered.get_json()["focus_items"]] == requested_order
    assert authenticated_client.put(
        "/api/focus-items/order",
        json={"focus_item_ids": requested_order[:-1]},
    ).get_json() == {"error": "invalid_focus_item_order"}

    deleted = authenticated_client.delete(f"/api/focus-items/{math_item['id']}")
    assert deleted.status_code == 200
    assert all(item["id"] != math_item["id"] for item in deleted.get_json()["focus_items"])


def test_unknown_subject_name_cannot_create_new_unlinked_records(authenticated_client):
    focus = authenticated_client.post("/api/focus/start", json={"subject": "不存在的科目", "mode": "专注"})
    score = authenticated_client.post("/api/scores", json={"subject": "不存在的科目", "score": 100, "target": 100})
    plan = authenticated_client.post("/api/plans", json={
        "subject": "不存在的科目",
        "week_start": "2026-07-13",
        "title": "复习",
        "target_minutes": 60,
    })

    assert focus.get_json() == {"error": "subject_not_found"}
    assert score.get_json() == {"error": "subject_not_found"}
    assert plan.get_json() == {"error": "subject_not_found"}
    assert focus.status_code == score.status_code == plan.status_code == 404


def test_dashboard_exposes_an_empty_focus_leaderboard(authenticated_client):
    payload = authenticated_client.get("/api/dashboard").get_json()

    assert payload["focus_leaderboard"] == {
        "entries": [],
        "day_count": 0,
        "today": {
            "date": payload["now"][:10],
            "seconds": 0,
            "rank": None,
            "gap_to_previous_seconds": None,
            "percentile": 0,
        },
    }


def test_start_and_end_focus_session(authenticated_client):
    started = authenticated_client.post("/api/focus/start", json={
        "subject": "408二轮",
        "mode": "专注",
        "planned_minutes": 0,
    })
    assert started.status_code == 201
    session_id = started.get_json()["session"]["id"]

    active = authenticated_client.get("/api/focus")
    assert active.get_json()["active"]["id"] == session_id
    dashboard = authenticated_client.get("/api/dashboard").get_json()
    assert dashboard["focus"]["today"][0]["id"] == session_id

    ended = authenticated_client.post("/api/focus/end", json={"session_id": session_id})
    assert ended.status_code == 200
    assert ended.get_json()["session"]["status"] == "completed"


def test_daily_settlement_snapshots_seven_hour_goal_and_is_idempotent(authenticated_client):
    authenticated_client.patch("/api/settings", json={"library_open": "00:00", "library_close": "00:01"})
    started = authenticated_client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"}).get_json()["session"]
    authenticated_client.post("/api/focus/end", json={"session_id": started["id"]})

    settled = authenticated_client.post("/api/daily-settlement", json={})
    assert settled.status_code == 201
    settled_payload = settled.get_json()
    payload = settled_payload["settlement"]
    assert payload["target_seconds"] == 7 * 3600
    assert payload["session_count"] == 1
    assert {"entries", "day_count", "today"} <= settled_payload["leaderboard"].keys()

    repeated = authenticated_client.post("/api/daily-settlement", json={})
    assert repeated.status_code == 200
    assert repeated.get_json()["idempotent"] is True
    assert {"entries", "day_count", "today"} <= repeated.get_json()["leaderboard"].keys()
    dashboard = authenticated_client.get("/api/dashboard").get_json()
    assert dashboard["daily_settlement"]["id"] == payload["id"]
    assert dashboard["can_settle_today"] is False
    blocked = authenticated_client.post("/api/focus/start", json={"subject": "英语二轮", "mode": "专注"})
    assert blocked.status_code == 409
    assert blocked.get_json() == {"error": "daily_focus_already_settled"}


def test_daily_settlement_rejects_an_active_focus(authenticated_client):
    authenticated_client.patch("/api/settings", json={"library_open": "00:00", "library_close": "00:01"})
    started = authenticated_client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"}).get_json()["session"]
    response = authenticated_client.post("/api/daily-settlement", json={})
    assert response.status_code == 409
    assert response.get_json() == {"error": "focus_still_active"}
    authenticated_client.post("/api/focus/end", json={"session_id": started["id"]})


def test_focus_pause_resume_and_lock_are_persisted(authenticated_client):
    started = authenticated_client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"}).get_json()["session"]

    paused = authenticated_client.post("/api/focus/pause", json={"session_id": started["id"], "paused": True})
    paused_again = authenticated_client.post("/api/focus/pause", json={"session_id": started["id"], "paused": True})
    assert paused.status_code == 200
    assert paused.get_json()["session"]["paused_at"] is not None
    assert paused_again.get_json()["session"]["interruption_count"] == 1

    resumed = authenticated_client.post("/api/focus/pause", json={"session_id": started["id"], "paused": False})
    assert resumed.get_json()["session"]["paused_at"] is None

    locked = authenticated_client.post("/api/focus/lock", json={"session_id": started["id"]})
    assert locked.status_code == 200
    assert locked.get_json()["session"]["focus_locked"] is True
    assert locked.get_json()["session"]["trusted"] is False
    active = authenticated_client.get("/api/dashboard").get_json()["focus"]["active"]
    assert active["focus_locked"] is True
    assert active["trusted"] is False


def test_guest_foreground_heartbeat_is_allowed(authenticated_client):
    authenticated_client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"})
    authenticated_client.get("/guest")

    heartbeat = authenticated_client.post("/api/focus/heartbeat", json={})

    assert heartbeat.status_code == 200
    assert heartbeat.get_json()["ok"] is True


def test_foreground_heartbeat_recovers_only_timeout_ended_session(authenticated_client, app):
    from datetime import datetime, timedelta, timezone

    from app.db import connect, expire_unattended_focus

    session_id = authenticated_client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"}).get_json()["session"]["id"]
    now = datetime.now(timezone.utc)
    connection = connect(app.config["DATABASE"])
    connection.execute(
        "UPDATE focus_sessions SET last_foreground_at = ? WHERE id = ?",
        ((now - timedelta(seconds=31)).isoformat(), session_id),
    )
    connection.commit()
    assert expire_unattended_focus(connection, now, 30) == session_id
    connection.close()

    recovered = authenticated_client.post("/api/focus/heartbeat", json={
        "session_id": session_id,
        "allow_recovery": True,
    }).get_json()
    assert recovered["recovered"] is True
    assert recovered["status"] == "active"

    authenticated_client.post("/api/focus/end", json={"session_id": session_id})
    not_recovered = authenticated_client.post("/api/focus/heartbeat", json={
        "session_id": session_id,
        "allow_recovery": True,
    }).get_json()
    assert not_recovered["recovered"] is False
    assert not_recovered["status"] == "completed"


def test_hidden_page_does_not_recover_timeout_ended_session(authenticated_client, app):
    from datetime import datetime, timedelta, timezone

    from app.db import connect, expire_unattended_focus

    session_id = authenticated_client.post("/api/focus/start", json={"subject": "408二轮", "mode": "专注"}).get_json()["session"]["id"]
    now = datetime.now(timezone.utc)
    connection = connect(app.config["DATABASE"])
    connection.execute(
        "UPDATE focus_sessions SET last_foreground_at = ? WHERE id = ?",
        ((now - timedelta(seconds=31)).isoformat(), session_id),
    )
    connection.commit()
    expire_unattended_focus(connection, now, 30)
    connection.close()

    heartbeat = authenticated_client.post("/api/focus/heartbeat", json={
        "session_id": session_id,
        "allow_recovery": False,
    }).get_json()
    assert heartbeat["recovered"] is False
    assert heartbeat["status"] == "completed"


def test_migration_code_exports_all_business_data_once(authenticated_client):
    session_id = authenticated_client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"}).get_json()["session"]["id"]
    authenticated_client.post("/api/focus/end", json={"session_id": session_id})
    authenticated_client.post("/api/scores", json={"subject": "数学二轮", "score": 100, "target": 130})

    issued = authenticated_client.post("/api/migration/code", json={})
    assert issued.status_code == 200
    code = issued.get_json()["code"]

    missing = authenticated_client.get("/api/migration/export")
    exported = authenticated_client.get("/api/migration/export", headers={"X-Migration-Code": code})
    repeated = authenticated_client.get("/api/migration/export", headers={"X-Migration-Code": code})

    assert missing.status_code == 401
    assert exported.status_code == 200
    assert repeated.status_code == 401
    package = exported.get_json()
    assert package["format"] == "408-dashboard-migration"
    assert package["version"] == 3
    assert package["user_subjects"]
    assert package["user_focus_items"]
    assert len(package["source_instance_id"]) == 32
    assert package["focus_sessions"][0]["id"] == session_id
    assert package["scores"][0]["subject"] == "数学"
    assert "migration_instance_id" not in package["settings"]


def test_visible_dashboard_poll_refreshes_foreground_heartbeat(authenticated_client, app):
    from app.db import connect

    session_id = authenticated_client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"}).get_json()["session"]["id"]
    connection = connect(app.config["DATABASE"])
    connection.execute("UPDATE focus_sessions SET last_foreground_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (session_id,))
    connection.commit()
    connection.close()

    authenticated_client.get("/api/dashboard")

    connection = connect(app.config["DATABASE"])
    refreshed = connection.execute("SELECT last_foreground_at FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()[0]
    connection.close()
    assert refreshed > "2026-01-01T00:00:00+00:00"


def test_negative_focus_duration_is_rejected(authenticated_client):
    response = authenticated_client.post("/api/focus/start", json={
        "subject": "数学二轮",
        "mode": "专注",
        "planned_minutes": -1,
    })

    assert response.status_code == 400
    assert response.get_json() == {"error": "planned_minutes_must_be_non_negative"}


def test_focus_start_is_idempotent_for_same_client_token(authenticated_client):
    payload = {"subject": "数学二轮", "mode": "专注", "planned_minutes": 0, "client_token": "drag-123"}
    first = authenticated_client.post("/api/focus/start", json=payload)
    second = authenticated_client.post("/api/focus/start", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["idempotent"] is True
    assert second.get_json()["session"]["id"] == first.get_json()["session"]["id"]


def test_focus_page_is_compatibility_redirect(authenticated_client):
    response = authenticated_client.get("/focus")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/owner")


def test_settings_patch_validates_time_values(authenticated_client):
    response = authenticated_client.patch("/api/settings", json={"lunch_start": "noon"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_time:lunch_start"}


def test_heatmap_visible_hours_are_validated_and_persisted(authenticated_client):
    saved = authenticated_client.patch("/api/settings", json={"heatmap_visible_hours": "6,8,10,12,14,16,18,20,22"})

    assert saved.status_code == 200
    assert saved.get_json()["settings"]["heatmap_visible_hours"] == "6,8,10,12,14,16,18,20,22"
    assert authenticated_client.get("/api/dashboard").get_json()["heatmap_visible_hours"] == [6, 8, 10, 12, 14, 16, 18, 20, 22]

    empty = authenticated_client.patch("/api/settings", json={"heatmap_visible_hours": ""})
    invalid = authenticated_client.patch("/api/settings", json={"heatmap_visible_hours": "7,8"})
    assert empty.status_code == 400
    assert invalid.status_code == 400
    assert empty.get_json() == {"error": "invalid_heatmap_visible_hours"}
    assert invalid.get_json() == {"error": "invalid_heatmap_visible_hours"}


def test_subjects_must_use_crud_api_while_focus_messages_still_persist(authenticated_client):
    saved = authenticated_client.patch("/api/settings", json={
        "focus_messages": [
            {"category": "提醒", "text": "忽略该忽略的，专注该专注的"},
            {"category": "节奏", "text": "完成当前这一页"},
        ],
    })

    assert saved.status_code == 200
    assert saved.get_json()["focus_messages"][1]["text"] == "完成当前这一页"
    dashboard = authenticated_client.get("/api/dashboard").get_json()
    assert dashboard["focus_messages"] == saved.get_json()["focus_messages"]

    legacy_subjects = authenticated_client.patch("/api/settings", json={"focus_subjects": ["数学", "数学"]})
    empty_messages = authenticated_client.patch("/api/settings", json={"focus_messages": []})
    assert legacy_subjects.status_code == 400
    assert legacy_subjects.get_json() == {"error": "subject_crud_required"}
    assert empty_messages.get_json() == {"error": "invalid_focus_messages"}


def test_guest_can_read_dashboard_but_cannot_mutate_data(client):
    assert client.get("/guest").status_code == 200
    assert client.get("/api/dashboard").status_code == 200

    focus = client.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注", "planned_minutes": 0})
    score = client.post("/api/scores", json={"subject": "数学", "score": 80, "target": 100})
    settings = client.get("/api/settings")

    assert focus.status_code == 403
    assert focus.get_json() == {"error": "guest_read_only"}
    assert score.status_code == 403
    assert score.get_json() == {"error": "guest_read_only"}
    assert settings.status_code == 403
    assert settings.get_json() == {"error": "guest_read_only"}
