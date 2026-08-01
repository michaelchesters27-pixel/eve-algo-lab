from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.services.autonomy import number, outcome_for, split_chronologically
from app.services.historical_research import predicate_from_definition
from app.services.learning import SNAPSHOT_INTERVAL, as_utc
from app.services.supabase_repo import SupabaseRepository
from app.settings import Settings

logger = logging.getLogger(__name__)

STRATEGY_ENGINE_VERSION = "strategy-idea-factory-v2"
MIN_TEST_TRADES = 50
MIN_VALIDATED_TRADES = 80


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sign(value: Any) -> int:
    value = number(value)
    return 1 if value > 0 else -1 if value < 0 else 0


def infer_families(source: dict[str, Any]) -> list[tuple[str, str, str]]:
    definition = dict(source.get("test_definition") or {})
    metric = str(definition.get("metric") or "excursion")
    effect = number(source.get("effect_size"))
    positive = effect >= 0
    if metric in {"continuation", "same_direction"}:
        return [("momentum_continuation", "current_direction", "include" if positive else "exclude")]
    if metric == "alignment_follow":
        return [("alignment_continuation", "alignment_direction", "include" if positive else "exclude")]
    if metric == "up_probability":
        return [("directional_bias", "fixed_long" if positive else "fixed_short", "include")]
    if positive:
        return [
            ("momentum_continuation", "current_direction", "include"),
            ("alignment_continuation", "alignment_direction", "include"),
        ]
    return [("momentum_exclusion_filter", "current_direction", "exclude")]


def generate_candidate_specs(source_jobs: list[dict[str, Any]], generation: int) -> list[dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    risk_grid = (
        (0.75, 1.00), (0.75, 1.50), (1.00, 1.50), (1.00, 2.00),
        (1.25, 1.50), (1.25, 2.50), (1.50, 2.00), (1.50, 3.00),
    )
    start = ((max(1, generation) - 1) * 2) % len(risk_grid)
    risk_variants = (risk_grid[start], risk_grid[(start + 1) % len(risk_grid)])
    for source in source_jobs:
        if source.get("result_status") not in {"validated", "promising"}:
            continue
        definition = dict(source.get("test_definition") or {})
        horizon = int(number(definition.get("horizon_minutes"), 60))
        source_conditions = list(definition.get("conditions") or [])
        for family, direction_rule, condition_mode in infer_families(source):
            for stop_atr, target_atr in risk_variants:
                rules = {
                    "engine_version": STRATEGY_ENGINE_VERSION,
                    "source_conditions": source_conditions,
                    "condition_mode": condition_mode,
                    "direction_rule": direction_rule,
                    "horizon_minutes": horizon,
                    "stop_atr": stop_atr,
                    "target_atr": target_atr,
                    "cooldown_minutes": horizon,
                    "cost_r": 0.03,
                    "research_grade_only": True,
                }
                digest = hashlib.sha256(canonical({"source": source.get("job_key"), "family": family, "rules": rules}).encode()).hexdigest()
                key = f"strategy-{digest[:28]}"
                mode_label = "use" if condition_mode == "include" else "avoid"
                rr = target_atr / stop_atr
                name = f"{family.replace('_', ' ').title()} · {mode_label} research condition · {rr:.1f}R target"
                specs[key] = {
                    "candidate_key": key,
                    "symbol": source.get("symbol") or "XAU/USD",
                    "snapshot_interval": source.get("snapshot_interval") or SNAPSHOT_INTERVAL,
                    "generation": generation,
                    "priority": 88 if source.get("result_status") == "validated" else 72,
                    "source_research_job_id": source.get("id"),
                    "source_job_key": source.get("job_key"),
                    "source_question": source.get("question"),
                    "name": name,
                    "family": family,
                    "hypothesis": (
                        f"Convert the {source.get('result_status')} research finding into a bot rule: "
                        f"{mode_label} the tested context, choose direction with {direction_rule.replace('_', ' ')}, "
                        f"and evaluate a {stop_atr:.2f} ATR stop against a {target_atr:.2f} ATR target."
                    ),
                    "rules": rules,
                    "backtest_config": {
                        "chronological_split": [0.70, 0.15, 0.15],
                        "non_overlapping_trades": True,
                        "conservative_same_bar_resolution": True,
                        "metric_unit": "R",
                    },
                    "status": "queued",
                }
    return list(specs.values())


def candidate_direction(row: dict[str, Any], rule: str) -> int:
    if rule == "current_direction":
        return sign(row.get("direction"))
    if rule == "alignment_direction":
        return sign(row.get("alignment_score"))
    if rule == "fixed_long":
        return 1
    if rule == "fixed_short":
        return -1
    return 0


def trade_r(row: dict[str, Any], direction: int, horizon: int, stop_atr: float, target_atr: float, cost_r: float) -> float | None:
    outcome = outcome_for(row, horizon)
    if not outcome or direction == 0:
        return None
    if direction > 0:
        favourable = number(outcome.get("max_up_atr"))
        adverse = number(outcome.get("max_down_atr"))
    else:
        favourable = number(outcome.get("max_down_atr"))
        adverse = number(outcome.get("max_up_atr"))

    # OHLC snapshots cannot always prove which extreme happened first. When both
    # stop and target were available, count the stop first. This is deliberately
    # conservative and prevents the Strategy Lab from flattering candidates.
    if adverse >= stop_atr:
        gross = -1.0
    elif favourable >= target_atr:
        gross = target_atr / stop_atr
    else:
        close = number(row.get("close"))
        atr = number(row.get("atr_14"))
        close_return = number(outcome.get("close_return_pct")) / 100.0
        close_move_atr = ((close * close_return) / atr) if close and atr else 0.0
        gross = max(-1.0, min(target_atr / stop_atr, direction * close_move_atr / stop_atr))
    return gross - cost_r


@dataclass
class SegmentMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    yearly_expectancy: dict[str, float]
    stability: float

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
            "stability": round(self.stability, 6),
        }


