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


def test_heatmap_returns_at_least_25_days_and_24_hours():
    from app.services import aggregate_focus_heatmap

    end = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
    sessions = [(end - timedelta(hours=2), end)]
    heatmap = aggregate_focus_heatmap(sessions, end)

    assert len(heatmap) == 25
    assert all(len(day) == 12 for day in heatmap)
    assert sum(sum(day) for day in heatmap) == 120


def test_heatmap_keeps_day_and_two_hour_bucket_aligned():
    from app.services import aggregate_focus_heatmap

    now = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)
    start = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)
    heatmap = aggregate_focus_heatmap([(start, start + timedelta(minutes=1))], now)

    assert heatmap[23][8] == 1
    assert sum(sum(day) for day in heatmap) == 1


def test_heatmap_includes_every_day_back_to_the_first_record():
    from app.services import aggregate_focus_heatmap

    now = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)
    start = now - timedelta(days=40, hours=4)
    heatmap = aggregate_focus_heatmap([(start, start + timedelta(minutes=30))], now)

    assert len(heatmap) == 41
    assert heatmap[0][8] == 30
    assert sum(sum(day) for day in heatmap) == 30


def test_today_summary_counts_only_sessions_in_local_day():
    from app.services import summarize_today_focus

    now = datetime(2026, 7, 13, 18, 0, tzinfo=timezone.utc)
    sessions = [
        (datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc), datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc)),
        (datetime(2026, 7, 12, 23, 30, tzinfo=timezone.utc), datetime(2026, 7, 13, 0, 30, tzinfo=timezone.utc)),
        (datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc), datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)),
    ]

    assert summarize_today_focus(sessions, now) == {"seconds": 5400, "count": 2}


def test_focus_investment_uses_the_latest_recorded_days_and_actual_day_counts():
    from app.services import aggregate_focus_investment

    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    sessions = [
        ("408二轮", now - timedelta(hours=2), now),
        ("数学二轮", now - timedelta(days=1, hours=7), now - timedelta(days=1)),
        ("英语二轮", now - timedelta(days=4, hours=5), now - timedelta(days=4)),
        ("政治一轮", now - timedelta(days=10, hours=7), now - timedelta(days=10)),
    ]

    result = aggregate_focus_investment(sessions, now)

    assert result["current_seconds"] == 21 * 3600
    assert result["previous_seconds"] == 0
    assert result["daily_average_seconds"] == 5 * 3600 + 15 * 60
    assert result["previous_daily_average_seconds"] == 0
    assert result["recorded_day_count"] == 4
    assert result["previous_recorded_day_count"] == 0
    assert result["today_seconds"] == 2 * 3600
    assert result["today_subjects"] == [{"subject": "408二轮", "seconds": 2 * 3600}]
    assert result["yesterday_seconds"] == 7 * 3600
    assert result["subjects"] == [
        {"subject": "政治一轮", "seconds": 7 * 3600},
        {"subject": "数学二轮", "seconds": 7 * 3600},
        {"subject": "英语二轮", "seconds": 5 * 3600},
        {"subject": "408二轮", "seconds": 2 * 3600},
    ]
    assert result["all_time_seconds"] == 14 * 3600 + 7 * 3600
    assert result["all_time_subjects"] == [
        {"subject": "政治一轮", "seconds": 7 * 3600},
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
        "recorded_day_count": 0,
        "previous_recorded_day_count": 0,
        "recorded_days": [],
        "previous_recorded_days": [],
        "today_seconds": 0,
        "today_subjects": [],
        "yesterday_seconds": 0,
        "subjects": [],
        "all_time_seconds": 0,
        "all_time_subjects": [],
    }


def test_focus_investment_limits_each_comparison_to_seven_recorded_days():
    from app.services import aggregate_focus_investment

    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    sessions = [
        (f"科目{index}", now - timedelta(days=index, hours=1), now - timedelta(days=index))
        for index in range(15)
    ]

    result = aggregate_focus_investment(sessions, now)

    assert result["recorded_day_count"] == 7
    assert result["previous_recorded_day_count"] == 7
    assert result["current_seconds"] == 7 * 3600
    assert result["previous_seconds"] == 7 * 3600
    assert result["recorded_days"] == ["2026-07-20", "2026-07-19", "2026-07-18", "2026-07-17", "2026-07-16", "2026-07-15", "2026-07-14"]
    assert result["previous_recorded_days"] == ["2026-07-13", "2026-07-12", "2026-07-11", "2026-07-10", "2026-07-09", "2026-07-08", "2026-07-07"]


def test_focus_leaderboard_ranks_local_days_and_reports_the_gap_to_the_next_rank():
    from app.services import focus_leaderboard

    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    sessions = [
        ("数学", datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc), datetime(2026, 7, 13, 1, 0, tzinfo=timezone.utc)),
        ("英语", datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc), datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)),
        ("408", datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc), datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)),
        ("政治", datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc), datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)),
    ]

    result = focus_leaderboard(sessions, now)

    assert [(entry["date"], entry["seconds"], entry["rank"]) for entry in result["entries"]] == [
        ("2026-07-13", 3 * 3600, 1),
        ("2026-07-14", 2 * 3600, 2),
        ("2026-07-12", 2 * 3600, 2),
        ("2026-07-15", 3600, 4),
    ]
    assert result["today"] == {
        "date": "2026-07-15",
        "seconds": 3600,
        "rank": 4,
        "gap_to_previous_seconds": 3600,
        "percentile": 25.0,
    }


def test_focus_segments_exclude_closed_and_open_pauses():
    from app.routes import _session_segments

    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    row = {"started_at": (now - timedelta(hours=3)).isoformat(), "ended_at": None}
    pauses = [
        {"started_at": (now - timedelta(hours=2, minutes=30)).isoformat(), "ended_at": (now - timedelta(hours=2)).isoformat()},
        {"started_at": (now - timedelta(minutes=30)).isoformat(), "ended_at": None},
    ]

    segments = _session_segments(row, pauses, now)

    assert segments == [
        (now - timedelta(hours=3), now - timedelta(hours=2, minutes=30)),
        (now - timedelta(hours=2), now - timedelta(minutes=30)),
    ]
    assert sum(int((end - start).total_seconds()) for start, end in segments) == 2 * 3600
