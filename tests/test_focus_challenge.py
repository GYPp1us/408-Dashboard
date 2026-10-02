"""Challenge limits are causal primary data, rather than a replay-wide flag."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.focus_challenge import challenge_decisions, challenge_payload, limit_at, limit_policy, set_challenge
from app.focus_kline import build_focus_klines, recompute_focus_klines


def local(hour=0, minute=0, second=0, day=1):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=ZoneInfo("Asia/Shanghai"))


def on(at):
    return [{"at": at, "limit_return": .20}]


@pytest.fixture()
def challenge_db(tmp_path):
    from app.db import connect, ensure_site_owner, init_db
    connection = connect(str(tmp_path / "challenge.sqlite3"))
    init_db(connection)
    owner = ensure_site_owner(connection, "owner", "owner@example.com", "hash")
    connection.commit()
    yield connection, owner
    connection.close()


def replay(at, segments, seed=19, policy=()):
    seconds = sum(int((min(end, at) - start).total_seconds()) for start, end in segments if start < at)
    return build_focus_klines({at.date(): seconds}, daily_segments={at.date(): segments},
                             now=at, user_key=seed, policy=policy)[0]


@pytest.mark.parametrize("focusing,limit", [(True, 110), (False, 90)])
def test_activation_at_an_ordinary_limit_preserves_exact_quote_and_entire_past_prefix(focusing, limit):
    segments = [(local(), local(22))] if focusing else []
    # Use the real seeded path to select an already touched ordinary limit,
    # with at least twelve previously accumulated hours in the focus case.
    chosen = None
    for seed in range(1, 33):
        ordinary = replay(local(20), segments, seed)
        touched = [point for point in ordinary["intraday"] if point["price"] == limit
                   and local(12) <= datetime.fromisoformat(point["timestamp"]) <= local(18)]
        # A future day's path contains the next session's opening point, while
        # replay exactly at that opening still publishes the preceding session.
        # Select a quote which was actually published at its evaluation cutoff.
        activation = next((datetime.fromisoformat(point["timestamp"]) for point in touched
                           if replay(datetime.fromisoformat(point["timestamp"]), segments, seed)["close"] == limit), None)
        if activation is not None:
            chosen = seed, activation
            break
    assert chosen is not None, "the fixture must exercise prior ordinary clipping"
    seed, activation = chosen
    before = replay(activation, segments, seed)
    after = replay(activation, segments, seed, on(activation))
    assert before["close"] == limit
    assert after["close"] == before["close"]
    assert after["intraday"][:len(before["intraday"])] == before["intraday"]
    assert json.dumps(after["intraday"][:len(before["intraday"])]) == json.dumps(before["intraday"])
    assert after["intraday"][-1]["timestamp"] == activation.isoformat()
    assert after["intraday"][-1]["price"] == limit
    assert (after["limit_down"], after["limit_up"]) == (80, 120)
    future = replay(local(22), segments, seed, on(activation))
    assert future["intraday"][:len(before["intraday"])] == before["intraday"]
    assert all(80 <= point["price"] <= 120 for point in future["intraday"])
    if focusing:
        assert future["close"] == 120, "only subsequent focus can earn the expanded upper limit"
    else:
        assert any(point["price"] < 90 for point in future["intraday"][len(before["intraday"]):])


def test_enabling_between_bars_does_not_advance_the_published_quote_or_consume_randomness(monkeypatch):
    from app import focus_kline
    original = focus_kline.random.Random
    calls = []
    class CountingRandom(original):
        def gauss(self, *args):
            calls.append("gauss")
            return super().gauss(*args)
        def random(self):
            calls.append("random")
            return super().random()
    monkeypatch.setattr(focus_kline.random, "Random", CountingRandom)
    activation = local(10, 15, 37)
    before = replay(activation, [])
    old_calls = list(calls); calls.clear()
    after = replay(activation, [], policy=on(activation))
    assert calls == old_calls
    assert after["intraday"][:len(before["intraday"])] == before["intraday"]
    assert after["close"] == before["close"]
    assert after["intraday"][-1]["timestamp"].endswith("10:15:37+08:00")


def test_already_clipped_twelve_hour_gain_is_not_reclaimed_at_activation_or_settlement():
    activation = local(18, 0, 37)
    segments = [(local(), local(12))]
    before = replay(activation, segments)
    after = replay(activation, segments, policy=on(activation))
    assert after["close"] == before["close"]
    settled = replay(local(22), segments, policy=on(activation))
    assert settled["close"] == 110, "raw +25% earned before activation remains clipped to its old +10%"
    with_future_focus = replay(local(22), [*segments, (activation, local(20, 0, 37))], policy=on(activation))
    assert with_future_focus["close"] == 120


def test_future_replays_keep_the_activation_prefix_when_focus_ends_at_its_last_minute_boundary():
    activation = local(10, 15, 37)
    segments = [(local(8), local(10, 15)), (local(10, 16), local(22))]
    before = replay(activation, segments)
    after = replay(local(11), segments, policy=on(activation))
    assert after["intraday"][:len(before["intraday"])] == before["intraday"]
    checkpoint = after["intraday"][len(before["intraday"])]
    assert checkpoint["price"] == before["close"]


@pytest.mark.parametrize("hours,expected", [(0, 80), (12, 120)])
def test_a_fully_challenged_future_day_can_settle_at_both_twenty_percent_limits(hours, expected):
    row = build_focus_klines({local().date(): hours * 3600}, now=local(22), policy=on(local() - timedelta(seconds=1)))[0]
    assert row["close"] == expected
    assert (row["limit_down"], row["limit_up"]) == (80, 120)


def test_disable_is_next_account_midnight_reenable_cancels_only_the_pending_off(challenge_db):
    connection, owner = challenge_db
    enabled = set_challenge(connection, owner, True, local(10), "Asia/Shanghai")
    disabled = set_challenge(connection, owner, False, local(11), "Asia/Shanghai")
    assert disabled["desired_enabled"] is False and disabled["active_today"] is True
    assert disabled["pending_disable"] is True
    assert disabled["effective_at"] == local(day=2).isoformat()
    assert disabled["revision"] > enabled["revision"]
    policy = limit_policy(challenge_decisions(connection, owner))
    assert limit_at(policy, local(23, 59, 59)) == .20
    assert limit_at(policy, local(day=2)) == .10
    ordinary_tomorrow = challenge_payload(challenge_decisions(connection, owner), local(day=2), "Asia/Shanghai")
    assert ordinary_tomorrow["active_today"] is False and ordinary_tomorrow["pending_disable"] is False
    assert ordinary_tomorrow["revision"] == disabled["revision"]
    assert ordinary_tomorrow["as_of"] > disabled["as_of"]
    reenabled = set_challenge(connection, owner, True, local(12), "Asia/Shanghai")
    assert reenabled["pending_disable"] is False
    assert reenabled["revision"] > disabled["revision"]
    policy = limit_policy(challenge_decisions(connection, owner))
    assert limit_at(policy, local(day=2)) == .20
    assert len(policy) == 1, "cancelling a future off must not create another intraday checkpoint"


def test_idempotency_persistence_account_isolation_and_export(challenge_db):
    from app.db import create_user, export_migration_data
    connection, owner = challenge_db
    other = create_user(connection, "other", "other@example.com", "hash", local().isoformat())
    connection.commit()
    first = set_challenge(connection, owner, True, local(10), "Asia/Shanghai")
    again = set_challenge(connection, owner, True, local(11), "Asia/Shanghai")
    assert again["revision"] == first["revision"]
    assert len(challenge_decisions(connection, owner)) == 1
    assert challenge_payload(challenge_decisions(connection, other), local(12), "Asia/Shanghai")["active_today"] is False
    connection.commit()
    exported = export_migration_data(connection, local(12))
    assert exported["version"] == 3
    assert exported["focus_kline_challenge_events"] == challenge_decisions(connection, owner)
    assert exported["focus_kline_challenge_events"][0]["changed_at"].endswith("+00:00")


def test_reenable_after_midnight_preserves_the_intervening_ordinary_day_prefix(challenge_db):
    connection, owner = challenge_db
    set_challenge(connection, owner, True, local(10), "Asia/Shanghai")
    set_challenge(connection, owner, False, local(11), "Asia/Shanghai")
    now = local(10, 15, 37, day=2)
    seconds = {local().date(): 0, now.date(): 0}
    before = build_focus_klines(seconds, now=now, user_key=owner, policy=limit_policy(challenge_decisions(connection, owner)))
    set_challenge(connection, owner, True, now, "Asia/Shanghai")
    policy = limit_policy(challenge_decisions(connection, owner))
    after = build_focus_klines(seconds, now=now, user_key=owner, policy=policy)
    assert limit_at(policy, local(9, day=2)) == .10
    assert limit_at(policy, now) == .20
    assert after[0] == before[0]
    assert after[1]["intraday"][:len(before[1]["intraday"])] == before[1]["intraday"]
    assert after[1]["close"] == before[1]["close"]


def test_midnight_reconciles_an_incomplete_challenge_cache_once_then_uses_settled_close(challenge_db, monkeypatch):
    from app import focus_kline
    connection, owner = challenge_db
    set_challenge(connection, owner, True, local(10), "Asia/Shanghai")
    recompute_focus_klines(connection, owner, now=local(14))
    rebuild = focus_kline.build_focus_klines
    historical_suffixes = []
    def tracked(*args, **kwargs):
        if kwargs.get("end_date") is not None:
            historical_suffixes.append((kwargs["now"], kwargs["end_date"]))
        return rebuild(*args, **kwargs)
    monkeypatch.setattr(focus_kline, "build_focus_klines", tracked)
    first = focus_kline.build_live_focus_kline(connection, owner, now=local(9, day=2))
    full = build_focus_klines({local().date(): 0}, now=local(9, day=2), user_key=owner,
                             policy=limit_policy(challenge_decisions(connection, owner)))
    assert first["previous_close"] == full[-1]["previous_close"]
    assert first["intraday"] == full[-1]["intraday"]
    assert first["challenge"]["active_today"] is True
    second = focus_kline.build_live_focus_kline(connection, owner, now=local(9, 0, 15, day=2))
    assert second["previous_close"] == first["previous_close"]
    assert historical_suffixes == [(local(9, day=2), local(9, day=2).date() - timedelta(days=1))]


def test_off_uses_account_midnight_and_stored_effective_instant_survives_timezone_changes(challenge_db):
    connection, owner = challenge_db
    now = datetime(2026, 10, 1, 23, 55, tzinfo=ZoneInfo("America/New_York"))
    set_challenge(connection, owner, True, now, "America/New_York")
    off = set_challenge(connection, owner, False, now + timedelta(minutes=1), "America/New_York")
    assert off["effective_at"] == "2026-10-02T00:00:00-04:00"
    policy = limit_policy(challenge_decisions(connection, owner))
    assert limit_at(policy, datetime(2026, 10, 2, 3, 59, tzinfo=timezone.utc)) == .20
    assert limit_at(policy, datetime(2026, 10, 2, 4, tzinfo=timezone.utc)) == .10


def test_post_close_enable_and_pending_cancellation_preserve_finished_prices_and_floor_reset():
    close = local(22)
    ordinary = build_focus_klines({close.date(): 0}, now=close, initial_price=10.5)[0]
    enabled = build_focus_klines({close.date(): 0}, now=local(23), initial_price=10.5, policy=on(local(22, 30)))[0]
    assert enabled["intraday"] == ordinary["intraday"]
    assert enabled["close"] == ordinary["close"] == 10
    assert enabled["intraday"][-1]["floor_reset"] is True


@pytest.fixture()
def challenge_client(tmp_path, monkeypatch):
    from app import create_app, routes
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "challenge-routes.sqlite3"),
                      "SECRET_KEY": "test-secret", "ADMIN_PASSWORD": "test-password", "COOKIE_SECURE": False})
    client = app.test_client()
    client.post("/login", data={"password": "test-password"})
    clock = {"now": local(18, 0, 37)}
    monkeypatch.setattr(routes, "_now", lambda timezone_name="UTC": clock["now"])
    return client, clock


def test_api_full_live_agree_and_activation_does_not_rewrite_cached_history(challenge_client, monkeypatch):
    from app import focus_kline
    from app.db import connect
    client, clock = challenge_client
    connection = connect(client.application.config["DATABASE"])
    with client.session_transaction() as session:
        owner = session["user_id"]
    connection.execute("INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,ended_at,status) VALUES (?, 'math', 'focus', 720, ?, ?, 'completed')",
                       (owner, local(day=1).isoformat(), local(12, day=1).isoformat()))
    connection.execute("INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,ended_at,status) VALUES (?, 'math', 'focus', 1, ?, ?, 'completed')",
                       (owner, "2026-09-30T00:00:00+08:00", "2026-09-30T00:01:00+08:00"))
    connection.commit()
    before = client.get("/api/focus-kline/live").get_json()
    past = connection.execute("SELECT * FROM focus_klines WHERE user_id=? AND trading_date='2026-09-30'", (owner,)).fetchone()
    enabled = client.patch("/api/focus-kline/challenge", json={"enabled": True})
    assert enabled.status_code == 200
    def no_history_rebuild(*args, **kwargs):
        raise AssertionError("enabling today must not rebuild already settled history on every live poll")
    monkeypatch.setattr(focus_kline, "recompute_focus_klines", no_history_rebuild)
    live = client.get("/api/focus-kline/live").get_json()
    full = client.get("/api/focus-kline").get_json()
    assert live["challenge"] == full["challenge"] == enabled.get_json()["challenge"]
    assert live["index"]["current"] == before["index"]["current"] == full["index"]["current"]
    assert live["intraday"][:len(before["intraday"])] == before["intraday"]
    assert live["intraday"] == full["intraday"]
    assert live["limit_up"] == full["limit_up"]
    assert live["limit_down"] == full["limit_down"]
    assert dict(connection.execute("SELECT * FROM focus_klines WHERE id=?", (past["id"],)).fetchone()) == dict(past)
    connection.close()


def test_api_disable_keeps_today_path_and_caps_then_restores_ordinary_limits_next_day(challenge_client):
    client, clock = challenge_client
    enabled = client.patch("/api/focus-kline/challenge", json={"enabled": True}).get_json()["challenge"]
    before = client.get("/api/focus-kline/live").get_json()
    off = client.patch("/api/focus-kline/challenge", json={"enabled": False}).get_json()["challenge"]
    after = client.get("/api/focus-kline/live").get_json()
    assert off["desired_enabled"] is False and off["pending_disable"] is True
    assert off["revision"] > enabled["revision"]
    assert after["intraday"] == before["intraday"]
    assert after["index"] == before["index"]
    assert after["limit_up"] == before["limit_up"]
    assert after["limit_down"] == before["limit_down"]
    clock["now"] = local(9, day=2)
    live = client.get("/api/focus-kline/live").get_json()
    full = client.get("/api/focus-kline").get_json()
    assert live["challenge"] == full["challenge"]
    assert live["challenge"]["current_limit_percent"] == 10
    assert live["challenge"]["pending_disable"] is False
    assert live["challenge"]["revision"] == off["revision"]
    assert live["intraday"] == full["intraday"]
    assert live["previous_close"] == full["today"]["previous_close"]
    assert live["limit_up"] == full["limit_up"]
    assert live["limit_down"] == full["limit_down"]


@pytest.mark.parametrize("payload", [{}, {"enabled": 1}, {"enabled": "true"}, {"enabled": None}, [], {"enabled": True, "user_id": 999}])
def test_api_rejects_non_boolean_or_foreign_account_payloads(challenge_client, payload):
    client, _clock = challenge_client
    assert client.patch("/api/focus-kline/challenge", json=payload).status_code == 400
    assert client.get("/api/focus-kline/challenge").get_json()["challenge"]["revision"] == 0


def test_guest_can_read_challenge_policy_but_cannot_mutate_it(challenge_client):
    client, _clock = challenge_client
    assert client.patch("/api/focus-kline/challenge", json={"enabled": True}).status_code == 200
    client.get("/guest")
    assert client.get("/api/focus-kline/challenge").get_json()["challenge"]["active_today"] is True
    assert client.patch("/api/focus-kline/challenge", json={"enabled": False}).status_code == 403


def test_challenge_read_without_login_requires_authentication(challenge_client):
    client, _clock = challenge_client
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/api/focus-kline/challenge").status_code == 401
    assert client.patch("/api/focus-kline/challenge", json={"enabled": True}).status_code == 401


def test_patch_only_changes_authenticated_account_even_with_a_foreign_query_id(challenge_client):
    from app.db import connect, create_user
    client, clock = challenge_client
    connection = connect(client.application.config["DATABASE"])
    other = create_user(connection, "other", "other@example.com", "hash", clock["now"].isoformat())
    connection.commit()
    assert client.patch(f"/api/focus-kline/challenge?user_id={other}", json={"enabled": True}).status_code == 200
    assert challenge_decisions(connection, other) == []
    with client.session_transaction() as session:
        session.update(viewing_as_guest=True, profile_user_id=other)
    assert client.get("/api/focus-kline/challenge").get_json()["challenge"]["active_today"] is False
    assert client.patch("/api/focus-kline/challenge", json={"enabled": True}).status_code == 403
    connection.close()
