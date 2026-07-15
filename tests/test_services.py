from datetime import datetime, timedelta, timezone


def test_time_window_is_complete_after_end_time():
    from app.services import calculate_window

    result = calculate_window(
        now=datetime(2026, 7, 13, 12, 30),
        start="08:00",
        end="12:00",
    )

    assert result["state"] == "complete"
    assert result["progress"] == 1.0
    assert result["remaining_seconds"] == 0


def test_time_window_progress_is_halfway_inside_window():
    from app.services import calculate_window

    result = calculate_window(
        now=datetime(2026, 7, 13, 10, 0),
        start="08:00",
        end="12:00",
    )

    assert result["state"] == "active"
    assert result["progress"] == 0.5
    assert result["remaining_seconds"] == 7200


def test_exam_countdown_is_non_negative():
    from app.services import seconds_until_exam

    now = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
    assert seconds_until_exam(now, "2026-12-26") == int((datetime(2026, 12, 26, tzinfo=timezone.utc) - now).total_seconds())
    assert seconds_until_exam(datetime(2027, 1, 1, tzinfo=timezone.utc), "2026-12-26") == 0


def test_current_time_uses_configured_timezone():
    from app.services import current_time

    assert current_time("Asia/Shanghai").utcoffset().total_seconds() == 8 * 3600


def test_heatmap_returns_30_days_and_24_hours():
    from app.services import aggregate_focus_heatmap

    end = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
    sessions = [(end - timedelta(hours=2), end)]
    heatmap = aggregate_focus_heatmap(sessions, end)

    assert len(heatmap) == 30
    assert all(len(day) == 12 for day in heatmap)
    assert sum(sum(day) for day in heatmap) == 120


def test_heatmap_keeps_day_and_two_hour_bucket_aligned():
    from app.services import aggregate_focus_heatmap

    now = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)
    start = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)
    heatmap = aggregate_focus_heatmap([(start, start + timedelta(minutes=1))], now)

    assert heatmap[28][8] == 1
    assert sum(sum(day) for day in heatmap) == 1


def test_today_summary_counts_only_sessions_in_local_day():
    from app.services import summarize_today_focus

    now = datetime(2026, 7, 13, 18, 0, tzinfo=timezone.utc)
    sessions = [
        (datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc), datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc)),
        (datetime(2026, 7, 12, 23, 30, tzinfo=timezone.utc), datetime(2026, 7, 13, 0, 30, tzinfo=timezone.utc)),
        (datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc), datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)),
    ]

    assert summarize_today_focus(sessions, now) == {"seconds": 5400, "count": 2}


def test_focus_investment_compares_rolling_weeks_and_summarizes_subjects():
    from app.services import aggregate_focus_investment

    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    sessions = [
        ("408二轮", now - timedelta(hours=2), now),
        ("数学二轮", now - timedelta(days=2, hours=7), now - timedelta(days=2)),
        ("英语二轮", now - timedelta(days=4, hours=5), now - timedelta(days=4)),
        ("政治一轮", now - timedelta(days=10, hours=7), now - timedelta(days=10)),
    ]

    result = aggregate_focus_investment(sessions, now)

    assert result["current_seconds"] == 14 * 3600
    assert result["previous_seconds"] == 7 * 3600
    assert result["daily_average_seconds"] == 2 * 3600
    assert result["previous_daily_average_seconds"] == 3600
    assert result["today_seconds"] == 2 * 3600
    assert result["subjects"] == [
        {"subject": "数学二轮", "seconds": 7 * 3600},
        {"subject": "英语二轮", "seconds": 5 * 3600},
        {"subject": "408二轮", "seconds": 2 * 3600},
    ]


def test_focus_investment_handles_empty_data():
    from app.services import aggregate_focus_investment

    result = aggregate_focus_investment([], datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc))

    assert result == {
        "current_seconds": 0,
        "previous_seconds": 0,
        "daily_average_seconds": 0,
        "previous_daily_average_seconds": 0,
        "today_seconds": 0,
        "subjects": [],
    }
