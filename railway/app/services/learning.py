from __future__ import annotations

import asyncio
import calendar
import logging
import math
import socket
import statistics
import uuid
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.services.supabase_repo import SupabaseRepository

logger = logging.getLogger(__name__)

FEATURE_VERSION = "eve-features-v1"
SOURCE_INTERVAL = "5min"
SNAPSHOT_INTERVAL = "15min"
LOOKBACK_BARS = 288
MAX_FUTURE_BARS = 48
HORIZON_BARS = {5: 1, 15: 3, 30: 6, 60: 12, 240: 48}
CONTEXT_INTERVAL_SECONDS = {"15min": 900, "1h": 3600, "4h": 14400, "1day": 86400}
UPSERT_BATCH_SIZE = 500
PAGE_SIZE = 1000
LONDON_TZ = ZoneInfo("Europe/London")
NEW_YORK_TZ = ZoneInfo("America/New_York")


def as_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def parse_candle(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = as_utc(row.get("candle_time"))
    if timestamp is None:
        raise ValueError("Candle has no candle_time")
    return {
        "candle_time": timestamp,
        "open": number(row.get("open")),
        "high": number(row.get("high")),
        "low": number(row.get("low")),
        "close": number(row.get("close")),
        "volume": None if row.get("volume") is None else number(row.get("volume")),
    }


def safe_pct(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return ((current / previous) - 1.0) * 100.0


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def standard_deviation(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.pstdev(items) if len(items) >= 2 else 0.0


def true_range(current: dict[str, Any], previous_close: float | None) -> float:
    if previous_close is None:
        return max(0.0, current["high"] - current["low"])
    return max(
        current["high"] - current["low"],
        abs(current["high"] - previous_close),
        abs(current["low"] - previous_close),
    )


def linear_slope(values: list[float]) -> float:
    count = len(values)
    if count < 2:
        return 0.0
    x_mean = (count - 1) / 2.0
    y_mean = mean(values)
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    return numerator / denominator if denominator else 0.0


def direction(value: float, tolerance: float = 1e-12) -> int:
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def candle_streak(history_and_current: list[dict[str, Any]], maximum: int = 12) -> int:
    streak = 0
    current_direction = 0
    for candle in reversed(history_and_current[-maximum:]):
        candle_direction = direction(candle["close"] - candle["open"])
        if candle_direction == 0:
            break
        if current_direction == 0:
            current_direction = candle_direction
        if candle_direction != current_direction:
            break
        streak += candle_direction
    return streak


def session_name(timestamp: datetime) -> str:
    london = timestamp.astimezone(LONDON_TZ)
    new_york = timestamp.astimezone(NEW_YORK_TZ)
    utc_hour = timestamp.hour

    # New York takes precedence during the London/New York overlap.
    if 8 <= new_york.hour < 17:
        return "new_york"
    if 8 <= london.hour < 13:
        return "london"
    if 0 <= utc_hour < 7:
        return "asia"
    return "off_session"


def is_snapshot_anchor(timestamp: datetime) -> bool:
    return timestamp.minute % 15 == 0 and timestamp.second == 0


def regime_name(atr: float, average_range_12: float, compression_ratio: float, trend_12_atr: float) -> str:
    if compression_ratio < 0.72:
        return "compression"
    if abs(trend_12_atr) >= 0.18:
        return "trend_up" if trend_12_atr > 0 else "trend_down"
    if average_range_12 > 0 and atr >= average_range_12 * 1.25:
        return "high_volatility"
    return "range"


def _outcome_for_horizon(
    current: dict[str, Any],
    future: list[dict[str, Any]],
    horizon_bars: int,
    atr: float,
) -> dict[str, Any] | None:
    if len(future) < horizon_bars:
        return None
    segment = future[:horizon_bars]
    close = current["close"]
    threshold = max(atr * 0.25, close * 0.00005, 1e-9)
    maximum_high = max(item["high"] for item in segment)
    minimum_low = min(item["low"] for item in segment)
    max_up = maximum_high - close
    max_down = close - minimum_low
    close_change = segment[-1]["close"] - close

    first_side = "none"
    for candle in segment:
        hit_up = candle["high"] - close >= threshold
        hit_down = close - candle["low"] >= threshold
        if hit_up and hit_down:
            first_side = "ambiguous"
            break
        if hit_up:
            first_side = "up"
            break
        if hit_down:
            first_side = "down"
            break

    if close_change > threshold:
        outcome_direction = "up"
    elif close_change < -threshold:
        outcome_direction = "down"
    else:
        outcome_direction = "flat"

    current_direction = direction(current["close"] - current["open"])
    future_direction = direction(close_change, threshold)
    continuation = current_direction != 0 and future_direction == current_direction

    return {
        "close_return_pct": round(safe_pct(segment[-1]["close"], close), 8),
        "max_up_price": round(max_up, 8),
        "max_down_price": round(max_down, 8),
        "max_up_atr": round(max_up / atr, 6) if atr > 0 else None,
        "max_down_atr": round(max_down / atr, 6) if atr > 0 else None,
        "direction": outcome_direction,
        "first_side": first_side,
        "continuation": continuation,
    }


class ContextLookup:
    def __init__(self, points: list[tuple[datetime, float]]) -> None:
        self.times = [point[0] for point in points]
        self.values = [point[1] for point in points]

    def at(self, timestamp: datetime) -> float | None:
        index = bisect_right(self.times, timestamp) - 1
        return self.values[index] if index >= 0 else None


def build_learning_snapshot(
    symbol: str,
    previous: list[dict[str, Any]],
    current: dict[str, Any],
    future: list[dict[str, Any]],
    context_returns: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    if len(previous) < LOOKBACK_BARS:
        raise ValueError(f"At least {LOOKBACK_BARS} prior M5 candles are required")

    timestamp: datetime = current["candle_time"]
    all_bars = previous + [current]
    current_range = max(0.0, current["high"] - current["low"])
    body = current["close"] - current["open"]
    upper_wick = current["high"] - max(current["open"], current["close"])
    lower_wick = min(current["open"], current["close"]) - current["low"]
    close_location = (current["close"] - current["low"]) / current_range if current_range > 0 else 0.5

    recent_14 = all_bars[-14:]
    true_ranges: list[float] = []
    for index, candle in enumerate(recent_14):
        previous_close = recent_14[index - 1]["close"] if index > 0 else previous[-14]["close"]
        true_ranges.append(true_range(candle, previous_close))
    atr_14 = mean(true_ranges)

    ranges_3 = [item["high"] - item["low"] for item in all_bars[-3:]]
    ranges_12 = [item["high"] - item["low"] for item in all_bars[-12:]]
    average_range_12 = mean(ranges_12)
    compression_ratio = mean(ranges_3) / average_range_12 if average_range_12 > 0 else 1.0

    closes_13 = [item["close"] for item in all_bars[-13:]]
    log_returns = [math.log(closes_13[index] / closes_13[index - 1]) for index in range(1, len(closes_13)) if closes_13[index - 1] > 0]
    volatility_12 = standard_deviation(log_returns) * 100.0

    closes_12 = [item["close"] for item in all_bars[-12:]]
    closes_48 = [item["close"] for item in all_bars[-48:]]
    trend_12_atr = linear_slope(closes_12) / atr_14 if atr_14 > 0 else 0.0
    trend_48_atr = linear_slope(closes_48) / atr_14 if atr_14 > 0 else 0.0

    return_1 = safe_pct(current["close"], previous[-1]["close"])
    return_3 = safe_pct(current["close"], previous[-3]["close"])
    return_12 = safe_pct(current["close"], previous[-12]["close"])
    return_48 = safe_pct(current["close"], previous[-48]["close"])
    return_288 = safe_pct(current["close"], previous[-288]["close"])

    context_returns = context_returns or {}
    context_m15 = context_returns.get("15min")
    context_h1 = context_returns.get("1h")
    context_h4 = context_returns.get("4h")
    context_d1 = context_returns.get("1day")
    actual_context = [item for item in (context_m15, context_h1, context_h4, context_d1) if item is not None]
    alignment_source = actual_context if actual_context else [return_3, return_12, return_48, return_288]
    alignment = sum(direction(item) for item in alignment_source)
    regime = regime_name(atr_14, average_range_12, compression_ratio, trend_12_atr)

    outcomes: dict[str, Any] = {}
    horizons: list[int] = []
    for horizon_minutes, horizon_bars in HORIZON_BARS.items():
        result = _outcome_for_horizon(current, future, horizon_bars, atr_14)
        if result is not None:
            outcomes[str(horizon_minutes)] = result
            horizons.append(horizon_minutes)

    return {
        "symbol": symbol,
        "snapshot_interval": SNAPSHOT_INTERVAL,
        "source_interval": SOURCE_INTERVAL,
        "candle_time": timestamp.isoformat(),
        "open": current["open"],
        "high": current["high"],
        "low": current["low"],
        "close": current["close"],
        "volume": current["volume"],
        "weekday": timestamp.isoweekday(),
        "month": timestamp.month,
        "quarter": ((timestamp.month - 1) // 3) + 1,
        "hour_utc": timestamp.hour,
        "week_of_month": ((timestamp.day - 1) // 7) + 1,
        "session": session_name(timestamp),
        "direction": direction(body),
        "range_price": current_range,
        "body_price": body,
        "upper_wick": max(0.0, upper_wick),
        "lower_wick": max(0.0, lower_wick),
        "close_location": close_location,
        "atr_14": atr_14,
        "average_range_12": average_range_12,
        "volatility_12": volatility_12,
        "compression_ratio": compression_ratio,
        "return_1_pct": return_1,
        "return_3_pct": return_3,
        "return_12_pct": return_12,
        "return_48_pct": return_48,
        "return_288_pct": return_288,
        "context_m15_return_pct": context_m15,
        "context_h1_return_pct": context_h1,
        "context_h4_return_pct": context_h4,
        "context_d1_return_pct": context_d1,
        "trend_12_atr": trend_12_atr,
        "trend_48_atr": trend_48_atr,
        "streak": candle_streak(all_bars),
        "regime": regime,
        "alignment_score": alignment,
        "outcomes": outcomes,
        "outcome_horizons": horizons,
        "outcome_complete": len(horizons) == len(HORIZON_BARS),
        "feature_version": FEATURE_VERSION,
    }


def _daily_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {
            "sample_count": 0,
            "average_range": 0.0,
            "median_range": 0.0,
            "average_range_pct": 0.0,
            "median_range_pct": 0.0,
            "average_return_pct": 0.0,
            "average_absolute_return_pct": 0.0,
            "positive_close_rate": 0.0,
            "directional_day_rate": 0.0,
        }
    ranges = [max(0.0, item["high"] - item["low"]) for item in rows]
    range_pcts = [(ranges[index] / item["open"]) * 100.0 if item["open"] else 0.0 for index, item in enumerate(rows)]
    returns = [safe_pct(item["close"], item["open"]) for item in rows]
    directional = [1.0 if ranges[index] > 0 and abs(item["close"] - item["open"]) / ranges[index] >= 0.6 else 0.0 for index, item in enumerate(rows)]
    return {
        "sample_count": len(rows),
        "average_range": mean(ranges),
        "median_range": statistics.median(ranges),
        "average_range_pct": mean(range_pcts),
        "median_range_pct": statistics.median(range_pcts),
        "average_return_pct": mean(returns),
        "average_absolute_return_pct": mean(abs(value) for value in returns),
        "positive_close_rate": mean(1.0 if value > 0 else 0.0 for value in returns) * 100.0,
        "directional_day_rate": mean(directional) * 100.0,
    }


def build_calendar_statistics(symbol: str, daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not daily_rows:
        return []
    parsed = [parse_candle(row) if not isinstance(row.get("candle_time"), datetime) else row for row in daily_rows]
    parsed.sort(key=lambda item: item["candle_time"])
    baseline = _daily_metrics(parsed)
    baseline_range = baseline["average_range_pct"]
    calculated_from = parsed[0]["candle_time"].isoformat()
    calculated_to = parsed[-1]["candle_time"].isoformat()

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    weekday_labels = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    for row in parsed:
        timestamp: datetime = row["candle_time"]
        groups[("weekday", str(timestamp.isoweekday()), weekday_labels[timestamp.isoweekday()])].append(row)
        groups[("month", str(timestamp.month), calendar.month_name[timestamp.month])].append(row)
        quarter = ((timestamp.month - 1) // 3) + 1
        groups[("quarter", str(quarter), f"Quarter {quarter}")].append(row)

    output: list[dict[str, Any]] = []
    for (dimension, bucket_key, label), rows in groups.items():
        metrics = _daily_metrics(rows)
        effect = ((metrics["average_range_pct"] / baseline_range) - 1.0) * 100.0 if baseline_range > 0 else 0.0
        output.append({
            "symbol": symbol,
            "dimension": dimension,
            "bucket_key": bucket_key,
            "bucket_label": label,
            "sample_count": metrics["sample_count"],
            "average_range": metrics["average_range"],
            "median_range": metrics["median_range"],
            "average_range_pct": metrics["average_range_pct"],
            "median_range_pct": metrics["median_range_pct"],
            "average_return_pct": metrics["average_return_pct"],
            "average_absolute_return_pct": metrics["average_absolute_return_pct"],
            "positive_close_rate": metrics["positive_close_rate"],
            "directional_day_rate": metrics["directional_day_rate"],
            "effect_vs_baseline_pct": effect,
            "metrics": {"baseline_average_range_pct": baseline_range},
            "calculated_from": calculated_from,
            "calculated_to": calculated_to,
        })
    return output


def generate_research_questions(symbol: str, statistics_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in statistics_rows:
        by_dimension[row["dimension"]].append(row)

    questions: list[dict[str, Any]] = [
        {
            "question_key": "compression-next-60m-expansion",
            "symbol": symbol,
            "category": "volatility",
            "question": "After unusually compressed M5 ranges, is the next 60-minute move larger than normal?",
            "rationale": "EVE now stores compression ratios and 60-minute outcomes for every research snapshot.",
            "priority": 88,
            "generated_by": "eve-learning-foundation",
            "evidence": {},
            "test_definition": {"feature": "compression_ratio", "outcome": "60.max_up_atr/60.max_down_atr"},
        },
        {
            "question_key": "three-candle-momentum-continuation",
            "symbol": symbol,
            "category": "momentum",
            "question": "When three M5 candles move in one direction, how often does price continue over the next 30 minutes?",
            "rationale": "Direction streaks and 30-minute continuation outcomes are now recorded.",
            "priority": 86,
            "generated_by": "eve-learning-foundation",
            "evidence": {},
            "test_definition": {"feature": "streak", "outcome": "30.continuation"},
        },
        {
            "question_key": "multihorizon-alignment-60m",
            "symbol": symbol,
            "category": "multi_timeframe",
            "question": "Does agreement between 15-minute, H1, H4 and daily momentum improve 60-minute continuation?",
            "rationale": "Each snapshot includes a four-horizon alignment score.",
            "priority": 92,
            "generated_by": "eve-learning-foundation",
            "evidence": {},
            "test_definition": {"feature": "alignment_score", "outcome": "60.direction"},
        },
        {
            "question_key": "session-weekday-interaction",
            "symbol": symbol,
            "category": "calendar",
            "question": "Which weekday and session combinations produce the strongest directional outcomes?",
            "rationale": "Session, weekday and forward outcomes are attached to the same historical snapshots.",
            "priority": 82,
            "generated_by": "eve-learning-foundation",
            "evidence": {},
            "test_definition": {"features": ["weekday", "session"], "outcome": "60.close_return_pct"},
        },
        {
            "question_key": "regime-pattern-failure",
            "symbol": symbol,
            "category": "regime",
            "question": "Which patterns succeed in a trend but fail when the market is ranging or compressed?",
            "rationale": "EVE classifies every snapshot into trend, range, compression or high-volatility regimes.",
            "priority": 90,
            "generated_by": "eve-learning-foundation",
            "evidence": {},
            "test_definition": {"feature": "regime", "outcomes": ["30", "60", "240"]},
        },
    ]

    for dimension, label in (("weekday", "weekday"), ("month", "month")):
        rows = by_dimension.get(dimension, [])
        if not rows:
            continue
        range_leader = max(rows, key=lambda item: number(item.get("average_range_pct")))
        directional_leader = max(rows, key=lambda item: number(item.get("directional_day_rate")))
        questions.extend([
            {
                "question_key": f"why-{dimension}-{range_leader['bucket_key']}-range-leader",
                "symbol": symbol,
                "category": "calendar",
                "question": f"Why has {range_leader['bucket_label']} produced the largest average daily range among all {label}s?",
                "rationale": f"Its average range is {number(range_leader.get('effect_vs_baseline_pct')):.1f}% versus the all-day baseline.",
                "priority": 84,
                "generated_by": "eve-calendar-observer",
                "evidence": range_leader,
                "test_definition": {"dimension": dimension, "bucket": range_leader["bucket_key"], "metric": "average_range_pct"},
            },
            {
                "question_key": f"why-{dimension}-{directional_leader['bucket_key']}-directional-leader",
                "symbol": symbol,
                "category": "calendar",
                "question": f"What conditions make {directional_leader['bucket_label']} the most directional {label}?",
                "rationale": f"Directional-day rate: {number(directional_leader.get('directional_day_rate')):.1f}% across {directional_leader['sample_count']} observations.",
                "priority": 80,
                "generated_by": "eve-calendar-observer",
                "evidence": directional_leader,
                "test_definition": {"dimension": dimension, "bucket": directional_leader["bucket_key"], "metric": "directional_day_rate"},
            },
        ])
    return questions


def generate_calendar_discoveries(symbol: str, statistics_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    discoveries: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in statistics_rows:
        grouped[row["dimension"]].append(row)

    for dimension in ("weekday", "month"):
        rows = grouped.get(dimension, [])
        if not rows:
            continue
        leader = max(rows, key=lambda item: number(item.get("effect_vs_baseline_pct")))
        effect = number(leader.get("effect_vs_baseline_pct"))
        samples = int(leader.get("sample_count") or 0)
        if effect < 5.0 or samples < 40:
            continue
        confidence = min(85.0, 45.0 + min(25.0, samples / 20.0) + min(15.0, effect / 2.0))
        discoveries.append({
            "discovery_key": f"calendar-{dimension}-{leader['bucket_key']}-range",
            "symbol": symbol,
            "title": f"{leader['bucket_label']} has produced above-baseline daily ranges",
            "summary": f"Across {samples:,} daily observations, average range was {effect:.1f}% above the full-history baseline. This is exploratory until it survives year-by-year and unseen-period testing.",
            "category": "calendar",
            "status": "exploratory",
            "sample_count": samples,
            "effect_size": effect,
            "confidence_score": confidence,
            "stability_score": None,
            "evidence": leader,
            "first_observed_at": leader.get("calculated_from"),
            "last_observed_at": leader.get("calculated_to"),
        })
    return discoveries


class LearningService:
    def __init__(self, repo: SupabaseRepository) -> None:
        self.repo = repo
        self.worker_id = f"learning-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    async def worker_loop(self) -> None:
        logger.info("Learning worker %s started", self.worker_id)
        try:
            await self.repo.reset_stale_learning_runs(stale_minutes=0)
        except Exception:
            logger.exception("Could not reset interrupted learning runs. Has the v1.5 SQL been applied?")
        while not self._stop.is_set():
            try:
                run = await self.repo.claim_next_learning_run(self.worker_id)
                if not run:
                    await asyncio.sleep(5)
                    continue
                await self._run(run)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Learning worker loop error")
                await asyncio.sleep(10)

    async def _run(self, run: dict[str, Any]) -> None:
        run_id = str(run["id"])
        symbol = str(run.get("symbol") or "XAU/USD")
        full_rebuild = bool(run.get("full_rebuild"))
        try:
            await self.repo.upsert_learning_state(
                symbol,
                SNAPSHOT_INTERVAL,
                status="building",
                last_run_id=run_id,
                last_error=None,
            )
            await self.repo.log_event(
                "info",
                "learning",
                "EVE learning foundation build started",
                {"run_id": run_id, "full_rebuild": full_rebuild},
            )
            await self.build_foundation(run_id, symbol, full_rebuild)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Learning run %s failed", run_id)
            await self.repo.update_learning_run(
                run_id,
                status="failed",
                stage="failed",
                message="Learning build failed — see Railway logs",
                error=str(exc)[:4000],
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.upsert_learning_state(
                symbol,
                SNAPSHOT_INTERVAL,
                status="error",
                last_error=str(exc)[:4000],
            )
            await self.repo.log_event(
                "error",
                "learning",
                "EVE learning foundation build failed",
                {"run_id": run_id, "error": str(exc)},
            )

    async def _cancelled(self, run_id: str) -> bool:
        current = await self.repo.get_learning_run(run_id)
        return bool(current and current.get("status") == "cancelled")

    async def _fetch_all_candles(self, symbol: str, interval: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            page = await self.repo.fetch_candles_page(symbol, interval, after=after, limit=PAGE_SIZE)
            if not page:
                break
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                break
            after = str(page[-1]["candle_time"])
        return rows

    async def _fetch_context_lookup(self, symbol: str, interval: str) -> ContextLookup:
        seconds = CONTEXT_INTERVAL_SECONDS[interval]
        points: list[tuple[datetime, float]] = []
        after: str | None = None
        while True:
            page = await self.repo.fetch_candles_page(symbol, interval, after=after, limit=PAGE_SIZE)
            if not page:
                break
            for row in page:
                candle = parse_candle(row)
                completed_at = candle["candle_time"] + timedelta(seconds=seconds)
                points.append((completed_at, safe_pct(candle["close"], candle["open"])))
            if len(page) < PAGE_SIZE:
                break
            after = str(page[-1]["candle_time"])
        return ContextLookup(points)

    @staticmethod
    def _context_at(lookups: dict[str, ContextLookup], timestamp: datetime) -> dict[str, float | None]:
        return {interval: lookup.at(timestamp) for interval, lookup in lookups.items()}

    async def build_foundation(self, run_id: str, symbol: str, full_rebuild: bool) -> None:
        state = await self.repo.get_learning_state(symbol, SNAPSHOT_INTERVAL) or {}
        run = await self.repo.get_learning_run(run_id) or {}
        resume_cursor = as_utc(run.get("cursor_time"))
        last_snapshot = as_utc(state.get("last_snapshot_time"))

        if full_rebuild and not resume_cursor:
            await self.repo.update_learning_run(run_id, stage="resetting", progress_percent=1, message="Resetting generated learning data")
            await self.repo.delete_learning_generated_data(symbol, SNAPSHOT_INTERVAL)
            last_snapshot = None

        if resume_cursor:
            output_after = resume_cursor
            source_from = resume_cursor - timedelta(days=5)
        elif last_snapshot and not full_rebuild:
            # Rebuild the recent tail so previously incomplete 240-minute labels are completed.
            output_after = last_snapshot - timedelta(days=1)
            source_from = last_snapshot - timedelta(days=5)
        else:
            output_after = None
            source_from = None

        await self.repo.update_learning_run(
            run_id,
            stage="loading_context",
            progress_percent=2,
            message="Loading completed M15, H1, H4 and D1 context without look-ahead",
        )
        context_lookups: dict[str, ContextLookup] = {}
        for interval in CONTEXT_INTERVAL_SECONDS:
            context_lookups[interval] = await self._fetch_context_lookup(symbol, interval)

        total_source = await self.repo.count_market_candles(
            symbol,
            SOURCE_INTERVAL,
            date_from=source_from.isoformat() if source_from else None,
        )
        if total_source < LOOKBACK_BARS + 2:
            raise RuntimeError("Not enough M5 history is stored to build the learning foundation")

        await self.repo.update_learning_run(
            run_id,
            stage="feature_engine",
            progress_percent=6,
            message="Building multi-timeframe research snapshots from M5 history",
        )

        buffer: list[dict[str, Any]] = []
        offset = 0
        after: str | None = None
        source_scanned = 0
        snapshots_written = int(run.get("snapshots_written") or 0)
        labels_written = int(run.get("outcome_labels_written") or 0)
        insert_batch: list[dict[str, Any]] = []
        last_output_time: datetime | None = resume_cursor

        while True:
            page = await self.repo.fetch_candles_page(
                symbol,
                SOURCE_INTERVAL,
                after=after,
                date_from=source_from.isoformat() if source_from and after is None else None,
                limit=PAGE_SIZE,
            )
            if not page:
                break
            parsed_page = [parse_candle(item) for item in page]
            buffer.extend(parsed_page)
            after = str(page[-1]["candle_time"])
            source_scanned += len(parsed_page)

            while len(buffer) - offset >= LOOKBACK_BARS + MAX_FUTURE_BARS + 1:
                candidate_index = offset + LOOKBACK_BARS
                current = buffer[candidate_index]
                if is_snapshot_anchor(current["candle_time"]) and (output_after is None or current["candle_time"] > output_after):
                    snapshot = build_learning_snapshot(
                        symbol,
                        buffer[offset:candidate_index],
                        current,
                        buffer[candidate_index + 1:candidate_index + 1 + MAX_FUTURE_BARS],
                        self._context_at(context_lookups, current["candle_time"]),
                    )
                    insert_batch.append(snapshot)
                    last_output_time = current["candle_time"]
                offset += 1

                if len(insert_batch) >= UPSERT_BATCH_SIZE:
                    await self.repo.bulk_upsert_learning_snapshots(insert_batch, chunk_size=UPSERT_BATCH_SIZE)
                    snapshots_written += len(insert_batch)
                    labels_written += sum(len(item["outcome_horizons"]) for item in insert_batch)
                    insert_batch.clear()
                    progress = min(86.0, 6.0 + (source_scanned / max(total_source, 1)) * 80.0)
                    await self.repo.update_learning_run(
                        run_id,
                        stage="feature_engine",
                        progress_percent=progress,
                        cursor_time=last_output_time.isoformat() if last_output_time else None,
                        source_rows_scanned=source_scanned,
                        snapshots_written=snapshots_written,
                        outcome_labels_written=labels_written,
                        message=f"Created {snapshots_written:,} research snapshots",
                    )
                    if await self._cancelled(run_id):
                        await self.repo.upsert_learning_state(symbol, SNAPSHOT_INTERVAL, status="queued")
                        return
                    await asyncio.sleep(0)

            if offset > 5000:
                buffer = buffer[offset:]
                offset = 0
            if len(page) < PAGE_SIZE:
                break

        # Store the most recent anchors even when one or more forward horizons are not yet available.
        while len(buffer) - offset > LOOKBACK_BARS:
            candidate_index = offset + LOOKBACK_BARS
            current = buffer[candidate_index]
            if is_snapshot_anchor(current["candle_time"]) and (output_after is None or current["candle_time"] > output_after):
                snapshot = build_learning_snapshot(
                    symbol,
                    buffer[offset:candidate_index],
                    current,
                    buffer[candidate_index + 1:],
                    self._context_at(context_lookups, current["candle_time"]),
                )
                insert_batch.append(snapshot)
                last_output_time = current["candle_time"]
            offset += 1

        if insert_batch:
            await self.repo.bulk_upsert_learning_snapshots(insert_batch, chunk_size=UPSERT_BATCH_SIZE)
            snapshots_written += len(insert_batch)
            labels_written += sum(len(item["outcome_horizons"]) for item in insert_batch)

        if await self._cancelled(run_id):
            await self.repo.upsert_learning_state(symbol, SNAPSHOT_INTERVAL, status="queued")
            return

        await self.repo.update_learning_run(
            run_id,
            stage="calendar_intelligence",
            progress_percent=88,
            cursor_time=last_output_time.isoformat() if last_output_time else None,
            source_rows_scanned=source_scanned,
            snapshots_written=snapshots_written,
            outcome_labels_written=labels_written,
            message="Analysing weekdays, months and quarters from complete D1 history",
        )
        daily_rows = await self._fetch_all_candles(symbol, "1day")
        calendar_rows = build_calendar_statistics(symbol, daily_rows)
        await self.repo.replace_calendar_statistics(symbol, calendar_rows)

        await self.repo.update_learning_run(
            run_id,
            stage="question_engine",
            progress_percent=94,
            message="EVE is generating its first evidence-led research questions",
        )
        questions = generate_research_questions(symbol, calendar_rows)
        await self.repo.upsert_research_questions(questions)
        discoveries = generate_calendar_discoveries(symbol, calendar_rows)
        await self.repo.upsert_discoveries(discoveries)

        await self.repo.refresh_learning_state(symbol, SNAPSHOT_INTERVAL)
        await self.repo.upsert_learning_state(
            symbol,
            SNAPSHOT_INTERVAL,
            status="ready",
            initial_build_complete=True,
            feature_version=FEATURE_VERSION,
            last_run_id=run_id,
            last_success_at=datetime.now(timezone.utc).isoformat(),
            last_error=None,
            approved_model_key=state.get("approved_model_key") or "baseline-statistics-v1",
            last_incremental_learning_at=datetime.now(timezone.utc).isoformat(),
            autonomous_learning_enabled=True,
            autonomous_status="active",
        )
        await self.repo.update_learning_run(
            run_id,
            status="complete",
            stage="complete",
            progress_percent=100,
            cursor_time=last_output_time.isoformat() if last_output_time else None,
            source_rows_scanned=source_scanned,
            snapshots_written=snapshots_written,
            outcome_labels_written=labels_written,
            questions_generated=len(questions),
            discoveries_created=len(discoveries),
            message="Learning foundation ready. Autonomous learning, historical research and Strategy Lab will maintain, investigate and convert it into testable ideas without button presses.",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        await self.repo.log_event(
            "success",
            "learning",
            "EVE learning foundation is ready",
            {
                "run_id": run_id,
                "snapshots_written": snapshots_written,
                "outcome_labels_written": labels_written,
                "questions_generated": len(questions),
                "discoveries_created": len(discoveries),
            },
        )
