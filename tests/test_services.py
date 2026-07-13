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
    assert all(len(day) == 24 for day in heatmap)
    assert sum(sum(day) for day in heatmap) == 120
