from datetime import datetime, timedelta, timezone


def test_close_return_follows_the_three_anchor_curve():
    from app.focus_kline import close_return

    assert close_return(0) == -0.10
    assert close_return(4) == -0.10
    assert round(close_return(5), 6) == round(-0.10 + (0.10 / 3), 6)
    assert close_return(7) == 0.0
    assert close_return(8) == 0.05
    assert close_return(9) == 0.10
    assert close_return(24) == 0.10


def test_close_return_accepts_custom_public_parameters():
    from app.focus_kline import close_return

    parameters = {
        "a_low": 2,
        "a_mid": 4,
        "a_high": 8,
        "k_low": 0.02,
        "k_high": 0.04,
    }
    assert close_return(3, parameters) == -0.08
    assert close_return(6, parameters) == 0.08


def test_build_fills_missing_days_and_keeps_prices_on_the_tick():
    from app.focus_kline import build_focus_klines

    now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    rows = build_focus_klines(
        {"2026-07-13": 7 * 3600, "2026-07-15": 9 * 3600},
        now=now,
        user_key=42,
    )

    assert [row["date"] for row in rows] == ["2026-07-13", "2026-07-14", "2026-07-15"]
    assert rows[1]["focus_seconds"] == 0
    assert rows[0]["close"] == 100.0
    assert all(round(row[field], 3) == row[field] for row in rows for field in ("open", "high", "low", "close"))
    assert all(row["low"] <= row["open"] <= row["high"] for row in rows)
    assert all(row["low"] <= row["close"] <= row["high"] for row in rows)
    assert all(row["low"] >= round(row["previous_close"] * 0.9, 3) for row in rows)
    assert all(row["high"] <= round(row["previous_close"] * 1.1, 3) for row in rows)


def test_build_intraday_path_is_stable_bounded_and_marks_state_changes():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    segments = [
        (day.replace(hour=2), day.replace(hour=8)),
        (day.replace(hour=8), day.replace(hour=10)),
        (day.replace(hour=12), day.replace(hour=13, minute=30)),
        (day.replace(hour=13, minute=30), day.replace(hour=14)),
    ]
    kwargs = {
        "daily_focus_seconds": {"2026-07-15": 3 * 3600},
        "daily_segments": {"2026-07-15": segments},
        "now": day.replace(hour=23),
        "user_key": 7,
        "bar_minutes": 30,
    }
    first = build_focus_klines(**kwargs)[0]
    second = build_focus_klines(**kwargs)[0]

    assert first["intraday"] == second["intraday"]
    assert first["open"] > 100.0
    assert first["pre_open_focus_seconds"] == 6 * 3600
    assert first["lunch_focus_seconds"] == 90 * 60
    assert first["focus_seconds"] == 10 * 3600
    assert first["close"] == 110.0
    assert any(point["changed"] for point in first["intraday"])
    assert {point["state"] for point in first["intraday"]} == {"focus", "idle"}
    assert all(90.0 <= point["price"] <= 110.0 for point in first["intraday"])
    for point in first["intraday"]:
        at = datetime.fromisoformat(point["timestamp"])
        minute_of_day = at.hour * 60 + at.minute
        assert (8 * 60 <= minute_of_day <= 12 * 60) or (13 * 60 + 30 <= minute_of_day <= 22 * 60)
        assert not (12 * 60 < minute_of_day < 13 * 60 + 30)


def test_default_intraday_path_samples_every_minute():
    from app.focus_kline import DEFAULT_BAR_MINUTES, build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    row = build_focus_klines({day.date(): 0}, now=day.replace(hour=23), user_key=19)[0]
    points = row["intraday"]

    assert DEFAULT_BAR_MINUTES == 1
    assert len(points) == 752
    assert (datetime.fromisoformat(points[1]["timestamp"]) - datetime.fromisoformat(points[0]["timestamp"])).total_seconds() == 60
    assert points[240]["timestamp"].endswith("12:00:00+00:00")
    assert points[241]["timestamp"].endswith("13:30:00+00:00")
    assert points[-1]["price"] == row["close"]


