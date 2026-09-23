"""Focus K-line calculation and persistence.

The dashboard records focus sessions rather than market ticks.  This module
turns those sessions into a deterministic, market-shaped daily OHLC series.
It intentionally has no Flask or template dependency so callers can refresh
the complete history whenever a session changes or a model parameter changes.

Prices are stored as index points (starting at 100.000) with a 0.001 tick.
The daily fundamental move is bounded to +/-10% by :func:`close_return` and
is settled at the configured market close. By default the market is open
08:00–12:00 and 13:30–22:00 in the configured local timezone. Focus from
00:00 to the morning open creates a high-open gap; focus in the
lunch break creates the afternoon reopening gap; post-close focus is ignored
by the same day's settlement and is not carried into the next day.
Intraday prices add deliberately visible focus/idle momentum, state-switch
shocks, and seeded mean-reverting noise; the seed makes historical charts
stable while retaining a different path for each user/date.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


INITIAL_INDEX = 100.0
PRICE_TICK = 0.001
PRICE_FLOOR = 10.0
LIMIT_RETURN = 0.10
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_BAR_MINUTES = 1
MODEL_VERSION = "focus-kline-v5"

# The app's existing study windows define the market clock.  Focus outside
# these windows can move an opening quote, but is never rendered as a
# continuous intraday point.
DEFAULT_TRADING_SESSIONS = (
    ("morning", "08:00", "12:00"),
    ("afternoon", "13:30", "22:00"),
)

# Gap moves are deliberately gentler than the daily close anchors.  The
# larger, visible short-term character comes from the intraday momentum and
# Ornstein-Uhlenbeck noise constants below.
GAP_FOCUS_PER_HOUR = 0.012
GAP_LIMIT = 0.08
MOMENTUM_DECAY = 0.82
MOMENTUM_IMPULSE = 0.0045
MOMENTUM_SWITCH_IMPULSE = 0.0075
NOISE_MEAN_REVERSION = 0.42
NOISE_VOLATILITY = 0.009
NOISE_SWITCH_VOLATILITY = 0.022
LIMIT_TOUCH_PROBABILITY = 0.12
LIMIT_REBOUND_DECAY = 0.72
LIMIT_REBOUND_NOISE = 0.0016
NOISE_CLOSE_TAPER_FRACTION = 0.08

# Settings are persisted by the existing user-settings store.  The values in
# storage use percentage points for K values because that is friendlier to a
# numeric settings form; the algorithm itself uses decimal returns.
SETTING_KEYS = {
    "a_low_hours": "focus_kline_a_low",
    "a_mid_hours": "focus_kline_a_mid",
    "a_high_hours": "focus_kline_a_high",
    "k_low_percent_per_hour": "focus_kline_k_low_percent",
    "k_high_percent_per_hour": "focus_kline_k_high_percent",
}


@dataclass(frozen=True)
class FocusKlineParameters:
    """The five user-facing model parameters.

    ``k_low`` and ``k_high`` are decimal returns per hour.  For example,
    ``0.0333333333`` means 3.33%/hour.  Omitting either value derives the
    default linear slope from its two anchors.
    """

    a_low: float = 4.0
    a_mid: float = 7.0
    a_high: float = 9.0
    k_low: float | None = None
    k_high: float | None = None

    def __post_init__(self) -> None:
        anchors = (self.a_low, self.a_mid, self.a_high)
        if not all(math.isfinite(float(value)) for value in anchors):
            raise ValueError("focus_kline_anchors_must_be_finite")
        if not (0 <= self.a_low < self.a_mid < self.a_high):
            raise ValueError("focus_kline_anchors_must_be_strictly_increasing")
        low_slope = LIMIT_RETURN / (self.a_mid - self.a_low)
        high_slope = LIMIT_RETURN / (self.a_high - self.a_mid)
        if self.k_low is None:
            object.__setattr__(self, "k_low", low_slope)
        if self.k_high is None:
            object.__setattr__(self, "k_high", high_slope)
        if not all(math.isfinite(float(value)) and float(value) >= 0 for value in (self.k_low, self.k_high)):
            raise ValueError("focus_kline_slopes_must_be_finite_and_non_negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "FocusKlineParameters":
        """Create parameters from a persisted/user payload.

        Unknown keys are ignored deliberately: only the five documented
        controls should affect the model.
        """

        if not value:
            return cls()
        fields = {"a_low", "a_mid", "a_high", "k_low", "k_high"}
        payload = {key: value[key] for key in fields if key in value and value[key] is not None}
        return cls(**payload)

    def to_mapping(self) -> dict[str, float]:
        return {
            "a_low": float(self.a_low),
            "a_mid": float(self.a_mid),
            "a_high": float(self.a_high),
            "k_low": float(self.k_low),
            "k_high": float(self.k_high),
        }


# A short alias keeps integrations readable without exposing implementation
# details in a route or template.
FocusKlineConfig = FocusKlineParameters


def _as_parameters(parameters: FocusKlineParameters | Mapping[str, Any] | None) -> FocusKlineParameters:
    if isinstance(parameters, FocusKlineParameters):
        return parameters
    return FocusKlineParameters.from_mapping(parameters)


def _parameters_from_settings(settings: Mapping[str, Any] | None) -> FocusKlineParameters:
    values = settings or {}

    def number(key: str, default: float) -> float:
        try:
            value = float(values.get(key, default))
        except (TypeError, ValueError):
            value = default
        return value

    return FocusKlineParameters(
        a_low=number(SETTING_KEYS["a_low_hours"], 4.0),
        a_mid=number(SETTING_KEYS["a_mid_hours"], 7.0),
        a_high=number(SETTING_KEYS["a_high_hours"], 9.0),
        k_low=number(SETTING_KEYS["k_low_percent_per_hour"], 3.333333) / 100.0,
        k_high=number(SETTING_KEYS["k_high_percent_per_hour"], 5.0) / 100.0,
    )


def validate_setting_payload(payload: Mapping[str, Any], current: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Validate the five public settings and return DB-ready strings."""

    source = dict(current or {})
    aliases = {
        "a_low_hours": ("a_low", "a_low_hours", SETTING_KEYS["a_low_hours"]),
        "a_mid_hours": ("a_mid", "a_mid_hours", SETTING_KEYS["a_mid_hours"]),
        "a_high_hours": ("a_high", "a_high_hours", SETTING_KEYS["a_high_hours"]),
        "k_low_percent_per_hour": ("k_low", "k_low_percent", "k_low_percent_per_hour", SETTING_KEYS["k_low_percent_per_hour"]),
        "k_high_percent_per_hour": ("k_high", "k_high_percent", "k_high_percent_per_hour", SETTING_KEYS["k_high_percent_per_hour"]),
    }

    def read(field: str, default: float) -> float:
        keys = aliases[field]
        raw = next((payload[key] for key in keys if key in payload), None)
        if raw is None:
            raw = next((source[key] for key in keys if key in source), default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"invalid_{field}") from None
        if not math.isfinite(value):
            raise ValueError(f"invalid_{field}")
        return value

    a_low = read("a_low_hours", 4.0)
    a_mid = read("a_mid_hours", 7.0)
    a_high = read("a_high_hours", 9.0)
    k_low = read("k_low_percent_per_hour", 3.333333)
    k_high = read("k_high_percent_per_hour", 5.0)
    if not (0 <= a_low < a_mid < a_high <= 24):
        raise ValueError("invalid_focus_kline_anchors")
    if not (0 <= k_low <= 20 and 0 <= k_high <= 20):
        raise ValueError("invalid_focus_kline_slopes")
    return {
        SETTING_KEYS["a_low_hours"]: f"{a_low:g}",
        SETTING_KEYS["a_mid_hours"]: f"{a_mid:g}",
        SETTING_KEYS["a_high_hours"]: f"{a_high:g}",
        SETTING_KEYS["k_low_percent_per_hour"]: f"{k_low:g}",
        SETTING_KEYS["k_high_percent_per_hour"]: f"{k_high:g}",
    }


