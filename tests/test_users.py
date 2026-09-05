import pytest


@pytest.fixture()
def app(tmp_path):
    from app import create_app

    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "users.sqlite3"),
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "test-password",
        "ADMIN_USERNAME": "owner",
        "ADMIN_EMAIL": "owner@example.com",
        "COOKIE_SECURE": False,
    })


def login_owner(app):
    client = app.test_client()
    response = client.post("/login", data={"identifier": "owner", "password": "test-password"})
    assert response.status_code == 302
    return client


def issue_code(owner):
    response = owner.post("/api/invitations", json={})
    assert response.status_code == 200
    return response.get_json()["invitations"][0]["code"]


def register(app, code, username, email):
    client = app.test_client()
    response = client.post("/register", data={
        "invite_code": code,
        "username": username,
        "email": email,
        "password": "strong-pass-123",
    })
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/{username}")
    return client


def test_invitation_registers_user_and_routes_to_username_home(app):
    owner = login_owner(app)
    code = issue_code(owner)

    user = register(app, code, "alice", "alice@example.com")

    assert user.get("/alice/").status_code == 200
    assert app.test_client().get("/guest/").status_code == 200
    assert user.get("/account").status_code == 200
    assert user.get("/api/dashboard").get_json()["viewer"]["username"] == "alice"
    anonymous = app.test_client()
    redirect = anonymous.get("/alice")
    assert redirect.status_code == 302
    assert redirect.headers["Location"].endswith("/alice/guest")
    assert 'data-role="guest"' in anonymous.get(redirect.headers["Location"]).get_data(as_text=True)
    assert anonymous.get("/api/dashboard").get_json()["viewer"]["username"] == "alice"
    assert user.post("/register", data={"invite_code": code, "username": "another", "email": "another@example.com", "password": "strong-pass-123"}).status_code == 400


def test_usernames_are_indexed_friends_and_data_is_isolated(app):
    owner = login_owner(app)
    alice = register(app, issue_code(owner), "alice", "alice@example.com")
    bob = register(app, issue_code(owner), "bob", "bob@example.com")

    assert bob.get("/alice").status_code == 302
    assert bob.get("/alice").headers["Location"].endswith("/alice/guest")

    assert alice.get("/api/friends/search?q=bo").get_json()["users"][0]["username"] == "bob"
    assert alice.post("/api/friends", json={"username": "bob"}).status_code == 200
    assert [item["username"] for item in alice.get("/api/friends").get_json()["friends"]] == ["bob"]

    assert alice.post("/api/scores", json={"subject": "数学二轮", "score": 80, "target": 100}).status_code == 200
    assert bob.get("/api/scores").get_json()["scores"] == []

    alice_focus = alice.post("/api/focus/start", json={"subject": "数学二轮", "mode": "专注"})
    bob_focus = bob.post("/api/focus/start", json={"subject": "英语二轮", "mode": "专注"})
    assert alice_focus.status_code == 201
    assert bob_focus.status_code == 201
    friend_board = alice.get("/api/dashboard").get_json()["friends"]
    assert friend_board[0]["username"] == "bob"
    assert "delta_seconds" in friend_board[0]


def test_settings_are_initialized_from_owner_then_persisted_per_user(app):
    owner = login_owner(app)
    assert owner.patch("/api/settings", json={"morning_start": "07:30"}).status_code == 200
    owner_subjects = owner.get("/api/subjects").get_json()["subjects"]
    keep = next(item for item in owner_subjects if item["name"] == "408")
    for item in owner_subjects:
        if item["id"] != keep["id"]:
            assert owner.delete(f"/api/subjects/{item['id']}").status_code == 200
    created = owner.post("/api/subjects", json={"name": "自定义数学", "target": 130})
    assert created.status_code == 201
    custom = next(item for item in created.get_json()["subjects"] if item["name"] == "自定义数学")
    assert owner.post("/api/focus-items", json={"subject_id": custom["id"], "name": "二轮"}).status_code == 201

    alice = register(app, issue_code(owner), "alice", "alice@example.com")
    bob = register(app, issue_code(owner), "bob", "bob@example.com")
    assert alice.get("/api/settings").get_json()["settings"]["morning_start"] == "07:30"
    assert [item["subject"] for item in bob.get("/api/settings").get_json()["focus_modes"]] == ["408二轮", "408模拟", "自定义数学二轮"]

    assert alice.patch("/api/settings", json={"morning_start": "06:45"}).status_code == 200
    alice_subjects = alice.get("/api/subjects").get_json()["subjects"]
    assert alice.patch(f"/api/subjects/{alice_subjects[0]['id']}", json={"name": "英语", "target": 100}).status_code == 200
    for item in alice_subjects[1:]:
        assert alice.delete(f"/api/subjects/{item['id']}").status_code == 200

    saved = alice.get("/api/settings")
    assert saved.status_code == 200
    assert alice.get("/api/settings").get_json()["settings"]["morning_start"] == "06:45"
    assert [item["subject"] for item in alice.get("/api/dashboard").get_json()["focus_modes"]] == ["英语二轮", "英语模拟"]
    assert owner.get("/api/settings").get_json()["settings"]["morning_start"] == "07:30"
    assert bob.get("/api/settings").get_json()["settings"]["morning_start"] == "07:30"


def test_settings_subpages_include_account_controls_and_logout(app):
    owner = login_owner(app)
    system = owner.get("/settings?tab=system").get_data(as_text=True)
    account = owner.get("/settings?tab=account").get_data(as_text=True)

    assert "系统设置" in system and "账户设置" in system
    assert 'id="settings-system-panel"' in system and 'id="settings-account-panel" class="settings-tab-panel is-hidden"' in system
    assert 'id="settings-account-panel"' in account and 'id="settings-system-panel" class="settings-tab-panel is-hidden"' in account
    assert "工作时间" in system
    assert "账户信息" in account and "好友" in account
    assert 'action="/logout"' in account
    assert "发放邀请码" not in account
    assert "站长邀请码" in account

    response = owner.post("/logout")
    assert response.status_code == 302
    assert owner.get("/settings").headers["Location"].startswith("/login?")
