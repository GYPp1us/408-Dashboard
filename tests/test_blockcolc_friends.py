from contextlib import closing
from datetime import datetime
from time import monotonic, sleep
from zoneinfo import ZoneInfo

import pytest

from app import blockcolc_friends, create_app
from app.db import add_friend, connect, create_user


LINK = "/api/integrations/blockcolc-friends"
SELECT = "/api/friends/leaderboard-selection"
TOKEN = "bci_" + "a" * 43


@pytest.fixture
def linked_app(tmp_path, monkeypatch):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "friends.sqlite3"),
        "ADMIN_PASSWORD": "test",
    })
    owner = app.test_client()
    assert owner.post("/login", data={"password": "test"}).status_code == 302
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    remote = {
        "account": {"id": "external-owner", "name": "方块钟账号"},
        "friends": [
            {"id": "shared", "name": "已分享", "visible": {"daily": True, "status": True}, "focusing": True,
             "days": [{"date": today, "actualFocusMs": 2_222_999}]},
            {"id": "private", "name": "未分享", "visible": {"daily": False, "status": False}, "focusing": True,
             "days": [{"date": today, "actualFocusMs": 999_999}]},
        ],
    }
    stamp = datetime.now().timestamp()
    monkeypatch.setattr(blockcolc_friends, "time", lambda: stamp)
    read_tokens = []

    def read(token):
        read_tokens.append(token)
        if isinstance(remote.get("error"), str):
            raise blockcolc_friends.SyncError(remote["error"])
        return remote

    monkeypatch.setattr(blockcolc_friends, "_read_friends", read)
    return app, owner, remote, read_tokens


def test_link_merges_sources_and_selects_single_public_daily_total(linked_app):
    app, owner, _, read_tokens = linked_app
    with closing(connect(app.config["DATABASE"])) as db, db:
        owner_id = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()["id"]
        local_id = create_user(db, "local-friend", "friend@example.invalid", "fixture", datetime.now().isoformat())
        add_friend(db, owner_id, local_id, datetime.now().isoformat())
    assert owner.put(LINK, json={"token": "account password"}).status_code == 422
    assert not read_tokens
    assert owner.put(LINK, json={"token": TOKEN}).status_code == 200
    assert read_tokens == [TOKEN]
    with closing(connect(app.config["DATABASE"])) as db:
        row = db.execute("SELECT encrypted_token, friends_json FROM blockcolc_friend_links").fetchone()
        assert TOKEN not in row["encrypted_token"] and TOKEN not in row["friends_json"]
    response = owner.get("/api/friends")
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert {row["key"] for row in payload["friends"]} == {f"local:{local_id}", "blockcolc:shared", "blockcolc:private"}
    assert payload["blockcolc"]["name"] == "方块钟账号"
    private = next(row for row in payload["friends"] if row["key"] == "blockcolc:private")
    assert private["focusing"] is None and private["today_seconds"] is None
    assert "days" not in private and TOKEN not in response.get_data(as_text=True)

    assert owner.put(SELECT, json={"key": f"local:{local_id}"}).status_code == 200
    assert owner.get("/api/dashboard").get_json()["leaderboard_friend"]["key"] == f"local:{local_id}"
    assert owner.put(SELECT, json={"key": "blockcolc:shared"}).status_code == 200
    assert owner.get("/api/dashboard").get_json()["leaderboard_friend"] == {
        "key": "blockcolc:shared", "name": "已分享", "seconds": 2222,
    }
    assert owner.get("/api/friends").get_json()["selected_friend"] == "blockcolc:shared"
    assert owner.put(SELECT, json={"key": "blockcolc:unknown"}).status_code == 404
    guest = app.test_client()
    guest.get("/guest")
    assert guest.get("/api/friends").status_code == 403
    assert guest.get("/api/dashboard").get_json()["leaderboard_friend"] is None
    assert owner.put(SELECT, json={"key": "blockcolc:private"}).status_code == 200
    assert owner.get("/api/dashboard").get_json()["leaderboard_friend"] is None
    assert owner.delete(LINK).status_code == 200
    assert owner.get("/api/friends").get_json()["selected_friend"] is None
    assert [row["source"] for row in owner.get("/api/friends").get_json()["friends"]] == ["local"]


