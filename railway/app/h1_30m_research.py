from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Any, Iterable
from zoneinfo import ZoneInfo


STRATEGY_CODE = "h1_30m_range_research"
ENGINE_VERSION = "h1-30m-range-v1"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pct(numerator: int, denominator: int) -> float:
    return round((100.0 * numerator / denominator), 4) if denominator else 0.0


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    p = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = (p + z2 / (2.0 * total)) / denom
    margin = z * sqrt((p * (1.0 - p) / total) + z2 / (4.0 * total * total)) / denom
    return [round(max(0.0, centre - margin) * 100.0, 4), round(min(1.0, centre + margin) * 100.0, 4)]


@dataclass(frozen=True)
class Observation:
    hour_start: str
    hour_utc: int
    open_price: float
    half_close: float
    first_half_high: float
    first_half_low: float
    first_half_range: float
    upper_wick: float
    lower_wick: float
    close_position: float
    position_bucket: str
    wick_dominance: str
    body_direction: str
    previous_hour_direction: str
    outcome: str
    high_break: bool
    low_break: bool
    first_break: str
    first_break_minute: int | None


def _position_bucket(position: float) -> str:
    if position < 0.20:
        return "bottom_20"
    if position < 0.40:
        return "lower_20_40"
    if position < 0.60:
        return "middle_40_60"
    if position < 0.80:
        return "upper_60_80"
    return "top_20"


def _wick_dominance(upper: float, lower: float) -> str:
    if lower > upper * 2.0:
        return "lower_gt_2x_upper"
    if upper > lower * 2.0:
        return "upper_gt_2x_lower"
    return "balanced"


def _body_direction(open_price: float, close_price: float, epsilon: float) -> str:
    if close_price > open_price + epsilon:
        return "bullish"
    if close_price < open_price - epsilon:
        return "bearish"
    return "doji"


def _summary(observations: list[Observation]) -> dict[str, Any]:
    total = len(observations)
    outcome_counts = {key: 0 for key in ("high_only", "low_only", "both", "neither")}
    first_counts = {key: 0 for key in ("high", "low", "same_minute_ambiguous", "none")}
    high_breaks = 0
    low_breaks = 0
    for item in observations:
        outcome_counts[item.outcome] += 1
        first_counts[item.first_break] += 1
        high_breaks += int(item.high_break)
        low_breaks += int(item.low_break)
    resolved_first = first_counts["high"] + first_counts["low"]
    neither = outcome_counts["neither"]
    return {
        "n": total,
        "outcomes": {
            key: {"count": value, "rate_pct": _pct(value, total)}
            for key, value in outcome_counts.items()
        },
        "at_least_one_break": {
            "count": total - neither,
            "rate_pct": _pct(total - neither, total),
        },
        "both_extremes_survived": {
            "count": neither,
            "rate_pct": _pct(neither, total),
            "wilson_95_pct": _wilson(neither, total),
        },
        "high_break": {"count": high_breaks, "rate_pct": _pct(high_breaks, total)},
        "low_break": {"count": low_breaks, "rate_pct": _pct(low_breaks, total)},
        "first_break": {
            "high": first_counts["high"],
            "low": first_counts["low"],
            "same_minute_ambiguous": first_counts["same_minute_ambiguous"],
            "none": first_counts["none"],
            "resolved_n": resolved_first,
            "high_rate_resolved_pct": _pct(first_counts["high"], resolved_first),
            "low_rate_resolved_pct": _pct(first_counts["low"], resolved_first),
            "high_rate_wilson_95_pct": _wilson(first_counts["high"], resolved_first),
        },
    }


def _group_rows(observations: list[Observation], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Observation]] = defaultdict(list)
    for item in observations:
        groups[str(getattr(item, field))].append(item)
    rows = [{"group": key, **_summary(items)} for key, items in groups.items()]
    if field == "hour_utc":
        rows.sort(key=lambda row: int(row["group"]))
    else:
        rows.sort(key=lambda row: (-int(row["n"]), str(row["group"])))
    return rows


def _combo_rows(observations: list[Observation]) -> list[dict[str, Any]]:
    groups: dict[str, list[Observation]] = defaultdict(list)
    for item in observations:
        key = f"{item.position_bucket} | {item.wick_dominance}"
        groups[key].append(item)
    rows = [{"group": key, **_summary(items)} for key, items in groups.items()]
    rows.sort(key=lambda row: (-int(row["n"]), str(row["group"])))
    return rows


def _candidate_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["group"]): row for row in rows}


