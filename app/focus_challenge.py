"""Causal, account-local daily limit policy; decisions are primary data."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ORDINARY_LIMIT = 0.10
CHALLENGE_LIMIT = 0.20


def account_now(now, timezone_name):
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = timezone(timedelta(hours=8)) if timezone_name == "Asia/Shanghai" else timezone.utc
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(zone)


def challenge_decisions(connection, user_id):
    if user_id is None:
        return []
    # Pure chart GETs also work against pre-migration databases without writes.
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='focus_kline_challenge_events'").fetchone():
        return []
    return [dict(row) for row in connection.execute(
        "SELECT * FROM focus_kline_challenge_events WHERE user_id=? ORDER BY id", (int(user_id),)
    )]


def limit_policy(decisions):
    """Resolve deferred off transitions, including cancellation before midnight."""
    events, pending = [], None
    active = ORDINARY_LIMIT
    for item in decisions:
        changed = datetime.fromisoformat(item["changed_at"])
        if pending and pending["at"] <= changed:
            if active != ORDINARY_LIMIT:
                events.append(pending)
            active, pending = ORDINARY_LIMIT, None
        if item["enabled"]:
            pending = None
            if active != CHALLENGE_LIMIT:
                events.append({"at": changed, "limit_return": CHALLENGE_LIMIT})
            active = CHALLENGE_LIMIT
        elif active != ORDINARY_LIMIT:
            pending = {"at": datetime.fromisoformat(item["effective_at"]), "limit_return": ORDINARY_LIMIT}
    if pending:
        events.append(pending)
    return events


def limit_at(policy, at):
    value = ORDINARY_LIMIT
    for event in policy:
        if event["at"] <= at:
            value = event["limit_return"]
        else:
            break
    return value


def policy_fingerprint(policy, through):
    return [{"at": event["at"].astimezone(timezone.utc).isoformat(), "limit_return": event["limit_return"]}
            for event in policy if event["at"] <= through]


def challenge_payload(decisions, now, timezone_name):
    current = account_now(now, timezone_name)
    visible = [row for row in decisions if datetime.fromisoformat(row["changed_at"]) <= current]
    latest = visible[-1] if visible else None
    desired = bool(latest and latest["enabled"])
    active = limit_at(limit_policy(visible), current) == CHALLENGE_LIMIT
    effective = datetime.fromisoformat(latest["effective_at"]).astimezone(current.tzinfo) if latest else None
    return {
        "desired_enabled": desired, "active_today": active,
        "pending_disable": active and not desired,
        "effective_at": effective.isoformat() if effective else None,
        "effective_date": effective.date().isoformat() if effective else None,
        "ordinary_limit_percent": 10, "current_limit_percent": 20 if active else 10,
        "revision": int(latest["id"]) if latest else 0,
        "as_of": current.isoformat(),
    }


def set_challenge(connection, user_id, enabled, now, timezone_name):
    """Serialize idempotent decisions; callers cannot supply another account id."""
    if type(enabled) is not bool:
        raise ValueError("invalid_challenge_enabled")
    current = account_now(now, timezone_name)
    connection.execute("BEGIN IMMEDIATE")
    try:
        decisions = challenge_decisions(connection, user_id)
        latest = decisions[-1] if decisions else None
        if bool(latest and latest["enabled"]) != enabled:
            effective = current if enabled else datetime.combine(current.date() + timedelta(days=1), time.min, current.tzinfo)
            connection.execute(
                "INSERT INTO focus_kline_challenge_events(user_id, enabled, changed_at, effective_at, timezone_name) VALUES (?, ?, ?, ?, ?)",
                (int(user_id), int(enabled), current.astimezone(timezone.utc).isoformat(), effective.astimezone(timezone.utc).isoformat(), timezone_name),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return challenge_payload(challenge_decisions(connection, user_id), current, timezone_name)
