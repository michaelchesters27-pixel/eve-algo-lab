from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import socket
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.services.autonomy import number, split_chronologically
from app.services.historical_research import predicate_from_definition
from app.services.learning import SNAPSHOT_INTERVAL, as_utc
from app.services.strategy_lab import candidate_direction
from app.services.supabase_repo import SupabaseRepository
from app.settings import Settings

logger = logging.getLogger(__name__)

VALIDATION_ENGINE_VERSION = "m1-validation-v2.3"
SOURCE_BAR_MINUTES = 5
MIN_VALIDATION_TRADES = 35
MIN_LOCKED_TRADES = 50
MAX_SEEDS = 12


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def validation_key(source_kind: str, source_id: str, rules: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical({"source_kind": source_kind, "source_id": source_id, "rules": rules}).encode()).hexdigest()
    return f"m1-validation-{digest[:28]}"


@dataclass(frozen=True)
class TradeIntent:
    snapshot_time: datetime
    entry_time: datetime
    direction: int
    atr: float
    year: int
    month: int
    weekday: int
    session: str
    regime: str


@dataclass(frozen=True)
class ReplayTrade:
    snapshot_time: datetime
    entry_time: datetime
    exit_time: datetime
    direction: int
    gross_r: float
    net_r: float
    exit_reason: str
    year: int
    month: int
    weekday: int
    session: str
    regime: str


@dataclass
class ReplayMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    yearly_expectancy: dict[str, float]
    monthly_expectancy: dict[str, float]
    weekday_expectancy: dict[str, float]
    session_expectancy: dict[str, float]
    regime_expectancy: dict[str, float]
    year_stability: float
    unresolved: int
    resolved_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "net_r": round(self.net_r, 6),
            "expectancy_r": round(self.expectancy_r, 6),
            "profit_factor": round(self.profit_factor, 6),
            "max_drawdown_r": round(self.max_drawdown_r, 6),
            "yearly_expectancy": {key: round(value, 6) for key, value in self.yearly_expectancy.items()},
            "monthly_expectancy": {key: round(value, 6) for key, value in self.monthly_expectancy.items()},
            "weekday_expectancy": {key: round(value, 6) for key, value in self.weekday_expectancy.items()},
            "session_expectancy": {key: round(value, 6) for key, value in self.session_expectancy.items()},
            "regime_expectancy": {key: round(value, 6) for key, value in self.regime_expectancy.items()},
            "year_stability": round(self.year_stability, 6),
            "unresolved": self.unresolved,
            "resolved_rate": round(self.resolved_rate, 6),
        }


def build_trade_intents(rows: list[dict[str, Any]], rules: dict[str, Any]) -> list[TradeIntent]:
    predicate = predicate_from_definition({"conditions": rules.get("source_conditions") or []})
    condition_mode = str(rules.get("condition_mode") or "include")
    direction_rule = str(rules.get("direction_rule") or "current_direction")
    cooldown = max(5, int(number(rules.get("cooldown_minutes"), rules.get("horizon_minutes") or 60)))
    next_allowed: datetime | None = None
    intents: list[TradeIntent] = []

    for row in rows:
        snapshot_time = as_utc(row.get("candle_time"))
        if snapshot_time is None:
            continue
        if next_allowed and snapshot_time < next_allowed:
            continue
        matches = predicate(row)
        eligible = matches if condition_mode == "include" else not matches
        if not eligible:
            continue
        direction = candidate_direction(row, direction_rule)
        atr = number(row.get("atr_14"))
        if direction == 0 or atr <= 0:
            continue
        # A Twelve Data M5 candle timestamp is its opening time. Its features are
        # only knowable after that candle closes, so replay enters on the first M1
        # bar at or after +5 minutes. This removes same-candle look-ahead.
        entry_time = snapshot_time + timedelta(minutes=SOURCE_BAR_MINUTES)
        intents.append(
            TradeIntent(
                snapshot_time=snapshot_time,
                entry_time=entry_time,
                direction=direction,
                atr=atr,
                year=snapshot_time.year,
                month=snapshot_time.month,
                weekday=snapshot_time.isoweekday(),
                session=str(row.get("session") or "unknown"),
                regime=str(row.get("regime") or "unknown"),
            )
        )
        next_allowed = snapshot_time + timedelta(minutes=cooldown)
    return intents