def test_live_path_stops_at_last_complete_minute():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    row = build_focus_klines(
        {day.date(): 0},
        daily_segments={day.date(): []},
        now=day.replace(hour=9, minute=12, second=47),
        user_key=23,
    )[0]

    latest = datetime.fromisoformat(row["intraday"][-1]["timestamp"])
    assert (latest.hour, latest.minute, latest.second) == (9, 12, 0)


def test_idle_day_declines_across_market_hours_not_at_opening():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    row = build_focus_klines(
        {day.date(): 0},
        daily_segments={day.date(): []},
        now=day.replace(hour=22),
        user_key=17,
    )[0]
    points = row["intraday"]

    assert points[0]["price"] == 100.0
    assert points[1]["price"] > 96.0  # no instant jump to the -10% close anchor
    assert points[240]["price"] > 90.0  # only four of 12.5 trading hours have elapsed
    assert points[241]["price"] == points[240]["price"]  # lunch itself is not a market bar
    assert abs(points[-1]["price"] - points[-2]["price"]) < 0.2
    assert row["close"] == row["limit_down"] == 90.0


def test_aggregate_only_history_converges_without_a_closing_spike():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    row = build_focus_klines({day.date(): 9 * 3600}, now=day.replace(hour=22), user_key=18)[0]
    points = row["intraday"]

    assert points[1]["price"] > 98.0
    assert points[240]["price"] > 100.0
    assert abs(points[-1]["price"] - points[-2]["price"]) < 0.2
    assert row["close"] == row["limit_up"] == 110.0


def test_market_projection_ignores_wall_clock_hours_before_open():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    common = {
        "daily_focus_seconds": {day.date(): 0},
        "daily_segments": {day.date(): []},
        "now": day.replace(hour=23),
        "user_key": 29,
    }
    morning_market = build_focus_klines(
        **common,
        trading_sessions=(("morning", "08:00", "09:00"), ("afternoon", "09:30", "10:30")),
    )[0]
    evening_market = build_focus_klines(
        **common,
        trading_sessions=(("morning", "20:00", "21:00"), ("afternoon", "21:30", "22:30")),
    )[0]

    assert [point["price"] for point in morning_market["intraday"]] == [
        point["price"] for point in evening_market["intraday"]
    ]


def test_low_fundamental_day_touches_limit_and_rebounds_inside_band():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    row = build_focus_klines(
        {day.date(): 0},
        now=day.replace(hour=22),
        user_key=1,
        bar_minutes=10,
    )[0]
    prices = [point["price"] for point in row["intraday"]]
    touches = [index for index, price in enumerate(prices) if price == row["limit_down"]]
    rebound_prices = {price for price in prices if price > row["limit_down"]}

    assert row["close"] == 90.0
    assert min(prices) == row["limit_down"]
    assert max(prices) > row["limit_down"]
    assert all(row["limit_down"] <= price <= row["limit_up"] for price in prices)
    assert len(touches) >= 2
    assert len({right - left for left, right in zip(touches, touches[1:])}) > 1
    assert len(rebound_prices) >= 3


def test_high_fundamental_day_touches_upper_limit_and_rebounds_inside_band():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    row = build_focus_klines(
        {day.date(): 24 * 3600},
        daily_segments={day.date(): [(day, day.replace(hour=22))]},
        now=day.replace(hour=22),
        user_key=18,
        bar_minutes=10,
    )[0]
    prices = [point["price"] for point in row["intraday"]]

    assert row["close"] == row["limit_up"]
    assert max(prices) == row["limit_up"]
    assert min(prices) < row["limit_up"]
    assert all(row["limit_down"] <= price <= row["limit_up"] for price in prices)