def _stable_candidates(
    full: list[Observation],
    development: list[Observation],
    untouched: list[Observation],
) -> list[dict[str, Any]]:
    definitions = {
        "price_position": lambda items: _group_rows(items, "position_bucket"),
        "wick_dominance": lambda items: _group_rows(items, "wick_dominance"),
        "body_direction": lambda items: _group_rows(items, "body_direction"),
        "hour_utc": lambda items: _group_rows(items, "hour_utc"),
        "previous_hour_direction": lambda items: _group_rows(items, "previous_hour_direction"),
        "position_x_wick": _combo_rows,
    }
    minimum_full = max(100, int(len(full) * 0.01))
    minimum_split = max(30, int(minimum_full * 0.25))
    candidates: list[dict[str, Any]] = []
    for group_type, builder in definitions.items():
        full_map = _candidate_map(builder(full))
        dev_map = _candidate_map(builder(development))
        untouched_map = _candidate_map(builder(untouched))
        for group, row in full_map.items():
            resolved = int(row["first_break"]["resolved_n"])
            dev = dev_map.get(group)
            test = untouched_map.get(group)
            if int(row["n"]) < minimum_full or resolved < minimum_full:
                continue
            if not dev or not test:
                continue
            dev_resolved = int(dev["first_break"]["resolved_n"])
            test_resolved = int(test["first_break"]["resolved_n"])
            if dev_resolved < minimum_split or test_resolved < minimum_split:
                continue
            full_rate = float(row["first_break"]["high_rate_resolved_pct"])
            dev_rate = float(dev["first_break"]["high_rate_resolved_pct"])
            test_rate = float(test["first_break"]["high_rate_resolved_pct"])
            full_side = "high" if full_rate >= 50.0 else "low"
            stable = (dev_rate >= 50.0) == (test_rate >= 50.0)
            candidates.append(
                {
                    "group_type": group_type,
                    "group": group,
                    "n": int(row["n"]),
                    "resolved_n": resolved,
                    "favoured_side": full_side,
                    "full_high_first_pct": round(full_rate, 4),
                    "development_high_first_pct": round(dev_rate, 4),
                    "untouched_high_first_pct": round(test_rate, 4),
                    "absolute_edge_pp": round(abs(full_rate - 50.0), 4),
                    "stable_direction": stable,
                }
            )
    candidates.sort(
        key=lambda item: (
            not bool(item["stable_direction"]),
            -float(item["absolute_edge_pp"]),
            -int(item["resolved_n"]),
        )
    )
    return candidates[:30]