def _candle_value(candle: dict[str, Any], key: str) -> float:
    return number(candle.get(key))


def replay_one_intent(
    intent: TradeIntent,
    candles: list[dict[str, Any]],
    *,
    stop_atr: float,
    target_atr: float,
    hold_minutes: int,
    cost_r: float,
) -> ReplayTrade | None:
    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for candle in candles:
        timestamp = as_utc(candle.get("candle_time"))
        if timestamp and timestamp >= intent.entry_time:
            parsed.append((timestamp, candle))
    parsed.sort(key=lambda item: item[0])
    if not parsed or parsed[0][0] > intent.entry_time + timedelta(minutes=2):
        return None

    entry_time, first = parsed[0]
    entry = _candle_value(first, "open")
    risk_price = max(1e-9, stop_atr * intent.atr)
    if entry <= 0 or risk_price <= 0:
        return None
    if intent.direction > 0:
        stop = entry - risk_price
        target = entry + target_atr * intent.atr
    else:
        stop = entry + risk_price
        target = entry - target_atr * intent.atr

    end_time = entry_time + timedelta(minutes=max(1, hold_minutes))
    last_time = entry_time
    last_close = entry
    exit_reason = "time_exit"
    gross_r: float | None = None

    for timestamp, candle in parsed:
        if timestamp >= end_time:
            break
        bar_open = _candle_value(candle, "open")
        high = _candle_value(candle, "high")
        low = _candle_value(candle, "low")
        close = _candle_value(candle, "close")
        last_time = timestamp
        last_close = close

        if intent.direction > 0:
            if bar_open <= stop:
                gross_r = (bar_open - entry) / risk_price
                exit_reason = "gap_stop"
                break
            if bar_open >= target:
                gross_r = target_atr / stop_atr
                exit_reason = "target"
                break
            hit_stop = low <= stop
            hit_target = high >= target
        else:
            if bar_open >= stop:
                gross_r = (entry - bar_open) / risk_price
                exit_reason = "gap_stop"
                break
            if bar_open <= target:
                gross_r = target_atr / stop_atr
                exit_reason = "target"
                break
            hit_stop = high >= stop
            hit_target = low <= target

        # Without tick data, a single M1 candle that can hit both sides is still
        # ambiguous. Count the stop first so validation cannot flatter a strategy.
        if hit_stop:
            gross_r = -1.0
            exit_reason = "stop"
            break
        if hit_target:
            gross_r = target_atr / stop_atr
            exit_reason = "target"
            break

    if gross_r is None:
        # A time exit is only trustworthy when the M1 window reaches the end of
        # the intended holding period. Missing tail candles remain unresolved.
        if last_time < end_time - timedelta(minutes=2):
            return None
        gross_r = intent.direction * (last_close - entry) / risk_price
        gross_r = max(-2.5, min(target_atr / stop_atr, gross_r))
    return ReplayTrade(
        snapshot_time=intent.snapshot_time,
        entry_time=entry_time,
        exit_time=last_time,
        direction=intent.direction,
        gross_r=gross_r,
        net_r=gross_r - max(0.0, cost_r),
        exit_reason=exit_reason,
        year=intent.year,
        month=intent.month,
        weekday=intent.weekday,
        session=intent.session,
        regime=intent.regime,
    )