def close_return(focus_hours: float, parameters: FocusKlineParameters | Mapping[str, Any] | None = None) -> float:
    """Return the daily fundamental move for ``focus_hours``.

    The result is a decimal return (``0.05`` means +5%).  It follows the
    specified -10% / 0% / +10% piecewise curve and never exceeds either limit.
    """

    config = _as_parameters(parameters)
    try:
        hours = max(0.0, float(focus_hours))
    except (TypeError, ValueError):
        hours = 0.0
    if not math.isfinite(hours):
        hours = 0.0 if hours < 0 else config.a_high
    if hours <= config.a_low:
        value = -LIMIT_RETURN
    elif hours < config.a_mid:
        value = -LIMIT_RETURN + float(config.k_low) * (hours - config.a_low)
    elif hours < config.a_high:
        value = float(config.k_high) * (hours - config.a_mid)
    else:
        value = LIMIT_RETURN
    return max(-LIMIT_RETURN, min(LIMIT_RETURN, value))


def _zone(timezone_name: str) -> Any:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=8)) if timezone_name == DEFAULT_TIMEZONE else timezone.utc


def _coerce_datetime(value: datetime | str, target_zone: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(target_zone)


def _coerce_now(now: datetime | None, target_zone: Any) -> datetime:
    value = now or datetime.now(timezone.utc)
    return _coerce_datetime(value, target_zone)


def _price(value: float, *, floor: float = PRICE_FLOOR) -> float:
    """Round to the 0.001 index tick without binary tail noise."""

    if not math.isfinite(value):
        value = floor
    value = max(floor, float(value))
    return float(f"{round(value / PRICE_TICK) * PRICE_TICK:.3f}")


def _date_key(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()


def _day_start(day: date, target_zone: Any) -> datetime:
    return datetime.combine(day, time.min, tzinfo=target_zone)


def _clock(value: str | time) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    text = str(value).strip()
    hour, minute = (int(part) for part in text.split(":", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid_trading_session_clock")
    return time(hour, minute)


def normalize_trading_sessions(
    sessions: Sequence[Sequence[str | time] | Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Normalize market windows to named, same-day local-time sessions.

    Accepted tuple forms are ``(start, end)`` and ``(name, start, end)``;
    mappings accept ``name``, ``start`` and ``end``.  The default clock is
    08:00–12:00 and 13:30–22:00 (Asia/Shanghai by default).
    """

    source = sessions or DEFAULT_TRADING_SESSIONS
    result: list[dict[str, Any]] = []
    for index, item in enumerate(source):
        if isinstance(item, Mapping):
            name = str(item.get("name") or f"session-{index + 1}")
            start_value = item.get("start")
            end_value = item.get("end")
        else:
            values = list(item)
            if len(values) == 2:
                name = f"session-{index + 1}"
                start_value, end_value = values
            elif len(values) == 3:
                name, start_value, end_value = values
                name = str(name)
            else:
                raise ValueError("invalid_trading_session")
        start = _clock(start_value)
        end = _clock(end_value)
        if start >= end:
            raise ValueError("trading_session_must_be_same_day_and_increasing")
        result.append({"name": str(name), "start": start, "end": end})
    if not result:
        raise ValueError("trading_sessions_required")
    result.sort(key=lambda item: (item["start"], item["end"], item["name"]))
    for previous, current in zip(result, result[1:]):
        if current["start"] < previous["end"]:
            raise ValueError("trading_sessions_must_not_overlap")
    return tuple(result)


def trading_sessions_from_settings(settings: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
    """Read the existing dashboard study-window settings as market hours."""

    values = settings or {}
    return normalize_trading_sessions(
        (
            ("morning", values.get("morning_start", "08:00"), values.get("lunch_start", "12:00")),
            ("afternoon", values.get("library_open", "13:30"), values.get("library_close", "22:00")),
        )
    )


def trading_session_windows(
    day: date,
    sessions: Sequence[Sequence[str | time] | Mapping[str, Any]] | None = None,
    *,
    target_zone: Any = timezone.utc,
) -> tuple[dict[str, Any], ...]:
    """Return concrete timezone-aware datetime windows for one local day."""

    return tuple(
        {
            "name": item["name"],
            "start": datetime.combine(day, item["start"], tzinfo=target_zone),
            "end": datetime.combine(day, item["end"], tzinfo=target_zone),
        }
        for item in normalize_trading_sessions(sessions)
    )


def _focus_seconds_between(
    segments: Sequence[tuple[datetime, datetime]],
    start: datetime,
    end: datetime,
) -> int:
    return sum(
        max(0, int((min(segment_end, end) - max(segment_start, start)).total_seconds()))
        for segment_start, segment_end in segments
        if segment_end > start and segment_start < end
    )


def _gap_return(focus_seconds: int, window_seconds: int) -> float:
    """Translate effective off-market focus into a bounded positive gap.

    Normal sleep/rest in a pre-open or lunch window is neutral.  Negative
    short-term pressure belongs to the in-session idle momentum model; a gap
    exists only when effective focus was recorded outside the market window.
    """

    if window_seconds <= 0:
        return 0.0
    focused_hours = max(0, focus_seconds) / 3600.0
    value = focused_hours * GAP_FOCUS_PER_HOUR
    return max(-GAP_LIMIT, min(GAP_LIMIT, value))


def _session_segments(
    row: Mapping[str, Any],
    pauses: Sequence[Mapping[str, Any]],
    now: datetime,
    target_zone: Any,
) -> list[tuple[datetime, datetime]]:
    """Return effective (non-paused) segments for one DB session."""

    try:
        start = _coerce_datetime(row["started_at"], target_zone)
    except (KeyError, TypeError, ValueError):
        return []
    raw_end = row.get("ended_at")
    try:
        end = _coerce_datetime(raw_end, target_zone) if raw_end else now
    except (TypeError, ValueError):
        end = now
    end = min(end, now)
    if end <= start:
        return []
    cursor = start
    result: list[tuple[datetime, datetime]] = []
    ordered_pauses = sorted(pauses, key=lambda item: str(item.get("started_at", "")))
    for pause in ordered_pauses:
        try:
            pause_start = _coerce_datetime(pause["started_at"], target_zone)
        except (KeyError, TypeError, ValueError):
            continue
        try:
            pause_end = _coerce_datetime(pause["ended_at"], target_zone) if pause.get("ended_at") else end
        except (TypeError, ValueError):
            pause_end = end
        if pause_end <= cursor or pause_start >= end:
            continue
        pause_start = max(start, pause_start)
        pause_end = min(end, pause_end)
        if pause_start > cursor:
            result.append((cursor, pause_start))
        cursor = max(cursor, pause_end)
    if cursor < end:
        result.append((cursor, end))
    return result


def _load_effective_segments(
    connection: sqlite3.Connection,
    user_id: int,
    now: datetime,
    target_zone: Any,
) -> list[tuple[datetime, datetime]]:
    rows = connection.execute(
        "SELECT id, started_at, ended_at, status FROM focus_sessions WHERE user_id = ? ORDER BY started_at, id",
        (user_id,),
    ).fetchall()
    pauses: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if rows:
        placeholders = ",".join("?" for _ in rows)
        pause_rows = connection.execute(
            f"SELECT session_id, started_at, ended_at FROM focus_pauses WHERE session_id IN ({placeholders}) ORDER BY started_at",
            tuple(int(row["id"]) for row in rows),
        ).fetchall()
        for pause in pause_rows:
            pauses[int(pause["session_id"])].append(dict(pause))
    segments: list[tuple[datetime, datetime]] = []
    for row in rows:
        segments.extend(_session_segments(dict(row), pauses[int(row["id"])], now, target_zone))
    return sorted(segments, key=lambda item: item[0])


def group_focus_segments_by_day(
    segments: Iterable[tuple[datetime, datetime]],
) -> tuple[dict[str, int], dict[str, list[tuple[datetime, datetime]]]]:
    """Split effective segments across local calendar days.

    Returns ``(seconds_by_day, segments_by_day)``.  The latter is used for
    state transitions and intraday path generation.
    """

    seconds: dict[str, int] = defaultdict(int)
    by_day: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for raw_start, raw_end in segments:
        if raw_end <= raw_start:
            continue
        cursor = raw_start
        while cursor < raw_end:
            next_day = _day_start(cursor.date() + timedelta(days=1), cursor.tzinfo)
            segment_end = min(next_day, raw_end)
            day_key = cursor.date().isoformat()
            duration = max(0, int((segment_end - cursor).total_seconds()))
            if duration:
                seconds[day_key] += duration
                by_day[day_key].append((cursor, segment_end))
            cursor = segment_end
    return dict(seconds), dict(by_day)


def _contains_focus(segments: Sequence[tuple[datetime, datetime]], at: datetime) -> bool:
    return any(start <= at < end for start, end in segments)


def _seed_for(user_key: int | str, day_key: str) -> int:
    digest = hashlib.sha256(f"{user_key}:{day_key}:{MODEL_VERSION}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _reflect_limit_price(
    value: float,
    *,
    reference_price: float,
    lower_bound: float,
    upper_bound: float,
    noise: float,
    momentum: float,
    rng: random.Random,
    rebound_state: float,
    bar_units: float,
    close_taper: float,
) -> tuple[float, float]:
    """Keep limit prices alive with sparse, seeded inside-band bounces.

    The fundamental close can still be exactly at a limit.  This helper only
    applies to noisy intraday points.  Touches are stochastic rather than
    periodic, while ``rebound_state`` is an OU-like memory so several nearby
    bars move together instead of making a synthetic saw-tooth wave.
    """

    if upper_bound <= lower_bound:
        return lower_bound, rebound_state
    if value <= lower_bound:
        target_state = min(
            0.006,
            0.0004 + abs(noise) * 0.08 + abs(momentum) * 0.12 + abs(rng.gauss(0.0, LIMIT_REBOUND_NOISE)),
        )
        rebound_decay = LIMIT_REBOUND_DECAY**bar_units
        rebound_state = max(0.0, min(0.006, rebound_state * rebound_decay + target_state * (1.0 - rebound_decay)))
        if rng.random() < 1.0 - (1.0 - LIMIT_TOUCH_PROBABILITY) ** bar_units:
            return lower_bound, rebound_state
        rebound_pct = (0.0008 + rebound_state) * close_taper
        return min(upper_bound, _price(lower_bound + reference_price * rebound_pct)), rebound_state
    if value >= upper_bound:
        target_state = min(
            0.006,
            0.0004 + abs(noise) * 0.08 + abs(momentum) * 0.12 + abs(rng.gauss(0.0, LIMIT_REBOUND_NOISE)),
        )
        rebound_decay = LIMIT_REBOUND_DECAY**bar_units
        rebound_state = max(0.0, min(0.006, rebound_state * rebound_decay + target_state * (1.0 - rebound_decay)))
        if rng.random() < 1.0 - (1.0 - LIMIT_TOUCH_PROBABILITY) ** bar_units:
            return upper_bound, rebound_state
        rebound_pct = (0.0008 + rebound_state) * close_taper
        return max(lower_bound, _price(upper_bound - reference_price * rebound_pct)), rebound_state
    return value, rebound_state * (0.55**bar_units)


def _intraday_path(
    *,
    day: date,
    reference_price: float,
    open_price: float,
    target_close: float,
    parameters: FocusKlineParameters,
    segments: Sequence[tuple[datetime, datetime]],
    now: datetime,
    user_key: int | str,
    bar_minutes: int,
    sessions: Sequence[Sequence[str | time] | Mapping[str, Any]],
    lunch_gap_return: float,
    complete_day: bool,
    aggregate_focus_seconds: int | None,
) -> list[dict[str, Any]]:
    """Generate points only inside market windows.

    The fundamental anchor interpolates from each session's actual opening
    quote toward the projected daily close, using elapsed *market* time only.
    Momentum and noise are fractional returns from ``reference_price`` (the
    prior daily close). A lunch gap resets the afternoon origin; no point is
    emitted between sessions.
    """

    target_zone = now.tzinfo
    windows = trading_session_windows(day, sessions, target_zone=target_zone)
    day_start = _day_start(day, target_zone)
    day_end = windows[-1]["end"]
    cutoff = now if day == now.date() else day_end
    total_market_seconds = sum((window["end"] - window["start"]).total_seconds() for window in windows)
    step = timedelta(minutes=max(1, int(bar_minutes)))
    rng = random.Random(_seed_for(user_key, day.isoformat()))
    path: list[dict[str, Any]] = []
    previous_state = "idle"
    momentum = 0.0
    noise = 0.0
    previous_at = day_start
    previous_price = _price(open_price)
    limit_rebound_state = 0.0

    for window_index, window in enumerate(windows):
        if cutoff <= window["start"]:
            continue
        window_end = min(window["end"], cutoff)
        if window_end < window["end"]:
            # Persist only complete minute bars. The browser may render
            # second-level quote ticks inside the latest minute, but those
            # transient trades must never become historical source data.
            elapsed_seconds = max(0.0, (window_end - window["start"]).total_seconds())
            completed_steps = math.floor(elapsed_seconds / step.total_seconds())
            window_end = window["start"] + step * completed_steps
        timestamps: list[datetime] = [window["start"]]
        cursor = window["start"] + step
        while cursor < window_end:
            timestamps.append(cursor)
            cursor += step
        if timestamps[-1] != window_end:
            timestamps.append(window_end)

        if window_index == 0:
            session_open = _price(open_price)
        else:
            session_open = _price(previous_price * (1.0 + lunch_gap_return))
            session_open = max(
                PRICE_FLOOR,
                min(
                    _price(reference_price * (1.0 + LIMIT_RETURN), floor=0.001),
                    max(_price(reference_price * (1.0 - LIMIT_RETURN), floor=0.001), session_open),
                ),
            )
        elapsed_before_session = sum(
            (earlier["end"] - earlier["start"]).total_seconds()
            for earlier in windows[:window_index]
        )
        origin_progress = elapsed_before_session / total_market_seconds
        origin_return = (session_open / reference_price) - 1.0

        for index, at in enumerate(timestamps):
            focused = _contains_focus(segments, min(at, window_end - timedelta(microseconds=1)))
            state = "focus" if focused else "idle"
            changed = bool(path) and index > 0 and state != previous_state
            bar_units = max(1.0 / 600.0, (at - previous_at).total_seconds() / 600.0)
            sign = 1.0 if focused else -1.0
            momentum *= MOMENTUM_DECAY**bar_units
            noise *= max(0.03, 1.0 - NOISE_MEAN_REVERSION) ** bar_units
            switch_shock = 0.0
            if index > 0:
                momentum += sign * MOMENTUM_IMPULSE * bar_units
                if changed:
                    momentum += sign * MOMENTUM_SWITCH_IMPULSE
                    switch_shock = NOISE_SWITCH_VOLATILITY
                noise += rng.gauss(
                    0.0,
                    NOISE_VOLATILITY * math.sqrt(bar_units) + switch_shock,
                )

            if index == 0:
                value = session_open
            else:
                elapsed_market_seconds = elapsed_before_session + (at - window["start"]).total_seconds()
                progress = max(0.0, min(1.0, elapsed_market_seconds / total_market_seconds))
                if aggregate_focus_seconds is None:
                    focused_market_seconds = sum(
                        _focus_seconds_between(segments, item["start"], min(at, item["end"]))
                        for item in windows if at > item["start"]
                    )
                    focused_off_market_seconds = max(
                        0, _focus_seconds_between(segments, day_start, at) - focused_market_seconds
                    )
                    projected_seconds = focused_off_market_seconds + (
                        focused_market_seconds * total_market_seconds / elapsed_market_seconds
                    )
                else:
                    # Aggregate-only imports have no timing information.  Use
                    # their known daily total instead of fabricating an idle day
                    # followed by an artificial closing spike.
                    projected_seconds = aggregate_focus_seconds
                projected_hours = max(0.0, min(24.0, projected_seconds / 3600.0))
                session_progress = (progress - origin_progress) / max(1e-9, 1.0 - origin_progress)
                anchor = origin_return + session_progress * (
                    close_return(projected_hours, parameters) - origin_return
                )
                # Momentum and news-like noise remain visible intraday, but
                # cannot create a one-bar settlement jump at the close.
                taper = min(1.0, ((1.0 - progress) / NOISE_CLOSE_TAPER_FRACTION) ** 2)
                market_return = max(-LIMIT_RETURN, min(LIMIT_RETURN, anchor + (momentum + noise) * taper))
                value = _price(reference_price * (1.0 + market_return))
                lower_bound = max(PRICE_FLOOR, _price(reference_price * (1.0 - LIMIT_RETURN), floor=0.001))
                upper_bound = _price(reference_price * (1.0 + LIMIT_RETURN), floor=0.001)
                value = min(max(value, lower_bound), upper_bound)
                value, limit_rebound_state = _reflect_limit_price(
                    value,
                    reference_price=reference_price,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    noise=noise,
                    momentum=momentum,
                    rng=rng,
                    rebound_state=limit_rebound_state,
                    bar_units=bar_units,
                    close_taper=taper,
                )
            path.append(
                {
                    "timestamp": at.isoformat(),
                    "price": _price(value),
                    "state": state,
                    "session": window["name"],
                    "changed": changed,
                }
            )
            previous_state = state
            previous_at = at
            previous_price = _price(value)

    # Only a completed trading day receives the fundamental close.  For the
    # current partial day, the latest visible market point is the close.
    if path and complete_day:
        path[-1]["price"] = _price(target_close)
    return path


def build_focus_klines(
    daily_focus_seconds: Mapping[date | str, int | float],
    *,
    daily_segments: Mapping[date | str, Sequence[tuple[datetime, datetime]]] | None = None,
    now: datetime | None = None,
    user_key: int | str = 0,
    parameters: FocusKlineParameters | Mapping[str, Any] | None = None,
    bar_minutes: int = DEFAULT_BAR_MINUTES,
    initial_price: float = INITIAL_INDEX,
    trading_sessions: Sequence[Sequence[str | time] | Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a complete chronological daily OHLC series from aggregated data.

    Missing dates between the first recorded date and ``now.date()`` are
    treated as zero-focus days. A supplied ``daily_segments`` map is used to
    settle F at market close, split morning/lunch gap influence, and exclude
    post-close focus. This is intentional: a historical refresh does not
    rely only on the most recent session.
    """

    config = _as_parameters(parameters)
    target_zone = now.tzinfo if now and now.tzinfo else timezone.utc
    current = _coerce_now(now, target_zone)
    normalized_sessions = normalize_trading_sessions(trading_sessions)
    normalized_seconds = {_date_key(key): max(0, int(float(value))) for key, value in daily_focus_seconds.items()}
    normalized_segments: dict[str, Sequence[tuple[datetime, datetime]]] = {
        _date_key(key): value for key, value in (daily_segments or {}).items()
    }
    first_key = min(normalized_seconds or {current.date().isoformat()})
    first_day = date.fromisoformat(first_key)
    last_day = current.date()
    if first_day > last_day:
        first_day = last_day
    result: list[dict[str, Any]] = []
    previous_close = _price(initial_price, floor=0.001)
    delisted = previous_close < PRICE_FLOOR

    day = first_day
    while day <= last_day:
        key = day.isoformat()
        segments = list(normalized_segments.get(key, ()))
        windows = trading_session_windows(day, normalized_sessions, target_zone=target_zone)
        day_start = _day_start(day, target_zone)
        market_close = windows[-1]["end"]
        market_open = windows[0]["start"]
        has_segment_detail = key in normalized_segments
        if day == current.date():
            market_cutoff = min(current, market_close)
        else:
            market_cutoff = market_close
        if has_segment_detail:
            focus_seconds = _focus_seconds_between(segments, day_start, market_cutoff)
            pre_open_seconds = _focus_seconds_between(segments, day_start, market_open)
            lunch_start = windows[0]["end"]
            lunch_end = windows[1]["start"] if len(windows) > 1 else lunch_start
            lunch_seconds = _focus_seconds_between(segments, lunch_start, lunch_end)
            after_close_seconds = _focus_seconds_between(segments, market_close, day_start + timedelta(days=1))
        else:
            focus_seconds = normalized_seconds.get(key, 0)
            pre_open_seconds = lunch_seconds = after_close_seconds = 0
        focus_hours = focus_seconds / 3600.0
        pre_open_window_seconds = max(0, int((market_open - day_start).total_seconds()))
        lunch_window_seconds = max(0, int((windows[1]["start"] - windows[0]["end"]).total_seconds())) if len(windows) > 1 else 0
        pre_open_gap = _gap_return(pre_open_seconds, pre_open_window_seconds) if has_segment_detail else 0.0
        lunch_gap = _gap_return(lunch_seconds, lunch_window_seconds) if has_segment_detail else 0.0
        complete_day = day < current.date() or current >= market_close
        reference_price = _price(previous_close)

        if delisted or reference_price <= PRICE_FLOOR:
            delisted = True
            open_price = close = low = high = _price(PRICE_FLOOR)
            path: list[dict[str, Any]] = []
            status = "delisted"
        else:
            lower_bound = max(PRICE_FLOOR, _price(reference_price * (1.0 - LIMIT_RETURN), floor=0.001))
            upper_bound = _price(reference_price * (1.0 + LIMIT_RETURN), floor=0.001)
            open_price = _price(reference_price * (1.0 + pre_open_gap))
            open_price = min(max(open_price, lower_bound), upper_bound)
            fundamental_return = close_return(focus_hours, config)
            target = reference_price * (1.0 + fundamental_return)
            target_close = min(max(_price(target), lower_bound), upper_bound)
            path = _intraday_path(
                day=day,
                reference_price=reference_price,
                open_price=open_price,
                target_close=target_close,
                parameters=config,
                segments=segments,
                now=current,
                user_key=user_key,
                bar_minutes=bar_minutes,
                sessions=normalized_sessions,
                lunch_gap_return=lunch_gap,
                complete_day=complete_day,
                aggregate_focus_seconds=None if has_segment_detail else focus_seconds,
            )
            would_delist = complete_day and target < PRICE_FLOOR
            if would_delist:
                delisted = True
                target_close = _price(PRICE_FLOOR)
                if path:
                    path[-1]["price"] = target_close
                close = target_close
                status = "delisted"
            else:
                close = _price(path[-1]["price"]) if path else open_price
                if complete_day:
                    close = target_close
                    if path:
                        path[-1]["price"] = close
                if day != current.date():
                    status = "closed"
                elif not path:
                    status = "pre_open"
                elif current < windows[0]["end"]:
                    status = "active"
                elif len(windows) > 1 and current < windows[1]["start"]:
                    status = "break"
                elif current < windows[-1]["end"]:
                    status = "active"
                else:
                    status = "closed"
            prices = [float(point["price"]) for point in path] or [open_price, close]
            low = _price(min(prices))
            high = _price(max(prices))
            low = max(low, lower_bound)
            high = min(high, upper_bound)
            low = min(low, _price(min(open_price, close)))
            high = max(high, _price(max(open_price, close)))
        change = _price(abs(close - reference_price), floor=0.001) if close != reference_price else 0.0
        if close < reference_price:
            change = -change
        change_pct = ((close / reference_price) - 1.0) * 100.0 if reference_price else 0.0
        result.append(
            {
                "date": key,
                "open": _price(open_price),
                "high": _price(high),
                "low": _price(low),
                "close": _price(close),
                "previous_close": _price(reference_price),
                "change": round(change, 3),
                "change_pct": round(change_pct, 3),
                "focus_seconds": int(focus_seconds),
                "focus_hours": round(focus_hours, 3),
                "pre_open_focus_seconds": int(pre_open_seconds),
                "lunch_focus_seconds": int(lunch_seconds),
                "after_close_focus_seconds": int(after_close_seconds),
                "pre_open_gap_pct": round(pre_open_gap * 100.0, 3),
                "lunch_gap_pct": round(lunch_gap * 100.0, 3),
                "status": status,
                "delisted": bool(delisted),
                "limit_up": _price(reference_price * (1.0 + LIMIT_RETURN)),
                "limit_down": max(PRICE_FLOOR if delisted else 0.001, _price(reference_price * (1.0 - LIMIT_RETURN), floor=0.001)),
                "trading_sessions": [
                    {"name": item["name"], "start": item["start"].isoformat(), "end": item["end"].isoformat()}
                    for item in windows
                ],
                "intraday": path,
            }
        )
        previous_close = _price(close)
        day += timedelta(days=1)
    return result


def ensure_focus_kline_schema(connection: sqlite3.Connection) -> None:
    """Create the derived K-line cache table if the database lacks it."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS focus_klines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            trading_date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            previous_close REAL NOT NULL DEFAULT 100,
            change REAL NOT NULL,
            change_pct REAL NOT NULL,
            focus_seconds INTEGER NOT NULL,
            focus_hours REAL NOT NULL,
            pre_open_focus_seconds INTEGER NOT NULL DEFAULT 0,
            lunch_focus_seconds INTEGER NOT NULL DEFAULT 0,
            after_close_focus_seconds INTEGER NOT NULL DEFAULT 0,
            pre_open_gap_pct REAL NOT NULL DEFAULT 0,
            lunch_gap_pct REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            delisted INTEGER NOT NULL DEFAULT 0,
            limit_up REAL NOT NULL,
            limit_down REAL NOT NULL,
            intraday_json TEXT NOT NULL DEFAULT '[]',
            trading_sessions_json TEXT NOT NULL DEFAULT '[]',
            model_version TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, trading_date)
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(focus_klines)").fetchall()}
    migrations = {
        "previous_close": "REAL NOT NULL DEFAULT 100",
        "pre_open_focus_seconds": "INTEGER NOT NULL DEFAULT 0",
        "lunch_focus_seconds": "INTEGER NOT NULL DEFAULT 0",
        "after_close_focus_seconds": "INTEGER NOT NULL DEFAULT 0",
        "pre_open_gap_pct": "REAL NOT NULL DEFAULT 0",
        "lunch_gap_pct": "REAL NOT NULL DEFAULT 0",
        "trading_sessions_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for name, definition in migrations.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE focus_klines ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_klines_user_date ON focus_klines(user_id, trading_date)"
    )


def recompute_focus_klines(
    connection: sqlite3.Connection,
    user_id: int,
    *,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    parameters: FocusKlineParameters | Mapping[str, Any] | None = None,
    bar_minutes: int = DEFAULT_BAR_MINUTES,
    initial_price: float = INITIAL_INDEX,
    trading_sessions: Sequence[Sequence[str | time] | Mapping[str, Any]] | None = None,
    commit: bool = True,
) -> list[dict[str, Any]]:
    """Rebuild *all* derived rows for one user from source sessions.

    The delete-and-insert operation is deliberate.  It makes changes to old
    sessions, pauses, or model parameters immediately affect every later
    candle, instead of leaving stale derived values in the cache.
    """

    target_zone = _zone(timezone_name)
    current = _coerce_now(now, target_zone)
    segments = _load_effective_segments(connection, int(user_id), current, target_zone)
    seconds_by_day, segments_by_day = group_focus_segments_by_day(segments)
    rows = build_focus_klines(
        seconds_by_day,
        daily_segments=segments_by_day,
        now=current,
        user_key=int(user_id),
        parameters=parameters,
        bar_minutes=bar_minutes,
        initial_price=initial_price,
        trading_sessions=trading_sessions,
    )
    ensure_focus_kline_schema(connection)
    connection.execute("DELETE FROM focus_klines WHERE user_id = ?", (int(user_id),))
    config = _as_parameters(parameters)
    updated_at = current.isoformat()
    for row in rows:
        connection.execute(
            """
            INSERT INTO focus_klines(
                user_id, trading_date, open, high, low, close, previous_close,
                change, change_pct, focus_seconds, focus_hours,
                pre_open_focus_seconds, lunch_focus_seconds, after_close_focus_seconds,
                pre_open_gap_pct, lunch_gap_pct, status, delisted, limit_up, limit_down,
                intraday_json, trading_sessions_json, model_version, parameters_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                row["date"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["previous_close"],
                row["change"],
                row["change_pct"],
                row["focus_seconds"],
                row["focus_hours"],
                row["pre_open_focus_seconds"],
                row["lunch_focus_seconds"],
                row["after_close_focus_seconds"],
                row["pre_open_gap_pct"],
                row["lunch_gap_pct"],
                row["status"],
                int(bool(row["delisted"])),
                row["limit_up"],
                row["limit_down"],
                json.dumps(row["intraday"], ensure_ascii=False, separators=(",", ":")),
                json.dumps(row["trading_sessions"], ensure_ascii=False, separators=(",", ":")),
                MODEL_VERSION,
                json.dumps(config.to_mapping(), ensure_ascii=False, separators=(",", ":")),
                updated_at,
            ),
        )
    if commit:
        connection.commit()
    return rows


def current_focus_state(connection: sqlite3.Connection, user_id: int) -> dict[str, bool | str]:
    """Read the user's live focus state from source rows.

    The latest intraday point is a market-clock sample and can be stale during
    lunch, after close, or when a session starts outside a market window.  The
    standalone payload therefore derives the live state from the active source
    session and its open pause instead.
    """

    active = connection.execute(
        "SELECT id FROM focus_sessions WHERE user_id = ? AND status = 'active' "
        "ORDER BY id DESC LIMIT 1",
        (int(user_id),),
    ).fetchone()
    if not active:
        return {"state": "rest", "is_focusing": False, "is_paused": False}
    paused = connection.execute(
        "SELECT 1 FROM focus_pauses WHERE session_id = ? AND ended_at IS NULL LIMIT 1",
        (int(active["id"]),),
    ).fetchone() is not None
    return {
        "state": "rest" if paused else "focus",
        "is_focusing": not paused,
        "is_paused": paused,
    }


def build_focus_kline(
    connection: sqlite3.Connection,
    user_id: int,
    timezone_name: str = DEFAULT_TIMEZONE,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility facade for the standalone page/API integration.

    Every call rebuilds the complete series from raw ``focus_sessions``.  The
    result includes a compact public parameter payload and daily candles; the
    latest candle also exposes the day's intraday path for the分时 chart.
    """

    config = _parameters_from_settings(settings)
    sessions = trading_sessions_from_settings(settings)
    candles = recompute_focus_klines(
        connection,
        int(user_id),
        timezone_name=timezone_name,
        parameters=config,
        trading_sessions=sessions,
    )
    public_parameters = {
        "a_low_hours": config.a_low,
        "a_mid_hours": config.a_mid,
        "a_high_hours": config.a_high,
        "k_low_percent_per_hour": round(float(config.k_low) * 100.0, 6),
        "k_high_percent_per_hour": round(float(config.k_high) * 100.0, 6),
    }
    latest = candles[-1] if candles else None
    previous_close = candles[-2]["close"] if len(candles) > 1 else INITIAL_INDEX
    focus = current_focus_state(connection, int(user_id))
    latest_status = "delisted" if latest and latest.get("delisted") else focus["state"]
    return {
        "parameters": public_parameters,
        "trading_sessions": [
            {"name": item["name"], "start": item["start"].strftime("%H:%M"), "end": item["end"].strftime("%H:%M")}
            for item in sessions
        ],
        "candles": candles,
        "daily": candles,
        "today": latest or {},
        "intraday": (latest or {}).get("intraday", []),
        "index": {"current": latest["close"] if latest else INITIAL_INDEX},
        "previous_close": previous_close,
        "today_focus_seconds": latest["focus_seconds"] if latest else 0,
        "status": latest_status,
        "focus_state": focus["state"],
        "is_focusing": focus["is_focusing"],
        "is_paused": focus["is_paused"],
        "limit_down": latest["limit_down"] if latest else INITIAL_INDEX * (1.0 - LIMIT_RETURN),
        "limit_up": latest["limit_up"] if latest else INITIAL_INDEX * (1.0 + LIMIT_RETURN),
        "updated_at": latest.get("updated_at") if latest else datetime.now(timezone.utc).isoformat(),
        "latest": latest,
        "current": latest,
        "model_version": MODEL_VERSION,
        "initial_index": INITIAL_INDEX,
        "price_tick": PRICE_TICK,
        "intraday_bar_minutes": DEFAULT_BAR_MINUTES,
        "price_floor": PRICE_FLOOR,
    }


def list_focus_klines(
    connection: sqlite3.Connection,
    user_id: int,
    *,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    ensure_schema: bool = True,
) -> list[dict[str, Any]]:
    """Read cached rows in chart order, decoding the intraday path."""

    if ensure_schema:
        ensure_focus_kline_schema(connection)
    clauses = ["user_id = ?"]
    params: list[Any] = [int(user_id)]
    if start_date is not None:
        clauses.append("trading_date >= ?")
        params.append(_date_key(start_date))
    if end_date is not None:
        clauses.append("trading_date <= ?")
        params.append(_date_key(end_date))
    where_clause = " AND ".join(clauses)
    rows = connection.execute(
        f"SELECT * FROM focus_klines WHERE {where_clause} ORDER BY trading_date",
        tuple(params),
    ).fetchall()
    result = []
    for row in rows:
        payload = dict(row)
        payload["date"] = payload.get("trading_date")
        payload["delisted"] = bool(payload.get("delisted"))
        try:
            payload["intraday"] = json.loads(payload.pop("intraday_json", "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload["intraday"] = []
        try:
            payload["parameters"] = json.loads(payload.pop("parameters_json", "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload["parameters"] = {}
        try:
            payload["trading_sessions"] = json.loads(payload.pop("trading_sessions_json", "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload["trading_sessions"] = []
        result.append(payload)
    return result


# Naming aliases make it clear to callers that a refresh is a full historical
# operation, not an append-only calculation.
refresh_focus_klines = recompute_focus_klines
get_focus_klines = list_focus_klines


__all__ = [
    "DEFAULT_BAR_MINUTES",
    "DEFAULT_TIMEZONE",
    "DEFAULT_TRADING_SESSIONS",
    "FocusKlineConfig",
    "FocusKlineParameters",
    "INITIAL_INDEX",
    "LIMIT_RETURN",
    "MODEL_VERSION",
    "PRICE_FLOOR",
    "PRICE_TICK",
    "SETTING_KEYS",
    "build_focus_kline",
    "build_focus_klines",
    "close_return",
    "current_focus_state",
    "ensure_focus_kline_schema",
    "get_focus_klines",
    "group_focus_segments_by_day",
    "list_focus_klines",
    "normalize_trading_sessions",
    "recompute_focus_klines",
    "refresh_focus_klines",
    "trading_session_windows",
    "trading_sessions_from_settings",
    "validate_setting_payload",
]