def test_post_close_focus_does_not_carry_into_next_open():
    from app.focus_kline import build_focus_klines

    first_day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    second_day = first_day + timedelta(days=1)
    rows = build_focus_klines(
        {first_day.date(): 0, second_day.date(): 0},
        daily_segments={
            first_day.date(): [(first_day.replace(hour=22), first_day.replace(hour=23, minute=30))],
            second_day.date(): [],
        },
        now=second_day.replace(hour=23),
        user_key=8,
    )

    assert rows[0]["focus_seconds"] == 0
    assert rows[0]["after_close_focus_seconds"] == 90 * 60
    assert rows[1]["pre_open_focus_seconds"] == 0
    assert rows[1]["open"] == rows[0]["close"]


def test_normal_off_market_rest_is_neutral_for_opening_gap():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    row = build_focus_klines(
        {day.date(): 0},
        daily_segments={day.date(): []},
        now=day.replace(hour=22),
    )[0]

    assert row["pre_open_focus_seconds"] == 0
    assert row["pre_open_gap_pct"] == 0.0
    assert row["open"] == row["previous_close"]


def test_lunch_focus_is_a_gap_and_never_an_off_session_point():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    rows = build_focus_klines(
        {day.date(): 2 * 3600},
        daily_segments={day.date(): [(day.replace(hour=12), day.replace(hour=13, minute=30))]},
        now=day.replace(hour=22),
        user_key=9,
        bar_minutes=30,
    )
    row = rows[0]
    timestamps = [datetime.fromisoformat(point["timestamp"]) for point in row["intraday"]]
    assert row["lunch_focus_seconds"] == 90 * 60
    market_minutes = [at.hour * 60 + at.minute for at in timestamps]
    assert all((8 * 60 <= value <= 12 * 60) or (13 * 60 + 30 <= value <= 22 * 60) for value in market_minutes)
    assert all(not (12 * 60 < value < 13 * 60 + 30) for value in market_minutes)
    assert any(at.hour == 12 and at.minute == 0 for at in timestamps)
    assert any(at.hour == 13 and at.minute == 30 for at in timestamps)


def test_current_day_uses_live_path_until_market_close():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    segments = [
        (day.replace(hour=2), day.replace(hour=8)),
        (day.replace(hour=8), day.replace(hour=9)),
    ]
    row = build_focus_klines(
        {day.date(): 0},
        daily_segments={day.date(): segments},
        now=day.replace(hour=9, minute=30),
        user_key=2,
        bar_minutes=10,
    )[0]

    # F is already 7h, whose settled anchor would be 100.000, but the
    # market is still open and the visible close is the live noisy path.
    assert row["status"] == "active"
    assert row["focus_seconds"] == 7 * 3600
    assert row["intraday"]
    assert row["close"] == row["intraday"][-1]["price"]
    assert row["close"] != 100.0


def test_custom_anchor_parameters_rebuild_the_intraday_anchor_path():
    from app.focus_kline import build_focus_klines

    day = datetime(2026, 7, 15, tzinfo=timezone.utc)
    segments = [(day.replace(hour=8), day.replace(hour=9))]
    common = {
        "daily_focus_seconds": {day.date(): 4 * 3600},
        "daily_segments": {day.date(): segments},
        "now": day.replace(hour=11),
        "user_key": 11,
        "bar_minutes": 10,
    }
    defaults = build_focus_klines(**common)[0]
    custom = build_focus_klines(
        **common,
        parameters={"a_low": 1, "a_mid": 2, "a_high": 3, "k_low": 0.1, "k_high": 0.1},
    )[0]
    assert defaults["intraday"] != custom["intraday"]


