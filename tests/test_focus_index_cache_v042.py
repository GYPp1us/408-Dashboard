"""Source-correction and settled-prefix guarantees for the v0.4.2 cache."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import focus_kline
from app.db import FOCUS_DYNAMICS_EFFECTIVE_KEY, connect, create_user, ensure_site_owner, init_db
from app.focus_challenge import set_challenge


LOCAL = timezone(timedelta(hours=8))


def at(day, hour=14, minute=0, second=0):
    return datetime(2026, 7, day, hour, minute, second, tzinfo=LOCAL)


@pytest.fixture
def source(tmp_path):
    connection = connect(str(tmp_path / "cached-history.sqlite3"))
    init_db(connection)
    owner = ensure_site_owner(connection, "owner", "owner@example.test", "hash")
    connection.commit()
    yield connection, owner
    connection.close()


def session(connection, owner, start, end=None, *, reporter=False):
    cursor = connection.execute(
        "INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,ended_at,status,reporter_source,last_foreground_at) "
        "VALUES (?, 'Math', 'focus', 30, ?, ?, ?, ?, ?)",
        (owner, start.isoformat(), end.isoformat() if end else None,
         "completed" if end else "active", "desktop" if reporter else None,
         start.isoformat() if reporter else None),
    )
    connection.commit()
    return cursor.lastrowid


def history(connection, owner):
    session(connection, owner, at(1, 4), at(1, 23))
    return session(connection, owner, at(2, 8), at(2, 16))


def cached(connection, owner, now=None, **options):
    return focus_kline.build_cached_focus_klines(
        connection, owner, now=now or at(5), timezone_name="Asia/Shanghai",
        bar_minutes=30, **options,
    )


def oracle(connection, owner, now=None, **options):
    # Exercise the retained full recompute without replacing the cache being
    # measured. Backup makes the comparison include the actual source DB.
    duplicate = sqlite3.connect(":memory:")
    duplicate.row_factory = sqlite3.Row
    connection.backup(duplicate)
    try:
        return focus_kline.recompute_focus_klines(
            duplicate, owner, now=now or at(5), timezone_name="Asia/Shanghai",
            bar_minutes=30, **options,
        )
    finally:
        duplicate.close()


def track_builds(monkeypatch):
    calls = []
    original = focus_kline.build_focus_klines

    def tracked(seconds, **options):
        calls.append((min(seconds), options.get("end_date")))
        return original(seconds, **options)

    monkeypatch.setattr(focus_kline, "build_focus_klines", tracked)
    return calls


def cache_rows(connection, owner):
    return {row["trading_date"]: dict(row) for row in connection.execute(
        "SELECT * FROM focus_klines WHERE user_id=? ORDER BY trading_date", (owner,)
    )}


def test_cached_history_matches_full_oracle_with_pauses_challenge_and_cutover(source):
    connection, owner = source
    old_session = history(connection, owner)
    connection.execute(
        "INSERT INTO focus_pauses(session_id,started_at,ended_at) VALUES (?,?,?)",
        (old_session, at(2, 9).isoformat(), at(2, 10).isoformat()),
    )
    connection.execute("UPDATE settings SET value=? WHERE key=?",
                       (at(3, 10).isoformat(), FOCUS_DYNAMICS_EFFECTIVE_KEY))
    connection.commit()
    session(connection, owner, at(3, 21), at(4, 9))
    set_challenge(connection, owner, True, at(2, 11), "Asia/Shanghai")
    set_challenge(connection, owner, False, at(4, 15), "Asia/Shanghai")
    expected = oracle(connection, owner)
    assert cached(connection, owner) == expected
    assert cached(connection, owner) == expected
    assert list(cache_rows(connection, owner)) == ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]
    assert not connection.in_transaction


def test_live_seconds_and_heartbeat_rebuild_only_today(source, monkeypatch):
    connection, owner = source
    history(connection, owner)
    active = session(connection, owner, at(5, 8), reporter=True)
    connection.execute("UPDATE focus_sessions SET last_foreground_at=? WHERE id=?", (at(5).isoformat(), active))
    connection.commit()
    cached(connection, owner)
    before = cache_rows(connection, owner)
    calls = track_builds(monkeypatch)
    next_tick = at(5, second=20)
    connection.execute("UPDATE focus_sessions SET last_foreground_at=? WHERE id=?", (next_tick.isoformat(), active))
    connection.commit()
    actual = cached(connection, owner, next_tick)
    assert calls == [("2026-07-05", None)]
    assert cache_rows(connection, owner) == before
    # Oracle is computed after inspecting the call count; it also calls build.
    assert actual == oracle(connection, owner, next_tick)


@pytest.mark.parametrize("correction", ["session", "pause", "import"])
def test_historical_correction_rebuilds_earliest_changed_suffix(source, monkeypatch, correction):
    connection, owner = source
    old_session = history(connection, owner)
    cached(connection, owner)
    before = cache_rows(connection, owner)
    if correction == "session":
        connection.execute("UPDATE focus_sessions SET ended_at=? WHERE id=?", (at(2, 10).isoformat(), old_session))
    elif correction == "pause":
        connection.execute("INSERT INTO focus_pauses(session_id,started_at,ended_at) VALUES (?,?,?)",
                           (old_session, at(2, 10).isoformat(), at(2, 11).isoformat()))
    else:
        session(connection, owner, at(2, 17), at(2, 18))
    connection.commit()
    calls = track_builds(monkeypatch)
    actual = cached(connection, owner)
    assert calls == [("2026-07-02", at(4).date()), ("2026-07-05", None)]
    assert cache_rows(connection, owner)["2026-07-01"] == before["2026-07-01"]
    assert actual == oracle(connection, owner)


@pytest.mark.parametrize("damage", ["gap", "intraday", "model", "unsettled", "fingerprint"])
def test_gap_corruption_and_partial_prefix_are_repaired(source, monkeypatch, damage):
    connection, owner = source
    history(connection, owner)
    cached(connection, owner)
    before = cache_rows(connection, owner)
    key = "2026-07-02"
    if damage == "gap":
        connection.execute("DELETE FROM focus_klines WHERE user_id=? AND trading_date=?", (owner, key))
    else:
        field, value = {
            "intraday": ("intraday_json", "broken JSON"),
            "model": ("model_version", "outdated-model"),
            "unsettled": ("updated_at", at(2, 9).isoformat()),
            "fingerprint": ("source_fingerprint", ""),
        }[damage]
        connection.execute(f"UPDATE focus_klines SET {field}=? WHERE user_id=? AND trading_date=?", (value, owner, key))
    connection.commit()
    calls = track_builds(monkeypatch)
    actual = cached(connection, owner, intraday_date="2026-07-05")
    assert calls == [(key, at(4).date()), ("2026-07-05", None)]
    assert cache_rows(connection, owner)["2026-07-01"] == before["2026-07-01"]
    expected = oracle(connection, owner)
    for row in expected[:-1]:
        row["intraday"] = []
    assert actual == expected


def test_selected_intraday_is_decoded_once_and_unknown_date_uses_today(source, monkeypatch):
    connection, owner = source
    history(connection, owner)
    full = cached(connection, owner)
    paths = {row["date"]: row["intraday"] for row in full}
    decoded_paths = []
    original = focus_kline.json.loads

    def tracked(value, *args, **options):
        if '"timestamp"' in value:
            decoded_paths.append(value)
        return original(value, *args, **options)

    monkeypatch.setattr(focus_kline.json, "loads", tracked)
    selected = cached(connection, owner, intraday_date="2026-07-02")
    assert len(decoded_paths) == 1
    assert selected[1]["intraday"] == paths["2026-07-02"]
    assert all(not row["intraday"] for row in selected if row["date"] != "2026-07-02")
    fallback = cached(connection, owner, intraday_date="2020-01-01")
    assert fallback[-1]["intraday"] == paths["2026-07-05"]


def test_today_challenge_enable_and_pending_disable_preserve_settled_prefix(source, monkeypatch):
    connection, owner = source
    history(connection, owner)
    cached(connection, owner)
    before = cache_rows(connection, owner)
    set_challenge(connection, owner, True, at(5, 14), "Asia/Shanghai")
    calls = track_builds(monkeypatch)
    enabled = cached(connection, owner, at(5, 15))
    assert calls == [("2026-07-05", None)]
    assert cache_rows(connection, owner) == before
    assert enabled[-1]["limit_up"] == round(enabled[-1]["previous_close"] * 1.2, 3)
    assert enabled == oracle(connection, owner, at(5, 15))
    set_challenge(connection, owner, False, at(5, 16), "Asia/Shanghai")
    calls.clear()
    disabled = cached(connection, owner, at(5, 17))
    assert calls == [("2026-07-05", None)]
    assert cache_rows(connection, owner) == before
    assert disabled == oracle(connection, owner, at(5, 17))


def test_preopen_latest_available_preserves_history_and_explicit_today_is_empty(source, monkeypatch):
    connection, owner = source
    history(connection, owner)
    expected = oracle(connection, owner, at(5, 7))
    implicit = cached(connection, owner, at(5, 7), intraday_date="latest_available")
    assert implicit[-1]["intraday"] == []
    assert implicit[-2]["intraday"] == expected[-2]["intraday"]
    assert all(not row["intraday"] for row in implicit[:-2])
    explicit = cached(connection, owner, at(5, 7), intraday_date="2026-07-05")
    assert all(not row["intraday"] for row in explicit)
    missing = cached(connection, owner, at(5, 7), intraday_date="2020-01-01")
    assert missing[-2]["intraday"] == expected[-2]["intraday"]


def test_causal_dynamics_cutover_rebuilds_only_affected_history(source, monkeypatch):
    connection, owner = source
    history(connection, owner)
    connection.execute("UPDATE settings SET value=? WHERE key=?", (at(6).isoformat(), FOCUS_DYNAMICS_EFFECTIVE_KEY))
    connection.commit()
    cached(connection, owner)
    before = cache_rows(connection, owner)
    connection.execute("UPDATE settings SET value=? WHERE key=?", (at(3, 10).isoformat(), FOCUS_DYNAMICS_EFFECTIVE_KEY))
    connection.commit()
    calls = track_builds(monkeypatch)
    actual = cached(connection, owner)
    assert calls == [("2026-07-03", at(4).date()), ("2026-07-05", None)]
    assert cache_rows(connection, owner)["2026-07-02"] == before["2026-07-02"]
    assert actual == oracle(connection, owner)


def test_rollover_settles_missing_previous_day_and_floor_reset(source, monkeypatch):
    connection, owner = source
    session(connection, owner, at(1, 23), at(1, 23, 1))
    cached(connection, owner, at(4, 21, 59), initial_price=11)
    before = cache_rows(connection, owner)
    calls = track_builds(monkeypatch)
    actual = cached(connection, owner, at(5, 7), initial_price=11)
    assert calls == [("2026-07-04", at(4).date()), ("2026-07-05", None)]
    assert cache_rows(connection, owner)["2026-07-03"] == before["2026-07-03"]
    assert actual[0]["close"] == actual[1]["previous_close"] == 10
    assert actual == oracle(connection, owner, at(5, 7), initial_price=11)


def test_parameter_and_window_change_invalidate_settled_history(source, monkeypatch):
    connection, owner = source
    history(connection, owner)
    cached(connection, owner)
    parameters = {"a_low": 2, "a_mid": 5, "a_high": 8}
    sessions = (("morning", "09:00", "12:00"), ("afternoon", "14:00", "21:00"))
    calls = track_builds(monkeypatch)
    actual = cached(connection, owner, parameters=parameters, trading_sessions=sessions)
    assert calls == [("2026-07-01", at(4).date()), ("2026-07-05", None)]
    assert actual == oracle(connection, owner, parameters=parameters, trading_sessions=sessions)


def test_cache_does_not_commit_caller_business_transaction(source):
    connection, owner = source
    history(connection, owner)
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("UPDATE focus_sessions SET ended_at=? WHERE user_id=? AND started_at=?",
                       (at(2, 9).isoformat(), owner, at(2, 8).isoformat()))
    assert cached(connection, owner)[1]["focus_seconds"] == 3600
    assert connection.in_transaction
    connection.rollback()
    assert connection.execute("SELECT ended_at FROM focus_sessions WHERE user_id=? AND started_at=?",
                              (owner, at(2, 8).isoformat())).fetchone()[0] == at(2, 16).isoformat()
    # Schema creation and cache writes were inside the caller's transaction.
    assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='focus_klines'").fetchone()


def test_caller_rollback_keeps_pending_business_write_after_cache_failure(source, monkeypatch):
    connection, owner = source
    history(connection, owner)
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("UPDATE focus_sessions SET ended_at=? WHERE user_id=? AND started_at=?",
                       (at(2, 9).isoformat(), owner, at(2, 8).isoformat()))

    def broken(*args, **options):
        raise ValueError("intentional calculation failure")

    monkeypatch.setattr(focus_kline, "build_focus_klines", broken)
    with pytest.raises(ValueError, match="intentional calculation failure"):
        cached(connection, owner)
    assert connection.in_transaction
    assert connection.execute("SELECT ended_at FROM focus_sessions WHERE user_id=? AND started_at=?",
                              (owner, at(2, 8).isoformat())).fetchone()[0] == at(2, 9).isoformat()
    connection.rollback()


def test_historical_delete_and_other_user_cache_are_isolated(source):
    connection, owner = source
    second = create_user(connection, "second", "second@example.test", "hash", at(1).isoformat())
    connection.commit()
    history(connection, owner)
    session(connection, second, at(3, 8), at(3, 16))
    cached(connection, owner)
    cached(connection, second)
    other_cache = cache_rows(connection, second)
    connection.execute("DELETE FROM focus_sessions WHERE user_id=? AND started_at=?", (owner, at(1, 4).isoformat()))
    connection.commit()
    actual = cached(connection, owner)
    assert actual[0]["date"] == "2026-07-02"
    assert "2026-07-01" not in cache_rows(connection, owner)
    assert cache_rows(connection, second) == other_cache
    assert actual == oracle(connection, owner)