def replay_metrics(trades: list[ReplayTrade], unresolved: int = 0) -> ReplayMetrics:
    pnls = [trade.net_r for trade in trades]
    wins = sum(1 for value in pnls if value > 0)
    losses = sum(1 for value in pnls if value < 0)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    pf = gross_profit / gross_loss if gross_loss > 1e-12 else (999.0 if gross_profit > 0 else 0.0)
    equity = peak = drawdown = 0.0
    for value in pnls:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)

    groups: dict[str, dict[str, list[float]]] = {
        "year": defaultdict(list),
        "month": defaultdict(list),
        "weekday": defaultdict(list),
        "session": defaultdict(list),
        "regime": defaultdict(list),
    }
    for trade in trades:
        groups["year"][str(trade.year)].append(trade.net_r)
        groups["month"][f"{trade.year:04d}-{trade.month:02d}"].append(trade.net_r)
        groups["weekday"][str(trade.weekday)].append(trade.net_r)
        groups["session"][trade.session].append(trade.net_r)
        groups["regime"][trade.regime].append(trade.net_r)

    def expectations(group: dict[str, list[float]]) -> dict[str, float]:
        return {key: sum(values) / len(values) for key, values in group.items() if values}

    yearly = expectations(groups["year"])
    stable = sum(1 for value in yearly.values() if value > 0) / len(yearly) if yearly else 0.0
    total = len(trades) + unresolved
    return ReplayMetrics(
        trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=(wins / len(trades) * 100.0) if trades else 0.0,
        net_r=sum(pnls),
        expectancy_r=(sum(pnls) / len(trades)) if trades else 0.0,
        profit_factor=pf,
        max_drawdown_r=drawdown,
        yearly_expectancy=yearly,
        monthly_expectancy=expectations(groups["month"]),
        weekday_expectancy=expectations(groups["weekday"]),
        session_expectancy=expectations(groups["session"]),
        regime_expectancy=expectations(groups["regime"]),
        year_stability=stable,
        unresolved=unresolved,
        resolved_rate=(len(trades) / total) if total else 0.0,
    )