def evaluate_segment(rows: list[dict[str, Any]], rules: dict[str, Any], apply_source_filter: bool) -> SegmentMetrics:
    definition = {"conditions": rules.get("source_conditions") or []}
    predicate = predicate_from_definition(definition)
    condition_mode = str(rules.get("condition_mode") or "include")
    horizon = int(number(rules.get("horizon_minutes"), 60))
    cooldown = max(5, int(number(rules.get("cooldown_minutes"), horizon)))
    stop_atr = max(0.1, number(rules.get("stop_atr"), 1.0))
    target_atr = max(0.1, number(rules.get("target_atr"), 2.0))
    cost_r = max(0.0, number(rules.get("cost_r"), 0.03))
    direction_rule = str(rules.get("direction_rule") or "current_direction")

    pnls: list[float] = []
    yearly: dict[str, list[float]] = defaultdict(list)
    next_allowed: datetime | None = None
    for row in rows:
        candle_time = as_utc(row.get("candle_time"))
        if not candle_time:
            continue
        if next_allowed and candle_time < next_allowed:
            continue
        matches = predicate(row)
        if apply_source_filter:
            eligible = matches if condition_mode == "include" else not matches
            if not eligible:
                continue
        direction = candidate_direction(row, direction_rule)
        pnl = trade_r(row, direction, horizon, stop_atr, target_atr, cost_r)
        if pnl is None:
            continue
        pnls.append(pnl)
        yearly[str(candle_time.year)].append(pnl)
        next_allowed = candle_time + timedelta(minutes=cooldown)

    wins = sum(1 for value in pnls if value > 0)
    losses = sum(1 for value in pnls if value < 0)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-12 else (999.0 if gross_profit > 0 else 0.0)
    equity = peak = drawdown = 0.0
    for value in pnls:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    year_expectancy = {year: sum(values) / len(values) for year, values in yearly.items() if values}
    stable_years = sum(1 for value in year_expectancy.values() if value > 0)
    stability = stable_years / len(year_expectancy) if year_expectancy else 0.0
    return SegmentMetrics(
        trades=len(pnls), wins=wins, losses=losses,
        win_rate=(wins / len(pnls) * 100.0) if pnls else 0.0,
        net_r=sum(pnls), expectancy_r=(sum(pnls) / len(pnls)) if pnls else 0.0,
        profit_factor=profit_factor, max_drawdown_r=drawdown,
        yearly_expectancy=year_expectancy, stability=stability,
    )


