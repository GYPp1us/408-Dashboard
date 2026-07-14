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
    first_day = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    heatmap = [[0 for _ in range(12)] for _ in range(30)]
    for start, end in sessions:
        cursor = max(start, first_day)
        while cursor < end:
            bucket_start = cursor.replace(hour=(cursor.hour // 2) * 2, minute=0, second=0, microsecond=0)
            segment_end = min(bucket_start + timedelta(hours=2), end)
            day_index = (cursor.date() - first_day.date()).days
            if 0 <= day_index < 30:
                heatmap[day_index][cursor.hour // 2] += int((segment_end - cursor).total_seconds() // 60)
            cursor = segment_end
    return heatmap


def summarize_today_focus(sessions: Iterable[tuple[datetime, datetime]], now: datetime) -> dict[str, int]:
    total_seconds = 0
    count = 0
    for start, end in sessions:
        local_start = start.astimezone(now.tzinfo)
        if local_start.date() != now.date():
            continue
        total_seconds += max(0, int((end - start).total_seconds()))
        count += 1
    return {"seconds": total_seconds, "count": count}


def score_metrics(scores: Iterable[dict]) -> list[dict]:
    result = []
    for score in scores:
        target = float(score["target"])
        current = float(score["score"])
        result.append({**score, "gap": round(target - current, 2), "completion": round(current / target, 4) if target else 0.0})
    return result
