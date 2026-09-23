from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def current_time(timezone_name: str) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = timezone(timedelta(hours=8)) if timezone_name == "Asia/Shanghai" else timezone.utc
    return datetime.now(zone)


def _at_time(now: datetime, value: str) -> datetime:
    hour, minute = (int(part) for part in value.split(":", 1))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def calculate_window(now: datetime, start: str, end: str) -> dict:
    start_at = _at_time(now, start)
    end_at = _at_time(now, end)
    total = max(1, int((end_at - start_at).total_seconds()))
    if now < start_at:
        state = "upcoming"
        progress = 0.0
    elif now >= end_at:
        state = "complete"
        progress = 1.0
    else:
        state = "active"
        progress = round((now - start_at).total_seconds() / total, 4)
    return {
        "start": start,
        "end": end,
        "state": state,
        "progress": progress,
        "remaining_seconds": max(0, int((end_at - now).total_seconds())),
        "total_seconds": total,
    }


def seconds_until_exam(now: datetime, exam_date: str) -> int:
    exam_at = datetime.fromisoformat(exam_date).replace(tzinfo=now.tzinfo)
    return max(0, int((exam_at - now).total_seconds()))


def aggregate_focus_heatmap(sessions: Iterable[tuple[datetime, datetime]], now: datetime) -> list[list[int]]:
    local_sessions = [
        (start.astimezone(now.tzinfo), min(end.astimezone(now.tzinfo), now))
        for start, end in sessions
        if end > start
    ]
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minimum_first_day = today - timedelta(days=24)
    recorded_first_day = min(
        (start.replace(hour=0, minute=0, second=0, microsecond=0) for start, end in local_sessions if end > start),
        default=minimum_first_day,
    )
    first_day = min(minimum_first_day, recorded_first_day)
    day_count = (today.date() - first_day.date()).days + 1
    heatmap = [[0 for _ in range(12)] for _ in range(day_count)]
    for start, end in local_sessions:
        cursor = max(start, first_day)
        while cursor < end:
            bucket_start = cursor.replace(hour=(cursor.hour // 2) * 2, minute=0, second=0, microsecond=0)
            segment_end = min(bucket_start + timedelta(hours=2), end)
            day_index = (cursor.date() - first_day.date()).days
            if 0 <= day_index < day_count:
                heatmap[day_index][cursor.hour // 2] += int((segment_end - cursor).total_seconds() // 60)
            cursor = segment_end
    return heatmap


def summarize_today_focus(sessions: Iterable[tuple[datetime, datetime]], now: datetime) -> dict[str, int]:
    total_seconds = 0
    count = 0
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for start, end in sessions:
        overlap_start = max(start.astimezone(now.tzinfo), day_start)
        overlap_end = min(end.astimezone(now.tzinfo), now)
        seconds = max(0, int((overlap_end - overlap_start).total_seconds()))
        if seconds:
            total_seconds += seconds
            count += 1
    return {"seconds": total_seconds, "count": count}


def aggregate_focus_by_day(sessions: Iterable[tuple[str, datetime, datetime]], now: datetime) -> dict[str, dict[str, int]]:
    """Split effective focus segments into local calendar-day subject totals."""
    day_subjects: dict[str, dict[str, int]] = {}
    for subject, session_start, session_end in sessions:
        start = session_start.astimezone(now.tzinfo)
        end = min(session_end.astimezone(now.tzinfo), now)
        cursor = start
        while cursor < end:
            next_day = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            segment_end = min(next_day, end)
            seconds = max(0, int((segment_end - cursor).total_seconds()))
            if seconds:
                day_key = cursor.date().isoformat()
                totals = day_subjects.setdefault(day_key, {})
                totals[subject] = totals.get(subject, 0) + seconds
            cursor = segment_end
    return day_subjects


def _subject_rows(totals: dict[str, int]) -> list[dict[str, int | str]]:
    return [
        {"subject": subject, "seconds": seconds}
        for subject, seconds in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]


def focus_leaderboard(sessions: Iterable[tuple[str, datetime, datetime]], now: datetime) -> dict:
    """Rank every recorded local day by its total effective focus time."""
    day_subjects = aggregate_focus_by_day(sessions, now)
    totals = {day: sum(subjects.values()) for day, subjects in day_subjects.items() if sum(subjects.values()) > 0}
    entries = []
    for day, seconds in sorted(totals.items(), key=lambda item: (item[1], item[0]), reverse=True):
        higher_totals = [value for value in totals.values() if value > seconds]
        previous_seconds = min(higher_totals) if higher_totals else None
        entries.append({
            "date": day,
            "seconds": seconds,
            "rank": len(higher_totals) + 1,
            "gap_to_previous_seconds": previous_seconds - seconds if previous_seconds is not None else None,
        })
    today_key = now.date().isoformat()
    today = next((entry for entry in entries if entry["date"] == today_key), None)
    day_count = len(entries)
    if today:
        today = {
            **today,
            "percentile": round((day_count - int(today["rank"]) + 1) / day_count * 100, 1) if day_count else 0,
        }
    else:
        today = {
            "date": today_key,
            "seconds": 0,
            "rank": None,
            "gap_to_previous_seconds": None,
            "percentile": 0,
        }
    return {"entries": entries, "day_count": day_count, "today": today}


def aggregate_focus_investment(sessions: Iterable[tuple[str, datetime, datetime]], now: datetime) -> dict:
    day_subjects = aggregate_focus_by_day(sessions, now)
    recorded_days = sorted(
        (day for day, subjects in day_subjects.items() if sum(subjects.values()) > 0),
        reverse=True,
    )
    current_days = recorded_days[:7]
    previous_days = recorded_days[7:14]

    def summarize(days: list[str]) -> tuple[int, dict[str, int]]:
        totals: dict[str, int] = {}
        for day in days:
            for subject, seconds in day_subjects.get(day, {}).items():
                totals[subject] = totals.get(subject, 0) + seconds
        return sum(totals.values()), totals

    current_seconds, current_subjects = summarize(current_days)
    previous_seconds, _ = summarize(previous_days)
    today_key = now.date().isoformat()
    yesterday_key = (now - timedelta(days=1)).date().isoformat()
    today_subject_totals = day_subjects.get(today_key, {})
    today_seconds = sum(today_subject_totals.values())
    yesterday_seconds = sum(day_subjects.get(yesterday_key, {}).values())
    all_seconds, all_subject_totals = summarize(recorded_days)
    return {
        "current_seconds": current_seconds,
        "previous_seconds": previous_seconds,
        "daily_average_seconds": current_seconds // len(current_days) if current_days else 0,
        "previous_daily_average_seconds": previous_seconds // len(previous_days) if previous_days else 0,
        "recorded_day_count": len(current_days),
        "previous_recorded_day_count": len(previous_days),
        "recorded_days": current_days,
        "previous_recorded_days": previous_days,
        "today_seconds": today_seconds,
        "today_subjects": _subject_rows(today_subject_totals),
        "yesterday_seconds": yesterday_seconds,
        "subjects": _subject_rows(current_subjects),
        "all_time_seconds": all_seconds,
        "all_time_subjects": _subject_rows(all_subject_totals),
    }


def score_metrics(scores: Iterable[dict]) -> list[dict]:
    result = []
    for score in scores:
        target = float(score["target"])
        current = float(score["score"])
        result.append({**score, "gap": round(target - current, 2), "completion": round(current / target, 4) if target else 0.0})
    return result