def test_revoked_token_clears_imported_data_on_next_shared_refresh(linked_app, monkeypatch):
    app, owner, remote, read_tokens = linked_app
    assert owner.put(LINK, json={"token": TOKEN}).status_code == 200
    assert owner.put(SELECT, json={"key": "blockcolc:shared"}).status_code == 200
    remote["error"] = "expired"
    stamp = blockcolc_friends.time() + blockcolc_friends.SYNC_INTERVAL
    monkeypatch.setattr(blockcolc_friends, "time", lambda: stamp + 0.01)
    owner.get("/api/dashboard")
    deadline = monotonic() + 3
    while monotonic() < deadline:
        data = owner.get("/api/friends").get_json()
        if data["blockcolc"]["status"] == "expired":
            break
        sleep(0.025)
    else:
        pytest.fail("Revoked token was not cleared")
    assert not data["friends"]
    assert owner.get("/api/dashboard").get_json()["leaderboard_friend"] is None
    assert read_tokens == [TOKEN, TOKEN]
    with closing(connect(app.config["DATABASE"])) as db:
        assert db.execute("SELECT encrypted_token FROM blockcolc_friend_links").fetchone()[0] is None
    assert owner.put(LINK, json={"token": TOKEN}).status_code == 422
    assert owner.get("/account").status_code == 200


def test_beta8_durable_focus_is_projected_at_read_time_without_a_write(linked_app, monkeypatch):
    app, owner, remote, read_tokens = linked_app
    stamp = datetime.fromisoformat("2026-11-27T00:00:45.500+08:00").timestamp()
    monkeypatch.setattr(blockcolc_friends, "time", lambda: stamp)
    friend = remote["friends"][0]
    friend["visible"]["time"] = True
    friend.update(
        estimated=True,
        startedAt="2026-11-26T15:50:00.000Z",
        endsAt="2026-11-26T15:55:00.000Z",
        updatedAt="2026-11-26T15:50:00.000Z",
        days=[{"date": "2026-11-27", "actualFocusMs": 10_700}],
    )
    assert owner.put(LINK, json={"token": TOKEN}).status_code == 200
    assert owner.put(SELECT, json={"key": "blockcolc:shared"}).status_code == 200

    def cached_friends():
        with closing(connect(app.config["DATABASE"])) as db:
            return db.execute("SELECT friends_json FROM blockcolc_friend_links").fetchone()[0]

    cached = cached_friends()
    assert "today_seconds" not in cached
    original = next(row for row in owner.get("/api/friends").get_json()["friends"] if row["id"] == "shared")
    assert original["today_seconds"] == 56
    assert "focus_window" not in original
    stamp += 2
    assert owner.get("/api/dashboard").get_json()["leaderboard_friend"]["seconds"] == 58
    assert cached_friends() == cached
    assert read_tokens == [TOKEN]

    friend.update(focusing=False, startedAt=None, endsAt=None,
                  days=[{"date": "2026-11-27", "actualFocusMs": 58_400}])
    assert owner.put(LINK, json={"token": TOKEN}).status_code == 200
    stamp += 3
    assert owner.get("/api/dashboard").get_json()["leaderboard_friend"]["seconds"] == 58


@pytest.mark.parametrize(("updates", "can_read_time", "expected"), [
    ({}, True, 27),
    ({}, False, 0),
    ({"state": "rest"}, True, 0),
    ({"stale": True}, True, 0),
    ({"startedAt": "2026-11-27T05:00:01Z"}, True, 0),
    ({"estimated": False, "updatedAt": "2026-11-27T04:58:00Z"}, True, 0),
])
def test_live_projection_respects_freshness_and_sharing(linked_app, monkeypatch, updates, can_read_time, expected):
    _, owner, remote, _ = linked_app
    stamp = datetime.fromisoformat("2026-11-27T13:00:00+08:00").timestamp()
    monkeypatch.setattr(blockcolc_friends, "time", lambda: stamp)
    friend = remote["friends"][0]
    friend["visible"]["time"] = can_read_time
    friend.update(estimated=True, startedAt="2026-11-27T04:59:33Z", days=[])
    friend.update(updates)
    assert owner.put(LINK, json={"token": TOKEN}).status_code == 200
    data = owner.get("/api/friends").get_json()
    assert next(row["today_seconds"] for row in data["friends"] if row["id"] == "shared") == expected