def test_close_below_ten_reopens_at_ten_and_can_recover():
    from app.focus_kline import build_focus_klines

    now = datetime(2026, 8, 1, 23, 0, tzinfo=timezone.utc)
    start = now.date() - timedelta(days=35)
    daily = {start + timedelta(days=index): 0 for index in range(36)}
    rows = build_focus_klines(daily, now=now)

    first_below = next(index for index, row in enumerate(rows) if row["delisted"])
    assert rows[first_below]["close"] < 10.0
    assert rows[first_below]["intraday"]
    assert rows[first_below + 1]["open"] == 10.0
    assert rows[first_below + 1]["previous_close"] == 10.0
    assert rows[first_below + 1]["intraday"]
    daily[start + timedelta(days=first_below + 1)] = 9 * 3600
    recovered = build_focus_klines(daily, now=now)
    assert recovered[first_below + 1]["open"] == 10.0
    assert recovered[first_below + 1]["close"] == 11.0
    assert recovered[first_below + 1]["delisted"] is False
    assert all(row["high"] >= row["open"] >= row["low"] for row in rows)


def test_group_segments_splits_midnight_crossing_focus():
    from app.focus_kline import group_focus_segments_by_day

    start = datetime(2026, 7, 14, 23, 30, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc)
    seconds, by_day = group_focus_segments_by_day([(start, end)])

    assert seconds == {"2026-07-14": 1800, "2026-07-15": 3600}
    assert by_day["2026-07-14"][0][1].hour == 0
    assert by_day["2026-07-15"][0][0].hour == 0


def test_validate_setting_payload_uses_storage_keys_and_rejects_bad_anchors():
    from app.focus_kline import SETTING_KEYS, validate_setting_payload

    values = validate_setting_payload(
        {
            "a_low_hours": 3,
            "a_mid_hours": 6,
            "a_high_hours": 8,
            "k_low_percent_per_hour": 4,
            "k_high_percent_per_hour": 6,
        }
    )
    assert values[SETTING_KEYS["a_low_hours"]] == "3"
    assert values[SETTING_KEYS["k_high_percent_per_hour"]] == "6"

    try:
        validate_setting_payload({"a_low_hours": 9, "a_mid_hours": 6, "a_high_hours": 8})
    except ValueError as error:
        assert str(error) == "invalid_focus_kline_anchors"
    else:
        raise AssertionError("invalid anchors should be rejected")


def test_recompute_reads_pauses_and_rebuilds_all_history(tmp_path):
    from app.db import connect, ensure_site_owner, init_db
    from app.focus_kline import list_focus_klines, recompute_focus_klines

    connection = connect(str(tmp_path / "kline.sqlite3"))
    init_db(connection)
    user_id = ensure_site_owner(connection, "owner", "owner@example.com", "hash")
    day = datetime(2026, 7, 13, tzinfo=timezone.utc)
    connection.execute(
        """
        INSERT INTO focus_sessions(user_id, subject, mode, planned_minutes, started_at, ended_at, status)
        VALUES (?, '408', '专注', 180, ?, ?, 'completed')
        """,
        (user_id, day.replace(hour=8).isoformat(), day.replace(hour=11).isoformat()),
    )
    session_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    connection.execute(
        "INSERT INTO focus_pauses(session_id, started_at, ended_at) VALUES (?, ?, ?)",
        (session_id, day.replace(hour=9).isoformat(), day.replace(hour=10).isoformat()),
    )
    connection.commit()

    now = datetime(2026, 7, 14, 20, tzinfo=timezone.utc)
    rows = recompute_focus_klines(connection, user_id, now=now, timezone_name="UTC")
    assert rows[0]["focus_seconds"] == 2 * 3600
    assert len(list_focus_klines(connection, user_id)) == 2

    old_close = rows[-1]["close"]
    connection.execute(
        "UPDATE focus_sessions SET ended_at = ? WHERE id = ?",
        (day.replace(hour=15).isoformat(), session_id),
    )
    connection.commit()
    refreshed = recompute_focus_klines(connection, user_id, now=now, timezone_name="UTC")
    assert refreshed[0]["focus_seconds"] == 6 * 3600
    assert refreshed[-1]["close"] != old_close
    assert list_focus_klines(connection, user_id)[0]["intraday"]
    connection.close()
