import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db import FOCUS_DYNAMICS_EFFECTIVE_KEY, connect, ensure_site_owner, export_migration_data, init_db
from app.focus_kline import DYNAMICS_SCALE, _live_slope, build_focus_klines, build_live_focus_kline, dynamics_effective_at, recompute_focus_klines


def local(hour=0, minute=0, second=0):
    return datetime(2026, 10, 2, hour, minute, second, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_cutover_preserves_the_entire_old_prefix_and_current_quote_without_a_new_event():
    at = local(10, 15, 37)
    kwargs = {"daily_focus_seconds": {at.date(): 7 * 3600}, "user_key": 53}
    before = build_focus_klines(now=at, **kwargs)[0]
    enabled = build_focus_klines(now=at, dynamics_at=at, **kwargs)[0]
    assert enabled == before
    later = build_focus_klines(now=local(18), dynamics_at=at, **kwargs)[0]
    prefix = [point for point in later["intraday"] if datetime.fromisoformat(point["timestamp"]) <= at]
    assert json.dumps(prefix) == json.dumps(before["intraday"])
    assert all(90 <= point["price"] <= 110 for point in later["intraday"])
    assert not any(point.get("dynamics_changed") for point in later["intraday"])
    closed = build_focus_klines(now=local(22), dynamics_at=at, **kwargs)[0]
    assert closed["close"] == build_focus_klines(now=local(22), **kwargs)[0]["close"] == 100


def test_future_noise_is_exactly_ten_percent_gentler_with_the_same_rng_draw_count(monkeypatch):
    from app import focus_kline
    draws = []
    class RecordingRandom:
        def __init__(self, seed):
            self.calls = []
            draws.append((seed, self.calls))
        def gauss(self, mean, sigma):
            self.calls.append(sigma)
            return 0.0
        def random(self):
            return 0.0
    monkeypatch.setattr(focus_kline.random, "Random", RecordingRandom)
    kwargs = {"daily_focus_seconds": {local().date(): 7 * 3600}, "now":local(12), "user_key":51}
    original = build_focus_klines(**kwargs)[0]
    revised = build_focus_klines(**kwargs, dynamics_at=local(10))[0]
    old_seed, old = draws[0]; new_seed, new = draws[1]
    assert old_seed == new_seed and len(old) == len(new) == 240
    assert new[:120] == old[:120]
    assert new[120:] == pytest.approx([sigma * DYNAMICS_SCALE for sigma in old[120:]])
    assert revised["intraday"][:121] == original["intraday"][:121]
    assert revised["close"] > original["close"], "weaker newly introduced idle pressure moves the future quote less"


def test_persisted_cutover_survives_restart_and_existing_export(tmp_path):
    path = str(tmp_path / "dynamics.sqlite3")
    connection = connect(path); init_db(connection)
    initial = dynamics_effective_at(connection)
    assert initial is not None and initial.utcoffset() == timedelta(0)
    connection.execute("UPDATE settings SET value=? WHERE key=?", (local(10).isoformat(), FOCUS_DYNAMICS_EFFECTIVE_KEY)); connection.commit()
    connection.close()
    reopened = connect(path); init_db(reopened)
    assert dynamics_effective_at(reopened) == local(10)
    exported = export_migration_data(reopened, local(11))
    assert exported["settings"][FOCUS_DYNAMICS_EFFECTIVE_KEY] == local(10).isoformat()
    reopened.close()


def test_full_and_live_share_future_dynamics_and_authoritative_today_ohlc(tmp_path):
    connection = connect(str(tmp_path / "full-live.sqlite3")); init_db(connection)
    owner = ensure_site_owner(connection, "owner", "owner@example.com", "hash")
    connection.execute("UPDATE settings SET value=? WHERE key=?", (local(10).isoformat(), FOCUS_DYNAMICS_EFFECTIVE_KEY))
    connection.execute("INSERT INTO focus_sessions(user_id, subject, mode, planned_minutes, started_at, ended_at, status) VALUES (?, '408', '专注', 180, ?, ?, 'completed')", (owner, local(8).isoformat(), local(11).isoformat()))
    connection.commit()
    full = recompute_focus_klines(connection, owner, now=local(14))[-1]
    live = build_live_focus_kline(connection, owner, now=local(14))
    assert live["intraday"] == full["intraday"]
    assert live["index"]["current"] == full["close"]
    assert live["today"] == {key:full[key] for key in ("date", "open", "high", "low", "close", "trading_sessions")}
    assert (live["limit_down"], live["limit_up"]) == (full["limit_down"], full["limit_up"])
    closed = build_live_focus_kline(connection, owner, now=local(22))
    assert closed["market_active"] is False and closed["live_tick"]["per_second"] == 0
    connection.close()


def test_live_motion_uses_recent_ordinary_motion_after_a_shock_without_repeating_it_or_crossing_breaks():
    def point(minute, price, session="morning", **flags):
        return {"timestamp":local(9, minute).isoformat(), "price":price, "session":session, **flags}
    normal = [point(0, 100), point(1, 100.12)]
    expected = .12 / 60 * .35
    assert _live_slope(normal, 100) == pytest.approx(expected)
    shock = normal + [point(2, 103.12, changed=True)]
    assert _live_slope(shock, 100) == pytest.approx(expected)
    assert _live_slope(shock + [point(3, 103.12, limit_policy_changed=True)], 100) == 0
    assert _live_slope(shock + [point(3, 10, floor_reset=True)], 100) == 0
    assert _live_slope(normal + [point(2, 100.1, session="afternoon")], 100) == 0
    assert _live_slope(normal + [point(2, 100.12)], 100) == 0