def parameter_profiles(rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stop = max(0.1, number(rules.get("stop_atr"), 1.0))
    target = max(0.1, number(rules.get("target_atr"), 2.0))
    hold = max(5, int(number(rules.get("horizon_minutes"), 60)))
    cooldown = max(5, int(number(rules.get("cooldown_minutes"), hold)))
    base = {**rules, "stop_atr": stop, "target_atr": target, "horizon_minutes": hold, "cooldown_minutes": cooldown}
    return {
        "base": base,
        "stop_minus_15pct": {**base, "stop_atr": round(max(0.1, stop * 0.85), 4)},
        "stop_plus_15pct": {**base, "stop_atr": round(stop * 1.15, 4)},
        "target_minus_15pct": {**base, "target_atr": round(max(0.1, target * 0.85), 4)},
        "target_plus_15pct": {**base, "target_atr": round(target * 1.15, 4)},
        "hold_minus_25pct": {**base, "horizon_minutes": max(5, int(round(hold * 0.75 / 5) * 5))},
        "hold_plus_25pct": {**base, "horizon_minutes": max(5, int(round(hold * 1.25 / 5) * 5))},
        "cooldown_minus_25pct": {**base, "cooldown_minutes": max(5, int(round(cooldown * 0.75 / 5) * 5))},
        "cooldown_plus_25pct": {**base, "cooldown_minutes": max(5, int(round(cooldown * 1.25 / 5) * 5))},
    }


def classify_validation(
    validation: ReplayMetrics,
    locked: ReplayMetrics,
    elevated_locked: ReplayMetrics,
    robust_profile_ratio: float,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    enough = validation.trades >= MIN_VALIDATION_TRADES and locked.trades >= MIN_LOCKED_TRADES
    if not enough:
        reasons.append(f"Needs at least {MIN_VALIDATION_TRADES} validation and {MIN_LOCKED_TRADES} locked M1 trades.")
    if validation.resolved_rate < 0.98 or locked.resolved_rate < 0.98:
        reasons.append("More than 2% of expected entries could not be resolved from M1 data.")
    if validation.expectancy_r <= 0 or locked.expectancy_r <= 0:
        reasons.append("Expectancy did not remain positive in both chronological M1 periods.")
    if elevated_locked.expectancy_r <= 0 or elevated_locked.profit_factor < 1.02:
        reasons.append("The strategy did not survive the elevated execution-cost stress.")
    if robust_profile_ratio < 0.60:
        reasons.append("The edge was too dependent on one exact parameter setting.")
    combined_year_stability = min(validation.year_stability, locked.year_stability)
    if combined_year_stability < 0.60:
        reasons.append("The M1 result was not positive across enough calendar years in both validation periods.")

    base_pass = (
        enough
        and validation.resolved_rate >= 0.98
        and locked.resolved_rate >= 0.98
        and validation.profit_factor >= 1.05
        and locked.profit_factor >= 1.08
        and validation.expectancy_r > 0
        and locked.expectancy_r > 0
        and elevated_locked.expectancy_r > 0
        and robust_profile_ratio >= 0.45
        and combined_year_stability >= 0.50
    )
    ready = (
        base_pass
        and validation.profit_factor >= 1.12
        and locked.profit_factor >= 1.18
        and locked.expectancy_r >= 0.05
        and elevated_locked.profit_factor >= 1.05
        and robust_profile_ratio >= 0.60
        and combined_year_stability >= 0.65
        and locked.max_drawdown_r <= max(25.0, locked.trades * 0.20)
    )
    if ready:
        return "ready_for_mt5_generation", []
    if base_pass:
        return "replay_validated", reasons
    if validation.expectancy_r > 0 and locked.expectancy_r > 0 and not enough:
        return "needs_more_evidence", reasons
    return "rejected", reasons


async def _fetch_m1_days(
    repo: SupabaseRepository,
    symbol: str,
    entry_times: dict[datetime, int],
    progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    # Fetch each required UTC date once instead of issuing one Supabase request
    # per trade. Dense strategies can have tens of thousands of eligible entries;
    # day-block pagination keeps database load and Railway memory bounded.
    groups: dict[str, dict[str, Any]] = {}
    for entry_time, hold in entry_times.items():
        key = entry_time.date().isoformat()
        group = groups.setdefault(key, {"start": datetime.combine(entry_time.date(), datetime.min.time(), tzinfo=timezone.utc), "hold": 0})
        group["hold"] = max(int(group["hold"]), int(hold))

    semaphore = asyncio.Semaphore(3)
    items = list(groups.items())
    output: dict[str, list[dict[str, Any]]] = {}

    async def fetch_day(key: str, group: dict[str, Any]) -> None:
        async with semaphore:
            date_from: datetime = group["start"]
            date_to = date_from + timedelta(days=1, minutes=int(group["hold"]) + 3)
            rows: list[dict[str, Any]] = []
            after: str | None = None
            while True:
                page = await repo.fetch_candles_page(
                    symbol,
                    "1min",
                    after=after,
                    date_from=date_from.isoformat(),
                    date_to=date_to.isoformat(),
                    limit=1000,
                )
                if not page:
                    break
                rows.extend(page)
                if len(page) < 1000:
                    break
                after = str(page[-1]["candle_time"])
            output[key] = rows

    for batch_start in range(0, len(items), 12):
        batch = items[batch_start:batch_start + 12]
        await asyncio.gather(*(fetch_day(key, group) for key, group in batch))
        if progress:
            await progress(min(batch_start + len(batch), len(items)), len(items))
    return output


async def evaluate_high_resolution_candidate(
    repo: SupabaseRepository,
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
    progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    _, validation_rows, locked_rows = split_chronologically(rows)
    profiles = parameter_profiles(rules)
    base_cost = max(0.0, number(rules.get("cost_r"), 0.03))
    cost_profiles = {
        "standard": max(0.03, base_cost),
        "elevated": max(0.06, base_cost * 2.0),
        "severe": max(0.10, base_cost * 3.0),
    }

    intents: dict[tuple[str, str], list[TradeIntent]] = {}
    max_holds: dict[datetime, int] = {}
    for profile_name, profile_rules in profiles.items():
        for segment_name, segment_rows in (("validation", validation_rows), ("locked_test", locked_rows)):
            profile_intents = build_trade_intents(segment_rows, profile_rules)
            intents[(profile_name, segment_name)] = profile_intents
            hold = max(5, int(number(profile_rules.get("horizon_minutes"), 60)))
            for intent in profile_intents:
                max_holds[intent.entry_time] = max(max_holds.get(intent.entry_time, 0), hold)

    day_windows = await _fetch_m1_days(repo, str(candidate.get("symbol") or "XAU/USD"), max_holds, progress)

    def run(profile_name: str, segment_name: str, cost_r: float) -> ReplayMetrics:
        profile_rules = profiles[profile_name]
        stop = max(0.1, number(profile_rules.get("stop_atr"), 1.0))
        target = max(0.1, number(profile_rules.get("target_atr"), 2.0))
        hold = max(5, int(number(profile_rules.get("horizon_minutes"), 60)))
        trades: list[ReplayTrade] = []
        unresolved = 0
        for intent in intents[(profile_name, segment_name)]:
            trade = replay_one_intent(
                intent,
                day_windows.get(intent.entry_time.date().isoformat(), []),
                stop_atr=stop,
                target_atr=target,
                hold_minutes=hold,
                cost_r=cost_r,
            )
            if trade is None:
                unresolved += 1
            else:
                trades.append(trade)
        return replay_metrics(trades, unresolved)

    standard_validation = run("base", "validation", cost_profiles["standard"])
    standard_locked = run("base", "locked_test", cost_profiles["standard"])
    elevated_validation = run("base", "validation", cost_profiles["elevated"])
    elevated_locked = run("base", "locked_test", cost_profiles["elevated"])
    severe_locked = run("base", "locked_test", cost_profiles["severe"])

    profile_results: dict[str, Any] = {}
    robust_passes = 0
    neighbour_names = [name for name in profiles if name != "base"]
    for name in neighbour_names:
        val_metrics = run(name, "validation", cost_profiles["standard"])
        test_metrics = run(name, "locked_test", cost_profiles["standard"])
        passed = val_metrics.expectancy_r > 0 and test_metrics.expectancy_r > 0 and test_metrics.profit_factor > 1.0
        robust_passes += int(passed)
        profile_results[name] = {
            "passed": passed,
            "validation": val_metrics.as_dict(),
            "locked_test": test_metrics.as_dict(),
            "rules": profiles[name],
        }
    robust_ratio = robust_passes / len(neighbour_names) if neighbour_names else 0.0
    result_status, reasons = classify_validation(standard_validation, standard_locked, elevated_locked, robust_ratio)

    research_pf = number(candidate.get("source_profit_factor"))
    research_expectancy = number(candidate.get("source_expectancy_r"))
    rules_hash = hashlib.sha256(canonical(rules).encode()).hexdigest()
    plain_verdict = {
        "ready_for_mt5_generation": "Passed M1 replay, execution-cost stress and parameter-neighbour tests. Its rules have been frozen for MT5 generation.",
        "replay_validated": "Passed the core M1 replay but did not clear every final MT5-readiness threshold.",
        "needs_more_evidence": "Stayed positive in M1 replay, but there are not enough high-resolution trades yet.",
        "rejected": "Failed one or more high-resolution validation safeguards and will not move toward MT5 generation.",
    }[result_status]
    return {
        "result_status": result_status,
        "rows_scanned": len(rows),
        "m1_windows_scanned": len(max_holds),
        "trades_total": standard_locked.trades,
        "profit_factor": round(standard_locked.profit_factor, 8),
        "expectancy_r": round(standard_locked.expectancy_r, 8),
        "max_drawdown_r": round(standard_locked.max_drawdown_r, 8),
        "win_rate": round(standard_locked.win_rate, 8),
        "year_stability": round(standard_locked.year_stability * 100.0, 8),
        "resolved_rate": round(min(standard_validation.resolved_rate, standard_locked.resolved_rate) * 100.0, 8),
        "robust_profile_ratio": round(robust_ratio * 100.0, 8),
        "rules_hash": rules_hash,
        "frozen_rules": rules if result_status == "ready_for_mt5_generation" else {},
        "metrics": {
            "standard_cost": {
                "cost_r": cost_profiles["standard"],
                "validation": standard_validation.as_dict(),
                "locked_test": standard_locked.as_dict(),
            },
            "elevated_cost": {
                "cost_r": cost_profiles["elevated"],
                "validation": elevated_validation.as_dict(),
                "locked_test": elevated_locked.as_dict(),
            },
            "severe_cost": {
                "cost_r": cost_profiles["severe"],
                "locked_test": severe_locked.as_dict(),
            },
            "parameter_neighbourhood": profile_results,
            "research_grade_comparison": {
                "source_profit_factor": research_pf,
                "m1_locked_profit_factor": standard_locked.profit_factor,
                "profit_factor_change": standard_locked.profit_factor - research_pf,
                "source_expectancy_r": research_expectancy,
                "m1_locked_expectancy_r": standard_locked.expectancy_r,
                "expectancy_change": standard_locked.expectancy_r - research_expectancy,
            },
        },
        "evidence": {
            "engine_version": VALIDATION_ENGINE_VERSION,
            "verdict": plain_verdict,
            "reasons": reasons,
            "entry_protocol": "Features are known after the M5 source candle closes. Entry is the first available M1 open at least five minutes after the snapshot timestamp.",
            "same_m1_bar_protocol": "If a single M1 candle can reach both stop and target, the stop is counted first.",
            "execution_costs": cost_profiles,
            "m1_date_blocks_scanned": len(day_windows),
            "parameter_profiles_tested": len(neighbour_names),
            "parameter_profiles_passed": robust_passes,
            "anti_overfitting": [
                "No parameter is selected from the locked period.",
                "The exact evolved rules are tested first, then nearby settings are challenged rather than optimised.",
                "Elevated and severe execution-cost scenarios are reported separately.",
                "Ready status freezes a SHA-256 hash of the exact rules.",
            ],
            "next_action": (
                "Generate an MT5 Expert Advisor from the frozen rules."
                if result_status == "ready_for_mt5_generation"
                else "Keep the strategy in research or reject it; do not deploy it to MT5."
            ),
        },
    }


class HighResolutionValidationService:
    def __init__(
        self,
        settings: Settings,
        repo: SupabaseRepository,
        shared_row_provider: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.shared_row_provider = shared_row_provider
        self.worker_id = f"validation-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def request_wake(self) -> None:
        self._wake.set()

    async def loop(self) -> None:
        if not self.settings.high_resolution_validation_enabled:
            logger.info("High-resolution validation is disabled")
            return
        logger.info("High-resolution validation worker %s started", self.worker_id)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self.settings.high_resolution_validation_startup_delay_seconds)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self.repo.upsert_validation_state(
                    "XAU/USD", SNAPSHOT_INTERVAL, status="active", worker_id=self.worker_id,
                    heartbeat_at=utc_now().isoformat(), started_at=utc_now().isoformat(), last_error=None,
                )
                await self.repo.reset_stale_validation_jobs()
                await self._ensure_queue()
                job = await self.repo.claim_next_validation_job(self.worker_id)
                if job:
                    await self._execute(job)
                else:
                    await self._sleep(self.settings.high_resolution_validation_idle_seconds)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("High-resolution validation cycle failed")
                await self.repo.upsert_validation_state(
                    "XAU/USD", SNAPSHOT_INTERVAL, status="error", heartbeat_at=utc_now().isoformat(),
                    last_error=str(exc)[:4000], last_result="Validation worker recovered from an error and will retry automatically.",
                )
                await self._sleep(max(60.0, self.settings.high_resolution_validation_idle_seconds))
            await self._sleep(self.settings.high_resolution_validation_job_delay_seconds)

    async def _sleep(self, seconds: float) -> None:
        self._wake.clear()
        stop_task = asyncio.create_task(self._stop.wait())
        wake_task = asyncio.create_task(self._wake.wait())
        _, pending = await asyncio.wait({stop_task, wake_task}, timeout=max(1.0, seconds), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _ensure_queue(self) -> None:
        await self.repo.refresh_validation_state("XAU/USD", SNAPSHOT_INTERVAL)
        state = await self.repo.get_validation_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        if int(number(state.get("queue_count"))) >= self.settings.high_resolution_validation_queue_floor:
            return
        seeds = await self.repo.list_validation_seed_candidates("XAU/USD", SNAPSHOT_INTERVAL, limit=MAX_SEEDS)
        specs: list[dict[str, Any]] = []
        for seed in seeds:
            source_kind = str(seed.get("source_kind") or "evolution")
            source_id = str(seed.get("id"))
            rules = dict(seed.get("rules") or {})
            specs.append({
                "validation_key": validation_key(source_kind, source_id, rules),
                "symbol": seed.get("symbol") or "XAU/USD",
                "snapshot_interval": seed.get("snapshot_interval") or SNAPSHOT_INTERVAL,
                "source_kind": source_kind,
                "source_strategy_candidate_id": source_id if source_kind == "strategy" else None,
                "source_evolution_candidate_id": source_id if source_kind == "evolution" else None,
                "source_lineage_id": seed.get("lineage_id"),
                "name": seed.get("name") or "Strategy for M1 validation",
                "family": seed.get("family") or "unknown",
                "rules": rules,
                "source_result_status": seed.get("result_status"),
                "source_profit_factor": seed.get("profit_factor"),
                "source_expectancy_r": seed.get("expectancy_r"),
                "source_metrics": seed.get("metrics") or {},
                "priority": 96 if seed.get("result_status") == "elite" else 90 if seed.get("result_status") == "champion" else 80,
                "status": "queued",
            })
        if specs:
            await self.repo.upsert_validation_jobs(specs)
            await self.repo.upsert_validation_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="active",
                last_generation_at=utc_now().isoformat(),
                last_result=f"Queued {len(specs)} surviving strategies for automatic M1 validation.",
            )
        else:
            await self.repo.upsert_validation_state(
                "XAU/USD", SNAPSHOT_INTERVAL,
                last_result="Waiting for a Champion, Elite or validated strategy that has not already received M1 validation.",
            )
        await self.repo.refresh_validation_state("XAU/USD", SNAPSHOT_INTERVAL)

    async def _load_rows(self) -> list[dict[str, Any]]:
        if self.shared_row_provider is not None:
            return await self.shared_row_provider()
        rows: list[dict[str, Any]] = []
        after: str | None = None
        while not self._stop.is_set():
            page = await self.repo.fetch_learning_snapshots_page("XAU/USD", SNAPSHOT_INTERVAL, after=after, complete_only=True, limit=1000)
            if not page:
                break
            rows.extend(page)
            if len(page) < 1000:
                break
            after = str(page[-1]["candle_time"])
        return rows

    async def _execute(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        name = str(job.get("name") or "High-resolution strategy validation")
        await self.repo.upsert_validation_state(
            "XAU/USD", SNAPSHOT_INTERVAL, status="loading", worker_id=self.worker_id,
            heartbeat_at=utc_now().isoformat(), current_job_id=job_id, current_job_name=name,
            last_job_started_at=utc_now().isoformat(), last_error=None,
        )

        async def progress(done: int, total: int) -> None:
            await self.repo.update_validation_job(job_id, heartbeat_at=utc_now().isoformat(), progress_done=done, progress_total=total)
            await self.repo.upsert_validation_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="replaying", heartbeat_at=utc_now().isoformat(),
                current_job_id=job_id, current_job_name=f"{name} · M1 date blocks {done:,}/{total:,}",
            )

        try:
            rows = await self._load_rows()
            if len(rows) < 5000:
                raise RuntimeError("Not enough complete learning snapshots for M1 validation")
            result = await evaluate_high_resolution_candidate(self.repo, job, rows, progress)
            await self.repo.complete_validation_job(job_id, result)
            if result["result_status"] == "ready_for_mt5_generation":
                await self.repo.freeze_validated_strategy(job, result)
            await self.repo.upsert_validation_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="active", heartbeat_at=utc_now().isoformat(),
                current_job_id=None, current_job_name=None, last_job_finished_at=utc_now().isoformat(),
                last_result=str(result.get("evidence", {}).get("verdict")), last_error=None,
            )
            await self.repo.log_event(
                "success" if result["result_status"] in {"replay_validated", "ready_for_mt5_generation"} else "info",
                "validation-lab", f"M1 validation {result['result_status']}", {"strategy": name, "result": result},
            )
            await self.repo.refresh_validation_state("XAU/USD", SNAPSHOT_INTERVAL)
        except Exception as exc:
            await self.repo.fail_validation_job(job_id, str(exc))
            await self.repo.upsert_validation_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="error", heartbeat_at=utc_now().isoformat(),
                current_job_id=None, current_job_name=None, last_job_finished_at=utc_now().isoformat(),
                last_error=str(exc)[:4000], last_result=f"M1 validation failed and will not be promoted: {name}",
            )
            raise
