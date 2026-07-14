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
    assert {"now", "windows", "focus", "today_focus", "heatmap", "scores", "score_history", "plans"} <= payload.keys()
    assert len(payload["heatmap"]) == 30
    assert all(len(day) == 12 for day in payload["heatmap"])
    assert payload["focus"]["today"] == []
    assert [mode["subject"] for mode in payload["focus_modes"]] == ["408二轮", "数学二轮", "英语二轮", "政治一轮", "408模拟", "数学模拟"]


def test_dashboard_score_history_keeps_all_submissions(authenticated_client):
    authenticated_client.post("/api/scores", json={"subject": "数学", "score": 80, "target": 100, "exam_date": "2026-07-01"})
    authenticated_client.post("/api/scores", json={"subject": "英语", "score": 90, "target": 100, "exam_date": "2026-07-03"})
    authenticated_client.post("/api/scores", json={"subject": "数学", "score": 85, "target": 100, "exam_date": "2026-07-05"})

    payload = authenticated_client.get("/api/dashboard").get_json()

    assert len(payload["score_history"]) == 3
    assert len(payload["scores"]) == 2


def test_start_and_end_focus_session(authenticated_client):
    started = authenticated_client.post("/api/focus/start", json={
        "subject": "数据结构",
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


def test_negative_focus_duration_is_rejected(authenticated_client):
    response = authenticated_client.post("/api/focus/start", json={
        "subject": "数学",
        "mode": "专注",
        "planned_minutes": -1,
    })

    assert response.status_code == 400
    assert response.get_json() == {"error": "planned_minutes_must_be_non_negative"}


def test_focus_start_is_idempotent_for_same_client_token(authenticated_client):
    payload = {"subject": "数学", "mode": "专注", "planned_minutes": 0, "client_token": "drag-123"}
    first = authenticated_client.post("/api/focus/start", json=payload)
    second = authenticated_client.post("/api/focus/start", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["idempotent"] is True
    assert second.get_json()["session"]["id"] == first.get_json()["session"]["id"]


def test_focus_page_is_compatibility_redirect(authenticated_client):
    response = authenticated_client.get("/focus")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_settings_patch_validates_time_values(authenticated_client):
    response = authenticated_client.patch("/api/settings", json={"lunch_start": "noon"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_time:lunch_start"}
