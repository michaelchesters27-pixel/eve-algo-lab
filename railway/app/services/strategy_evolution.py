from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.services.autonomy import number, split_chronologically
from app.services.learning import SNAPSHOT_INTERVAL, as_utc
from app.services.strategy_lab import SegmentMetrics, evaluate_segment
from app.services.supabase_repo import SupabaseRepository
from app.settings import Settings

logger = logging.getLogger(__name__)

EVOLUTION_ENGINE_VERSION = "strategy-evolution-v2.2"
MAX_ACTIVE_LINEAGES = 20
MIN_VALIDATION_TRADES = 35
MIN_LOCKED_TRADES = 50


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def conditions_compatible(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> bool:
    values: dict[str, Any] = {}
    for condition in [*first, *second]:
        field = str(condition.get("field") or "")
        if not field:
            continue
        value = condition.get("value")
        if field in values and values[field] != value:
            return False
        values[field] = value
    return True


def merge_conditions(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not conditions_compatible(first, second):
        return None
    merged: dict[str, dict[str, Any]] = {}
    for condition in [*first, *second]:
        field = str(condition.get("field") or "")
        if not field:
            continue
        merged[f"{field}:{canonical(condition.get('value'))}"] = {"field": field, "value": condition.get("value")}
    return sorted(merged.values(), key=lambda item: (str(item.get("field")), canonical(item.get("value"))))


def validation_fitness(metrics: SegmentMetrics) -> float:
    """A validation-only score used to select the next development champion.

    Locked-test results are deliberately excluded. The locked period is used only
    as a safety/readiness grade so repeated evolution cannot optimise directly on it.
    """
    if metrics.trades <= 0:
        return -999.0
    pf_component = clamp(metrics.profit_factor - 1.0, -1.0, 2.0) * 28.0
    expectancy_component = clamp(metrics.expectancy_r, -1.0, 1.0) * 100.0
    stability_component = metrics.stability * 18.0
    sample_component = min(metrics.trades, 200) / 200.0 * 8.0
    drawdown_rate = metrics.max_drawdown_r / max(1, metrics.trades)
    drawdown_penalty = min(drawdown_rate, 1.0) * 55.0
    return pf_component + expectancy_component + stability_component + sample_component - drawdown_penalty


def strategy_seed_to_lineage(seed: dict[str, Any]) -> dict[str, Any]:
    candidate_key = str(seed.get("candidate_key") or seed.get("id"))
    digest = hashlib.sha256(f"lineage:{candidate_key}".encode()).hexdigest()
    metrics = dict(seed.get("metrics") or {})
    return {
        "lineage_key": f"lineage-{digest[:28]}",
        "symbol": seed.get("symbol") or "XAU/USD",
        "snapshot_interval": seed.get("snapshot_interval") or SNAPSHOT_INTERVAL,
        "family": seed.get("family") or "unknown",
        "name": seed.get("name") or "Strategy lineage",
        "root_strategy_candidate_id": seed.get("id"),
        "status": "active",
        "current_generation": 0,
        "champion_kind": "strategy",
        "champion_id": seed.get("id"),
        "champion_name": seed.get("name") or "Strategy seed",
        "champion_rules": dict(seed.get("rules") or {}),
        "champion_metrics": metrics,
        "champion_result_status": seed.get("result_status") or "promising",
        "champion_profit_factor": number(seed.get("profit_factor")),
        "champion_expectancy_r": number(seed.get("expectancy_r")),
        "champion_max_drawdown_r": number(seed.get("max_drawdown_r")),
        "champion_trades": int(number(seed.get("trades_total"))),
        "champion_validation_score": validation_fitness_from_metrics_payload(metrics.get("validation") or {}),
        "last_result": "Seeded from a Strategy Lab candidate that survived chronological testing.",
    }


def metrics_from_payload(payload: dict[str, Any]) -> SegmentMetrics:
    yearly = {str(key): number(value) for key, value in dict(payload.get("yearly_expectancy") or {}).items()}
    return SegmentMetrics(
        trades=int(number(payload.get("trades"))),
        wins=int(number(payload.get("wins"))),
        losses=int(number(payload.get("losses"))),
        win_rate=number(payload.get("win_rate")),
        net_r=number(payload.get("net_r")),
        expectancy_r=number(payload.get("expectancy_r")),
        profit_factor=number(payload.get("profit_factor")),
        max_drawdown_r=number(payload.get("max_drawdown_r")),
        yearly_expectancy=yearly,
        stability=number(payload.get("stability")),
    )


def validation_fitness_from_metrics_payload(payload: dict[str, Any]) -> float:
    return validation_fitness(metrics_from_payload(payload)) if payload else 0.0


def _nearest_grid_values(current: float, grid: tuple[float, ...], generation: int, count: int = 2) -> list[float]:
    ordered = sorted((value for value in grid if abs(value - current) > 1e-9), key=lambda value: (abs(value - current), value))
    if not ordered:
        return []
    start = ((max(1, generation) - 1) * count) % len(ordered)
    return [ordered[(start + offset) % len(ordered)] for offset in range(min(count, len(ordered)))]


def _child_spec(
    lineage: dict[str, Any], generation: int, mutation_type: str, rules: dict[str, Any], changes: dict[str, Any],
    secondary_parent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parent_id = lineage.get("champion_id")
    identity = {
        "lineage": lineage.get("lineage_key"),
        "parent_kind": lineage.get("champion_kind"),
        "parent_id": parent_id,
        "secondary_parent": (secondary_parent or {}).get("champion_id"),
        "rules": rules,
    }
    digest = hashlib.sha256(canonical(identity).encode()).hexdigest()
    label_map = {
        "stop": "Stop mutation",
        "target": "Target mutation",
        "cooldown": "Cooldown mutation",
        "direction": "Direction mutation",
        "condition_mode": "Filter-mode mutation",
        "combination": "Discovery combination",
    }
    change_text = ", ".join(f"{key}: {value}" for key, value in changes.items())
    return {
        "child_key": f"evolution-{digest[:28]}",
        "lineage_id": lineage.get("id"),
        "symbol": lineage.get("symbol") or "XAU/USD",
        "snapshot_interval": lineage.get("snapshot_interval") or SNAPSHOT_INTERVAL,
        "generation": generation,
        "priority": 76 if mutation_type == "combination" else 82,
        "mutation_type": mutation_type,
        "parent_kind": lineage.get("champion_kind") or "strategy",
        "parent_candidate_id": parent_id if lineage.get("champion_kind") == "strategy" else None,
        "parent_evolution_candidate_id": parent_id if lineage.get("champion_kind") == "evolution" else None,
        "secondary_parent_candidate_id": (
            secondary_parent.get("champion_id") if secondary_parent and secondary_parent.get("champion_kind") == "strategy" else None
        ),
        "secondary_parent_evolution_id": (
            secondary_parent.get("champion_id") if secondary_parent and secondary_parent.get("champion_kind") == "evolution" else None
        ),
        "name": f"{lineage.get('name') or 'Strategy'} · generation {generation} · {label_map.get(mutation_type, mutation_type)}",
        "hypothesis": f"Test whether this controlled mutation improves the current development champion. {change_text}",
        "parent_rules": dict(lineage.get("champion_rules") or {}),
        "rules": rules,
        "changes": changes,
        "selection_config": {
            "engine_version": EVOLUTION_ENGINE_VERSION,
            "selection_period": "validation only",
            "locked_test_role": "readiness grade and catastrophic-loss veto only",
            "minimum_validation_trades": MIN_VALIDATION_TRADES,
            "minimum_locked_trades": MIN_LOCKED_TRADES,
        },
        "status": "queued",
    }


def generate_evolution_specs(lineages: list[dict[str, Any]], generation: int) -> list[dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    stop_grid = (0.50, 0.65, 0.75, 0.90, 1.00, 1.15, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50)
    target_grid = (0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00, 3.50, 4.00, 4.50, 5.00)
    cooldown_grid = (5, 10, 15, 30, 45, 60, 90, 120, 180, 240)

    active = [item for item in lineages if item.get("status") == "active" and item.get("champion_rules")]
    active = active[:MAX_ACTIVE_LINEAGES]
    for index, lineage in enumerate(active):
        parent_rules = dict(lineage.get("champion_rules") or {})
        current_stop = number(parent_rules.get("stop_atr"), 1.0)
        current_target = number(parent_rules.get("target_atr"), 2.0)
        current_cooldown = int(number(parent_rules.get("cooldown_minutes"), parent_rules.get("horizon_minutes") or 60))

        for stop in _nearest_grid_values(current_stop, stop_grid, generation, 2):
            rules = {**parent_rules, "stop_atr": stop, "engine_version": EVOLUTION_ENGINE_VERSION}
            child = _child_spec(lineage, generation, "stop", rules, {"stop_atr": f"{current_stop:.2f} → {stop:.2f}"})
            specs[child["child_key"]] = child

        for target in _nearest_grid_values(current_target, target_grid, generation, 2):
            rules = {**parent_rules, "target_atr": target, "engine_version": EVOLUTION_ENGINE_VERSION}
            child = _child_spec(lineage, generation, "target", rules, {"target_atr": f"{current_target:.2f} → {target:.2f}"})
            specs[child["child_key"]] = child

        cooldown_options = _nearest_grid_values(float(current_cooldown), tuple(float(v) for v in cooldown_grid), generation, 1)
        for cooldown_value in cooldown_options:
            cooldown = int(cooldown_value)
            rules = {**parent_rules, "cooldown_minutes": cooldown, "engine_version": EVOLUTION_ENGINE_VERSION}
            child = _child_spec(lineage, generation, "cooldown", rules, {"cooldown_minutes": f"{current_cooldown} → {cooldown}"})
            specs[child["child_key"]] = child

        direction = str(parent_rules.get("direction_rule") or "current_direction")
        alternatives = {
            "current_direction": "alignment_direction",
            "alignment_direction": "current_direction",
            "fixed_long": "alignment_direction",
            "fixed_short": "alignment_direction",
        }
        alternative = alternatives.get(direction)
        if alternative:
            rules = {**parent_rules, "direction_rule": alternative, "engine_version": EVOLUTION_ENGINE_VERSION}
            child = _child_spec(lineage, generation, "direction", rules, {"direction_rule": f"{direction} → {alternative}"})
            specs[child["child_key"]] = child

        condition_mode = str(parent_rules.get("condition_mode") or "include")
        flipped_mode = "exclude" if condition_mode == "include" else "include"
        rules = {**parent_rules, "condition_mode": flipped_mode, "engine_version": EVOLUTION_ENGINE_VERSION}
        child = _child_spec(lineage, generation, "condition_mode", rules, {"condition_mode": f"{condition_mode} → {flipped_mode}"})
        specs[child["child_key"]] = child

        if len(active) > 1:
            partner = active[(index + max(1, generation)) % len(active)]
            if partner.get("id") != lineage.get("id"):
                partner_rules = dict(partner.get("champion_rules") or {})
                combined = merge_conditions(
                    list(parent_rules.get("source_conditions") or []),
                    list(partner_rules.get("source_conditions") or []),
                )
                if combined and len(combined) > len(list(parent_rules.get("source_conditions") or [])):
                    rules = {
                        **parent_rules,
                        "source_conditions": combined,
                        "condition_mode": "include",
                        "engine_version": EVOLUTION_ENGINE_VERSION,
                    }
                    child = _child_spec(
                        lineage, generation, "combination", rules,
                        {"combined_with": partner.get("champion_name") or partner.get("name"), "condition_count": len(combined)},
                        secondary_parent=partner,
                    )
                    specs[child["child_key"]] = child

    return list(specs.values())


@dataclass
class EvolutionEvaluation:
    result: dict[str, Any]
    promote_for_next_generation: bool


def _delta(child: SegmentMetrics, parent: SegmentMetrics) -> dict[str, float]:
    return {
        "profit_factor": child.profit_factor - parent.profit_factor,
        "expectancy_r": child.expectancy_r - parent.expectancy_r,
        "max_drawdown_r": child.max_drawdown_r - parent.max_drawdown_r,
        "trades": float(child.trades - parent.trades),
        "stability": child.stability - parent.stability,
        "fitness": validation_fitness(child) - validation_fitness(parent),
    }


def evaluate_evolution_candidate(candidate: dict[str, Any], rows: list[dict[str, Any]]) -> EvolutionEvaluation:
    child_rules = dict(candidate.get("rules") or {})
    parent_rules = dict(candidate.get("parent_rules") or {})
    train, validation, locked_test = split_chronologically(rows)

    child_train = evaluate_segment(train, child_rules, True)
    child_validation = evaluate_segment(validation, child_rules, True)
    child_test = evaluate_segment(locked_test, child_rules, True)
    parent_validation = evaluate_segment(validation, parent_rules, True)
    parent_test = evaluate_segment(locked_test, parent_rules, True)
    baseline_test = evaluate_segment(locked_test, child_rules, False)

    validation_delta = _delta(child_validation, parent_validation)
    locked_delta = _delta(child_test, parent_test)
    child_validation_score = validation_fitness(child_validation)
    parent_validation_score = validation_fitness(parent_validation)

    enough_validation = child_validation.trades >= MIN_VALIDATION_TRADES
    positive_validation = child_validation.expectancy_r > 0 and child_validation.profit_factor >= 1.03
    stable_validation = child_validation.stability >= 0.45
    meaningful_improvement = (
        validation_delta["fitness"] >= 1.5
        and (
            validation_delta["expectancy_r"] >= 0.005
            or validation_delta["profit_factor"] >= 0.03
            or (
                validation_delta["max_drawdown_r"] <= -0.50
                and child_validation.expectancy_r >= parent_validation.expectancy_r - 0.005
            )
        )
    )
    selection_passed = enough_validation and positive_validation and stable_validation and meaningful_improvement

    catastrophic_locked_failure = (
        child_test.trades >= 20
        and (child_test.profit_factor < 0.85 or child_test.expectancy_r < -0.05)
    )
    promote_for_next_generation = selection_passed and not catastrophic_locked_failure

    locked_passed = (
        child_test.trades >= MIN_LOCKED_TRADES
        and child_test.profit_factor >= 1.05
        and child_test.expectancy_r > 0
        and child_test.stability >= 0.45
        and child_test.profit_factor >= parent_test.profit_factor - 0.10
        and child_test.expectancy_r >= parent_test.expectancy_r - 0.03
    )
    elite = (
        locked_passed
        and child_test.trades >= 100
        and child_test.profit_factor >= 1.50
        and child_test.expectancy_r >= 0.12
        and child_test.stability >= 0.75
        and child_validation.profit_factor >= 1.20
    )

    if not selection_passed or catastrophic_locked_failure:
        result_status = "rejected"
    elif elite:
        result_status = "elite"
    elif locked_passed:
        result_status = "champion"
    else:
        result_status = "development"

    if not selection_passed:
        verdict = "Rejected: the mutation did not improve the parent on validation-only selection evidence."
    elif catastrophic_locked_failure:
        verdict = "Rejected by the safety veto: validation improved, but the sealed locked period showed a material failure."
    elif elite:
        verdict = "Elite development champion: validation improved and the sealed locked period remained exceptionally strong."
    elif locked_passed:
        verdict = "New champion: validation improved and the sealed locked period remained positive and stable."
    else:
        verdict = "Development champion: validation improved, but locked-test evidence is not strong enough for readiness status."

    summary = (
        f"{candidate.get('name')} changed validation fitness by {validation_delta['fitness']:+.2f}, "
        f"validation PF by {validation_delta['profit_factor']:+.2f} and validation expectancy by "
        f"{validation_delta['expectancy_r']:+.3f}R. Locked-test PF was {child_test.profit_factor:.2f} "
        f"across {child_test.trades:,} trades."
    )
    result = {
        "result_status": result_status,
        "selection_passed": selection_passed,
        "promoted_for_next_generation": promote_for_next_generation,
        "locked_test_passed": locked_passed,
        "rows_scanned": len(rows),
        "trades_total": child_test.trades,
        "profit_factor": round(child_test.profit_factor, 8),
        "expectancy_r": round(child_test.expectancy_r, 8),
        "max_drawdown_r": round(child_test.max_drawdown_r, 8),
        "win_rate": round(child_test.win_rate, 8),
        "stability_score": round(child_test.stability * 100.0, 8),
        "validation_score": round(child_validation_score, 8),
        "parent_validation_score": round(parent_validation_score, 8),
        "validation_improvement": round(validation_delta["fitness"], 8),
        "metrics": {
            "child_train": child_train.as_dict(),
            "child_validation": child_validation.as_dict(),
            "child_locked_test": child_test.as_dict(),
            "parent_validation": parent_validation.as_dict(),
            "parent_locked_test": parent_test.as_dict(),
            "unfiltered_locked_test": baseline_test.as_dict(),
        },
        "parent_comparison": {
            "validation_delta": {key: round(value, 8) for key, value in validation_delta.items()},
            "locked_test_delta": {key: round(value, 8) for key, value in locked_delta.items()},
            "selection_used_locked_test": False,
            "catastrophic_locked_failure": catastrophic_locked_failure,
        },
        "evidence": {
            "engine_version": EVOLUTION_ENGINE_VERSION,
            "summary": summary,
            "verdict": verdict,
            "changes": dict(candidate.get("changes") or {}),
            "chronological_split": {
                "train_rows": len(train),
                "validation_rows": len(validation),
                "locked_test_rows": len(locked_test),
            },
            "selection_protocol": [
                "Mutation choice and development-champion selection use training and validation data only.",
                "The locked period is not used to choose parameter values; it supplies a readiness grade and catastrophic-loss veto.",
                "Every child is compared with its direct parent on exactly the same chronological rows.",
                "Research-grade M5 outcome replay remains subject to M1/tick replay and forward testing before MT5 deployment.",
            ],
        },
    }
    return EvolutionEvaluation(result=result, promote_for_next_generation=promote_for_next_generation)


class StrategyEvolutionService:
    def __init__(
        self, settings: Settings, repo: SupabaseRepository,
        shared_row_provider: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.shared_row_provider = shared_row_provider
        self.worker_id = f"evolution-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
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
        if not self.settings.strategy_evolution_enabled:
            logger.info("Strategy Evolution Engine is disabled")
            return
        logger.info("Strategy Evolution worker %s started", self.worker_id)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self.settings.strategy_evolution_startup_delay_seconds)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self.repo.upsert_strategy_evolution_state(
                    "XAU/USD", SNAPSHOT_INTERVAL, status="active", worker_id=self.worker_id,
                    heartbeat_at=utc_now().isoformat(), started_at=utc_now().isoformat(), last_error=None,
                )
                await self._ensure_lineages()
                await self._ensure_queue()
                child = await self.repo.claim_next_evolution_candidate(self.worker_id)
                if child:
                    await self._execute_child(child)
                else:
                    await self._sleep(self.settings.strategy_evolution_idle_seconds)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Strategy Evolution cycle failed")
                await self.repo.upsert_strategy_evolution_state(
                    "XAU/USD", SNAPSHOT_INTERVAL, status="error", heartbeat_at=utc_now().isoformat(),
                    last_error=str(exc)[:4000], last_result="Evolution worker recovered from an error and will retry automatically.",
                )
                await self._sleep(max(30.0, self.settings.strategy_evolution_idle_seconds))
            await self._sleep(self.settings.strategy_evolution_job_delay_seconds)

    async def _sleep(self, seconds: float) -> None:
        self._wake.clear()
        stop_task = asyncio.create_task(self._stop.wait())
        wake_task = asyncio.create_task(self._wake.wait())
        _, pending = await asyncio.wait(
            {stop_task, wake_task}, timeout=max(1.0, seconds), return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _ensure_lineages(self) -> None:
        seeds = await self.repo.list_evolution_seed_strategies("XAU/USD", SNAPSHOT_INTERVAL, limit=MAX_ACTIVE_LINEAGES)
        lineages = [strategy_seed_to_lineage(seed) for seed in seeds]
        if lineages:
            await self.repo.upsert_strategy_lineages(lineages)

    async def _ensure_queue(self) -> None:
        await self.repo.refresh_strategy_evolution_state("XAU/USD", SNAPSHOT_INTERVAL)
        state = await self.repo.get_strategy_evolution_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        if int(number(state.get("queue_count"))) >= self.settings.strategy_evolution_queue_floor:
            return
        last_generation = as_utc(state.get("last_generation_at"))
        if last_generation and utc_now() < last_generation + timedelta(minutes=20):
            return
        lineages = await self.repo.list_strategy_lineages("XAU/USD", SNAPSHOT_INTERVAL, limit=MAX_ACTIVE_LINEAGES)
        generation = int(number(state.get("generator_generation"))) + 1
        specs = generate_evolution_specs(lineages, generation)
        if specs:
            await self.repo.upsert_evolution_candidates(specs)
            await self.repo.upsert_strategy_evolution_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="generating", generator_generation=generation,
                last_generation_at=utc_now().isoformat(),
                last_result=f"Generated evolution batch {generation} across {len(lineages)} active strategy lineages.",
            )
        else:
            await self.repo.upsert_strategy_evolution_state(
                "XAU/USD", SNAPSHOT_INTERVAL,
                last_result="Waiting for validated or promising Strategy Lab candidates to seed evolution lineages.",
            )
        await self.repo.refresh_strategy_evolution_state("XAU/USD", SNAPSHOT_INTERVAL)

    async def _load_rows(self) -> list[dict[str, Any]]:
        if self.shared_row_provider is not None:
            return await self.shared_row_provider()
        learning_state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        latest = as_utc(learning_state.get("last_snapshot_time"))
        fresh = (
            self._rows_cache
            and latest == self._cache_snapshot_time
            and self._cache_loaded_at
            and utc_now() < self._cache_loaded_at + timedelta(minutes=self.settings.strategy_evolution_cache_minutes)
        )
        if fresh:
            return self._rows_cache
        rows: list[dict[str, Any]] = []
        after: str | None = None
        while not self._stop.is_set():
            page = await self.repo.fetch_learning_snapshots_page(
                "XAU/USD", SNAPSHOT_INTERVAL, after=after, complete_only=True, limit=1000
            )
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

    async def _execute_child(self, child: dict[str, Any]) -> None:
        child_id = str(child["id"])
        name = str(child.get("name") or "Evolution child")
        await self.repo.upsert_strategy_evolution_state(
            "XAU/USD", SNAPSHOT_INTERVAL, status="testing", worker_id=self.worker_id,
            heartbeat_at=utc_now().isoformat(), current_child_id=child_id,
            current_child_name=name, last_child_started_at=utc_now().isoformat(), last_error=None,
        )
        try:
            rows = await self._load_rows()
            if len(rows) < 5000:
                raise RuntimeError("Not enough complete learning snapshots for Strategy Evolution")
            evaluation = await asyncio.to_thread(evaluate_evolution_candidate, child, rows)
            result = evaluation.result
            await self.repo.complete_evolution_candidate(child_id, result)
            await self.repo.record_evolution_lineage_result(
                lineage_id=str(child["lineage_id"]), candidate_id=child_id,
                promoted=evaluation.promote_for_next_generation, generation=int(number(child.get("generation"))),
                result_status=str(result["result_status"]), name=name, rules=dict(child.get("rules") or {}),
                metrics=dict(result.get("metrics") or {}), profit_factor=number(result.get("profit_factor")),
                expectancy_r=number(result.get("expectancy_r")), max_drawdown_r=number(result.get("max_drawdown_r")),
                trades=int(number(result.get("trades_total"))), validation_score=number(result.get("validation_score")),
                summary=str(result.get("evidence", {}).get("summary") or "Evolution candidate completed"),
            )
            await self.repo.upsert_strategy_evolution_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="active", heartbeat_at=utc_now().isoformat(),
                current_child_id=None, current_child_name=None, last_child_finished_at=utc_now().isoformat(),
                last_result=str(result.get("evidence", {}).get("verdict") or result.get("evidence", {}).get("summary")),
                last_error=None,
            )
            await self.repo.log_event(
                "success" if result["result_status"] in {"champion", "elite"} else "info",
                "strategy-evolution", f"Evolution child {result['result_status']}",
                {"candidate": name, "result": result},
            )
            await self.repo.refresh_strategy_evolution_state("XAU/USD", SNAPSHOT_INTERVAL)
        except Exception as exc:
            await self.repo.fail_evolution_candidate(child_id, str(exc))
            await self.repo.upsert_strategy_evolution_state(
                "XAU/USD", SNAPSHOT_INTERVAL, status="error", heartbeat_at=utc_now().isoformat(),
                current_child_id=None, current_child_name=None, last_child_finished_at=utc_now().isoformat(),
                last_error=str(exc)[:4000], last_result=f"Evolution child failed and was recorded: {name}",
            )
            raise