class H1ThirtyMinuteAnalyzer:
    """Streaming M1 analyzer for the developing-H1-at-minute-30 hypothesis."""

    def __init__(self, timezone_name: str = "UTC") -> None:
        self.tz = ZoneInfo(timezone_name)
        self.timezone_name = timezone_name
        self._hour_key: datetime | None = None
        self._hour_rows: list[tuple[datetime, dict[str, Any]]] = []
        self._previous_complete_hour: datetime | None = None
        self._previous_direction = "unknown"
        self.observations: list[Observation] = []
        self.total_hour_groups = 0
        self.complete_hours = 0
        self.incomplete_hours = 0
        self.nonqualifying_hours = 0

    def push(self, candle: dict[str, Any]) -> None:
        timestamp = _as_utc(candle.get("candle_time"))
        if timestamp is None:
            return
        local = timestamp.astimezone(self.tz)
        local_hour = local.replace(minute=0, second=0, microsecond=0)
        hour_key = local_hour.astimezone(timezone.utc)
        if self._hour_key is None:
            self._hour_key = hour_key
        if hour_key != self._hour_key:
            self._flush_hour()
            self._hour_key = hour_key
            self._hour_rows = []
        self._hour_rows.append((timestamp, candle))

    def finish(self) -> dict[str, Any]:
        self._flush_hour()
        ordered = sorted(self.observations, key=lambda item: item.hour_start)
        split = int(len(ordered) * (2.0 / 3.0))
        development = ordered[:split]
        untouched = ordered[split:]
        full_summary = _summary(ordered)
        report = {
            "engine_version": ENGINE_VERSION,
            "strategy": STRATEGY_CODE,
            "timezone": self.timezone_name,
            "definition": {
                "observation_window": "minute 00:00 through 29:59 of each complete H1 period",
                "reveal_window": "minute 30:00 through 59:59",
                "qualifier": "developing H1 has a strictly positive upper wick and lower wick at minute 30",
                "high_break": "a reveal-window M1 high strictly exceeds the first-30-minute high",
                "low_break": "a reveal-window M1 low strictly falls below the first-30-minute low",
                "same_minute_rule": "if one M1 candle breaches both boundaries, first-side order is marked ambiguous, never guessed",
                "complete_hour_rule": "requires all 60 consecutive M1 candles; incomplete hours are excluded",
            },
            "data_quality": {
                "hour_groups_seen": self.total_hour_groups,
                "complete_hours": self.complete_hours,
                "incomplete_hours_excluded": self.incomplete_hours,
                "complete_hours_without_two_wicks": self.nonqualifying_hours,
                "qualifying_two_wick_hours": len(ordered),
                "qualifying_rate_of_complete_hours_pct": _pct(len(ordered), self.complete_hours),
            },
            "full": full_summary,
            "chronological_split": {
                "development_first_two_thirds": _summary(development),
                "untouched_final_third": _summary(untouched),
            },
            "breakdowns": {
                "hour_utc": _group_rows(ordered, "hour_utc"),
                "price_position": _group_rows(ordered, "position_bucket"),
                "wick_dominance": _group_rows(ordered, "wick_dominance"),
                "body_direction": _group_rows(ordered, "body_direction"),
                "previous_hour_direction": _group_rows(ordered, "previous_hour_direction"),
                "position_x_wick": _combo_rows(ordered),
            },
            "stable_directional_candidates": _stable_candidates(ordered, development, untouched),
        }
        return report

    def _flush_hour(self) -> None:
        if self._hour_key is None or not self._hour_rows:
            return
        self.total_hour_groups += 1
        rows = sorted(self._hour_rows, key=lambda item: item[0])
        timestamps = [item[0] for item in rows]
        complete = len(rows) == 60 and all(
            timestamps[index] == timestamps[0] + timedelta(minutes=index)
            for index in range(60)
        )
        if not complete:
            self.incomplete_hours += 1
            self._hour_rows = []
            return

        self.complete_hours += 1
        previous_direction = "unknown"
        if self._previous_complete_hour is not None and self._hour_key == self._previous_complete_hour + timedelta(hours=1):
            previous_direction = self._previous_direction

        first = [row for _, row in rows[:30]]
        second = [(ts, row) for ts, row in rows[30:]]
        open_price = _number(first[0].get("open"))
        half_close = _number(first[-1].get("close"))
        first_high = max(_number(row.get("high")) for row in first)
        first_low = min(_number(row.get("low")) for row in first)
        first_range = first_high - first_low
        epsilon = max(abs(first_range) * 1e-9, 1e-12)
        upper_wick = first_high - max(open_price, half_close)
        lower_wick = min(open_price, half_close) - first_low

        final_close = _number(rows[-1][1].get("close"))
        self._previous_direction = _body_direction(open_price, final_close, epsilon)
        self._previous_complete_hour = self._hour_key

        if first_range <= epsilon or upper_wick <= epsilon or lower_wick <= epsilon:
            self.nonqualifying_hours += 1
            self._hour_rows = []
            return

        high_break = False
        low_break = False
        first_break = "none"
        first_break_minute: int | None = None
        for timestamp, row in second:
            hit_high = _number(row.get("high")) > first_high + epsilon
            hit_low = _number(row.get("low")) < first_low - epsilon
            high_break = high_break or hit_high
            low_break = low_break or hit_low
            if first_break == "none" and (hit_high or hit_low):
                first_break_minute = int((timestamp - timestamps[0]).total_seconds() // 60)
                if hit_high and hit_low:
                    first_break = "same_minute_ambiguous"
                elif hit_high:
                    first_break = "high"
                else:
                    first_break = "low"

        if high_break and low_break:
            outcome = "both"
        elif high_break:
            outcome = "high_only"
        elif low_break:
            outcome = "low_only"
        else:
            outcome = "neither"

        close_position = min(1.0, max(0.0, (half_close - first_low) / first_range))
        self.observations.append(
            Observation(
                hour_start=self._hour_key.isoformat(),
                hour_utc=self._hour_key.hour,
                open_price=round(open_price, 10),
                half_close=round(half_close, 10),
                first_half_high=round(first_high, 10),
                first_half_low=round(first_low, 10),
                first_half_range=round(first_range, 10),
                upper_wick=round(upper_wick, 10),
                lower_wick=round(lower_wick, 10),
                close_position=round(close_position, 8),
                position_bucket=_position_bucket(close_position),
                wick_dominance=_wick_dominance(upper_wick, lower_wick),
                body_direction=_body_direction(open_price, half_close, epsilon),
                previous_hour_direction=previous_direction,
                outcome=outcome,
                high_break=high_break,
                low_break=low_break,
                first_break=first_break,
                first_break_minute=first_break_minute,
            )
        )
        self._hour_rows = []


def analyze_candles(candles: Iterable[dict[str, Any]], timezone_name: str = "UTC") -> dict[str, Any]:
    analyzer = H1ThirtyMinuteAnalyzer(timezone_name)
    for candle in candles:
        analyzer.push(candle)
    return analyzer.finish()


def observation_as_dict(item: Observation) -> dict[str, Any]:
    return asdict(item)