def evaluate_candidate(candidate: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    train, validation, test = split_chronologically(rows)
    train_metrics = evaluate_segment(train, rules, True)
    validation_metrics = evaluate_segment(validation, rules, True)
    test_metrics = evaluate_segment(test, rules, True)
    baseline_validation = evaluate_segment(validation, rules, False)
    baseline_test = evaluate_segment(test, rules, False)

    pf_improvement = test_metrics.profit_factor - baseline_test.profit_factor
    expectancy_improvement = test_metrics.expectancy_r - baseline_test.expectancy_r
    improvement_score = pf_improvement * 50.0 + expectancy_improvement * 100.0
    enough = test_metrics.trades >= MIN_TEST_TRADES and validation_metrics.trades >= 35
    robust = validation_metrics.expectancy_r > 0 and test_metrics.expectancy_r > 0
    better = pf_improvement >= 0.05 or expectancy_improvement >= 0.02

    if (
        enough and robust and better and test_metrics.trades >= 120
        and validation_metrics.profit_factor >= 1.20 and test_metrics.profit_factor >= 1.40
        and test_metrics.expectancy_r >= 0.12 and test_metrics.stability >= 0.75
    ):
        result_status = "elite"
    elif (
        enough and robust and better and test_metrics.trades >= MIN_VALIDATED_TRADES
        and validation_metrics.profit_factor >= 1.08 and test_metrics.profit_factor >= 1.15
        and test_metrics.expectancy_r >= 0.04 and test_metrics.stability >= 0.60
    ):
        result_status = "validated"
    elif (
        enough and robust and test_metrics.profit_factor >= 1.03
        and test_metrics.expectancy_r > 0 and test_metrics.stability >= 0.45
    ):
        result_status = "promising"
    else:
        result_status = "rejected"

    summary = (
        f"{candidate.get('name')} produced {test_metrics.trades:,} locked-test trades, "
        f"profit factor {test_metrics.profit_factor:.2f}, expectancy {test_metrics.expectancy_r:+.3f}R "
        f"and maximum drawdown {test_metrics.max_drawdown_r:.2f}R. "
        f"The comparable unfiltered baseline profit factor was {baseline_test.profit_factor:.2f}."
    )
    return {
        "result_status": result_status,
        "rows_scanned": len(rows),
        "trades_total": test_metrics.trades,
        "profit_factor": round(test_metrics.profit_factor, 8),
        "expectancy_r": round(test_metrics.expectancy_r, 8),
        "max_drawdown_r": round(test_metrics.max_drawdown_r, 8),
        "win_rate": round(test_metrics.win_rate, 8),
        "stability_score": round(test_metrics.stability * 100.0, 8),
        "baseline_profit_factor": round(baseline_test.profit_factor, 8),
        "improvement_score": round(improvement_score, 8),
        "metrics": {
            "train": train_metrics.as_dict(),
            "validation": validation_metrics.as_dict(),
            "locked_test": test_metrics.as_dict(),
            "baseline_validation": baseline_validation.as_dict(),
            "baseline_locked_test": baseline_test.as_dict(),
        },
        "evidence": {
            "engine_version": STRATEGY_ENGINE_VERSION,
            "summary": summary,
            "chronological_split": {"train_rows": len(train), "validation_rows": len(validation), "test_rows": len(test)},
            "source_question": candidate.get("source_question"),
            "rules": rules,
            "caveats": [
                "Research-grade M5 outcome replay, not tick-level execution.",
                "When stop and target were both reachable inside one horizon, the stop was counted first.",
                "Spread and slippage are represented by a fixed R cost, not broker tick data.",
                "A validated candidate still requires forward testing before MT5 implementation.",
            ],
        },
    }


class StrategyLabService:
    def __init__(
        self, settings: Settings, repo: SupabaseRepository,
        shared_row_provider: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.shared_row_provider = shared_row_provider
        self.worker_id = f"strategy-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._rows_cache: list[dict[str, Any]] = []
        self._cache_snapshot_time: datetime | None = None
        self._cache_loaded_at: datetime | None = None

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def request_wake(self) -> None:
        self._wake.set()

    async def loop(self) -> None:
        if not self.settings.strategy_lab_enabled:
            logger.info("Strategy Lab is disabled")
            return
        logger.info("Strategy Lab worker %s started", self.worker_id)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self.settings.strategy_lab_startup_delay_seconds)
            return
        except asyncio.TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                await self.repo.upsert_strategy_lab_state(
                    "XAU/USD", SNAPSHOT_INTERVAL, status="active", worker_id=self.worker_id,
                    heartbeat_at=utc_now().isoformat(), started_at=utc_now().isoformat(), last_error=None,
                )
                await self._ensure_queue()
                candidate = await self.repo.claim_next_strategy_candidate(self.worker_id)
                if candidate:
                    await self._execute_candidate(candidate)
                else:
                    await self._sleep(self.settings.strategy_lab_idle_seconds)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Strategy Lab cycle failed")
                await self.repo.upsert_strategy_lab_state(
                    "XAU/USD", SNAPSHOT_INTERVAL, status="error", heartbeat_at=utc_now().isoformat(),
                    last_error=str(exc)[:4000], last_result="Strategy Lab recovered from an error and will retry automatically.",
                )
                await self._sleep(max(30.0, self.settings.strategy_lab_idle_seconds))
            await self._sleep(self.settings.strategy_lab_job_delay_seconds)

    async def _sleep(self, seconds: float) -> None:
        self._wake.clear()
        stop_task = asyncio.create_task(self._stop.wait())
        wake_task = asyncio.create_task(self._wake.wait())
        _, pending = await asyncio.wait({stop_task, wake_task}, timeout=max(1.0, seconds), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _ensure_queue(self) -> None:
        await self.repo.refresh_strategy_lab_state("XAU/USD", SNAPSHOT_INTERVAL)
        state = await self.repo.get_strategy_lab_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        if int(number(state.get("queue_count"))) >= self.settings.strategy_lab_queue_floor:
            return
        last_generation = as_utc(state.get("last_generation_at"))
        if last_generation and utc_now() < last_generation + timedelta(minutes=30):
            return
        sources = await self.repo.list_strategy_source_research("XAU/USD", SNAPSHOT_INTERVAL, limit=250)
        generation = int(number(state.get("generator_generation"))) + 1
        specs = generate_candidate_specs(sources, generation)
        if specs:
            await self.repo.upsert_strategy_candidates(specs)
            await self.repo.upsert_strategy_lab_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="generating", generator_generation=generation,
                last_generation_at=utc_now().isoformat(),
                last_result=f"Generated strategy batch {generation} from {len(sources)} validated or promising research findings.",
            )
        else:
            await self.repo.upsert_strategy_lab_state(
                "XAU/USD", SNAPSHOT_INTERVAL,
                last_result="Waiting for new validated or promising research findings to convert into strategy candidates.",
            )
        await self.repo.refresh_strategy_lab_state("XAU/USD", SNAPSHOT_INTERVAL)

    async def _load_rows(self) -> list[dict[str, Any]]:
        # Reuse the continuous-research cache when available. This prevents two
        # 159k-row Python object graphs from occupying Railway memory at once.
        if self.shared_row_provider is not None:
            return await self.shared_row_provider()
        learning_state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        latest = as_utc(learning_state.get("last_snapshot_time"))
        fresh = self._rows_cache and latest == self._cache_snapshot_time and self._cache_loaded_at and utc_now() < self._cache_loaded_at + timedelta(minutes=self.settings.strategy_lab_cache_minutes)
        if fresh:
            return self._rows_cache
        await self.repo.upsert_strategy_lab_state(
            "XAU/USD", SNAPSHOT_INTERVAL, status="loading", heartbeat_at=utc_now().isoformat(),
            current_candidate_name="Refreshing the strategy research dataset",
        )
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
        self._rows_cache = rows
        self._cache_snapshot_time = latest
        self._cache_loaded_at = utc_now()
        return rows

    async def _execute_candidate(self, candidate: dict[str, Any]) -> None:
        candidate_id = str(candidate["id"])
        name = str(candidate.get("name") or "Strategy candidate")
        await self.repo.upsert_strategy_lab_state(
            "XAU/USD", SNAPSHOT_INTERVAL, status="testing", worker_id=self.worker_id,
            heartbeat_at=utc_now().isoformat(), current_candidate_id=candidate_id,
            current_candidate_name=name, last_candidate_started_at=utc_now().isoformat(), last_error=None,
        )
        try:
            rows = await self._load_rows()
            if len(rows) < 5000:
                raise RuntimeError("Not enough complete learning snapshots for Strategy Lab")
            result = await asyncio.to_thread(evaluate_candidate, candidate, rows)
            await self.repo.complete_strategy_candidate(candidate_id, result)
            await self.repo.upsert_strategy_lab_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="active", heartbeat_at=utc_now().isoformat(),
                current_candidate_id=None, current_candidate_name=None,
                last_candidate_finished_at=utc_now().isoformat(),
                last_result=result["evidence"]["summary"], last_error=None,
            )
            await self.repo.log_event(
                "success" if result["result_status"] in {"validated", "elite"} else "info",
                "strategy-lab", f"Strategy candidate {result['result_status']}",
                {"candidate": name, "result": result},
            )
            await self.repo.refresh_strategy_lab_state("XAU/USD", SNAPSHOT_INTERVAL)
        except Exception as exc:
            await self.repo.fail_strategy_candidate(candidate_id, str(exc))
            await self.repo.upsert_strategy_lab_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="error", heartbeat_at=utc_now().isoformat(),
                current_candidate_id=None, current_candidate_name=None, last_candidate_finished_at=utc_now().isoformat(),
                last_error=str(exc)[:4000], last_result=f"Strategy candidate failed and was recorded: {name}",
            )
            raise
