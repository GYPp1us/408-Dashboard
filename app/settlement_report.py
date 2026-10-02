"""Immutable daily report payloads, including honest legacy-summary fallbacks."""

from typing import Any


REPORT_VERSION = 1
TRUST_NOTE = "按专注记录的可信标记统计，暂停时间不计入；锁定后台的记录标记为非可信。"


def _base_report(settlement: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": REPORT_VERSION,
        "date": settlement["settlement_date"],
        "settled_at": settlement["settled_at"],
        "total_seconds": settlement["total_seconds"],
        "yesterday_seconds": settlement["yesterday_seconds"],
        "delta_seconds": settlement["delta_seconds"],
        "target_seconds": settlement["target_seconds"],
        "completion": settlement["completion"],
        "completion_percent": round(settlement["completion"] * 100, 2),
        "session_count": settlement["session_count"],
        "top_subject": settlement.get("top_subject"),
        "top_subject_seconds": settlement.get("top_subject_seconds", 0),
    }


def _achievements(report: dict[str, Any], leaderboard: dict | None = None) -> list[dict[str, str]]:
    result = []
    total = report["total_seconds"]
    if total > 0 and total >= report["target_seconds"] > 0:
        result.append({"id": "goal_met", "label": "目标达成", "detail": "有效专注时长达到当日目标。"})
    if report["yesterday_seconds"] > 0 and report["delta_seconds"] > 0:
        result.append({"id": "ahead_of_yesterday", "label": "超越昨日", "detail": "有效专注时长超过昨日。"})
    if leaderboard and total > 0:
        previous = [row["seconds"] for row in leaderboard["entries"] if row["date"] < report["date"]]
        if previous and total > max(previous):
            result.append({"id": "personal_best", "label": "个人新高", "detail": "超过此前所有有记录日期的有效专注时长。"})
    if (report.get("longest_session_seconds") or 0) >= 3600:
        result.append({"id": "one_hour_session", "label": "一小时投入", "detail": "至少一次会话的当日有效专注时长达到一小时。"})
    if total > 0 and report.get("trusted_seconds") == total:
        result.append({"id": "trusted_day", "label": "全程可信", "detail": "当日有效专注时长全部来自标记为可信的记录。"})
    if report.get("subject_identity_complete") and len(report["subject_totals"]) >= 3:
        result.append({"id": "three_subjects", "label": "三科推进", "detail": "当日至少三个科目有有效专注记录。"})
    return result


def legacy_settlement_report(settlement: dict[str, Any]) -> dict[str, Any]:
    """Never reconstruct missing historical evidence from today's mutable data."""
    report = {
        **_base_report(settlement),
        "snapshot_kind": "legacy_summary",
        "timezone": None,
        "username": None,
        "subject_breakdown_complete": False,
        "subject_identity_complete": False,
        "subject_totals": [],
        "longest_session_seconds": None,
        "first_start": None,
        "last_end": None,
        "trusted_seconds": None,
        "untrusted_seconds": None,
        "trust_note": "这份历史结算只保存了摘要，未保存会话时间及可信计时快照。",
        "rank": None,
        "percentile": None,
        "day_count": None,
        "gap_to_previous_seconds": None,
        "challenge": None,
        "index": None,
        "closing_note": "当日投入已留下记录。历史结算未保存的细节不作补算。",
        "missing_fields": [
            "timezone", "username", "subject_totals", "longest_session_seconds", "first_start", "last_end",
            "trusted_seconds", "untrusted_seconds", "rank", "percentile", "day_count",
            "gap_to_previous_seconds", "challenge", "index",
        ],
    }
    if settlement.get("top_subject") and settlement.get("top_subject_seconds", 0) > 0:
        seconds = int(settlement["top_subject_seconds"])
        report["subject_totals"] = [{
            "subject": settlement["top_subject"], "seconds": seconds,
            "percent": round(seconds / report["total_seconds"] * 100, 2) if report["total_seconds"] else 0,
        }]
    report["achievements"] = _achievements(report)
    return report


def build_settlement_report(
    settlement: dict[str, Any], *, timezone_name: str, username: str | None,
    today_rows: list[dict], subject_names: dict[int, str], leaderboard: dict,
    index_payload: dict,
) -> dict[str, Any]:
    subject_totals: dict[str, int] = {}
    trusted_seconds = untrusted_seconds = 0
    for row in today_rows:
        seconds = int(row["effective_seconds"])
        subject = subject_names.get(row.get("subject_id"), row["subject"])
        if seconds > 0:
            subject_totals[subject] = subject_totals.get(subject, 0) + seconds
        if row.get("trusted", True):
            trusted_seconds += seconds
        else:
            untrusted_seconds += seconds
    total = int(settlement["total_seconds"])
    candle = index_payload.get("today") or None
    index = None
    if candle and candle.get("date") == settlement["settlement_date"]:
        is_closed = candle["status"] in ("closed", "below_floor")
        index = {
            "open": candle["open"], "current": candle["close"], "previous_close": candle["previous_close"],
            "return_percent": candle["change_pct"], "status": candle["status"],
            "is_market_closed": is_closed, "as_of": settlement["settled_at"],
            "model_version": index_payload["model_version"],
            "limit_up": candle["limit_up"], "limit_down": candle["limit_down"],
            "note": "当日市场收盘指数快照。" if is_closed else "主动收官时的指数快照，市场尚未收盘。",
        }
    today_rank = leaderboard["today"]
    report = {
        **_base_report(settlement),
        "snapshot_kind": "settled",
        "timezone": timezone_name,
        "username": username,
        "subject_breakdown_complete": True,
        "subject_identity_complete": all(
            row.get("subject_id") in subject_names for row in today_rows if row["effective_seconds"] > 0
        ),
        "subject_totals": [
            {"subject": name, "seconds": seconds, "percent": round(seconds / total * 100, 2) if total else 0}
            for name, seconds in sorted(subject_totals.items(), key=lambda item: (-item[1], item[0]))
        ],
        "longest_session_seconds": max((row["effective_seconds"] for row in today_rows), default=0),
        "first_start": min((row["started_at"] for row in today_rows), default=None),
        "last_end": max((row["ended_at"] for row in today_rows if row["ended_at"]), default=None),
        "trusted_seconds": trusted_seconds,
        "untrusted_seconds": untrusted_seconds,
        "trust_note": TRUST_NOTE,
        "rank": today_rank["rank"],
        "percentile": today_rank["percentile"],
        "day_count": leaderboard["day_count"],
        "gap_to_previous_seconds": today_rank["gap_to_previous_seconds"],
        "challenge": index_payload.get("challenge"),
        "index": index,
        "closing_note": "今天的投入已经收好，下一次专注从明天开始。" if total else "今天已经收官，明天仍是新的开始。",
        "missing_fields": [] if index else ["index"],
    }
    report["achievements"] = _achievements(report, leaderboard)
    return report
