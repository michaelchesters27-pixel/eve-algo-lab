from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from app.services.autonomy import (
    alignment_band,
    compression_band,
    confidence_score,
    mean,
    number,
    outcome_direction,
    outcome_excursion,
    outcome_for,
    split_chronologically,
    streak_band,
    trend_band,
    year_stability,
)
from app.services.learning import SNAPSHOT_INTERVAL, as_utc
from app.services.supabase_repo import SupabaseRepository
from app.settings import Settings

logger = logging.getLogger(__name__)

RESEARCH_ENGINE_VERSION = "continuous-history-v1"
DEFAULT_BATCH_SIZE = 250
MIN_GROUP_TEST = 60
MIN_GROUP_VALIDATION = 60


@dataclass(frozen=True)
class ConditionOption:
    key: str
    label: str
    field: str
    value: Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _condition_options() -> list[ConditionOption]:
    options: list[ConditionOption] = []
    weekday_names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday"}
    month_names = {
        1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
        7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
    }
    for value, label in weekday_names.items():
        options.append(ConditionOption(f"weekday:{value}", label, "weekday", value))
    for value, label in month_names.items():
        options.append(ConditionOption(f"month:{value}", label, "month", value))
    for value in range(1, 5):
        options.append(ConditionOption(f"quarter:{value}", f"quarter {value}", "quarter", value))
    for value in range(1, 6):
        options.append(ConditionOption(f"week_of_month:{value}", f"week {value} of the month", "week_of_month", value))
    for value in range(24):
        options.append(ConditionOption(f"hour_utc:{value}", f"{value:02d}:00 UTC", "hour_utc", value))
    for value, label in (
        ("asia", "Asian session"),
        ("london", "London session"),
        ("new_york", "New York session"),
        ("off_session", "off-session hours"),
    ):
        options.append(ConditionOption(f"session:{value}", label, "session", value))
    for value, label in (
        ("compression", "compression regime"),
        ("trend_up", "uptrend regime"),
        ("trend_down", "downtrend regime"),
        ("high_volatility", "high-volatility regime"),
        ("range", "range regime"),
    ):
        options.append(ConditionOption(f"regime:{value}", label, "regime", value))
    for value, label in ((1, "bullish M5 candle"), (-1, "bearish M5 candle"), (0, "neutral M5 candle")):
        options.append(ConditionOption(f"direction:{value}", label, "direction", value))
    for value, label in (
        ("strong_up", "strong bullish multi-timeframe alignment"),
        ("up", "bullish multi-timeframe alignment"),
        ("neutral", "neutral multi-timeframe alignment"),
        ("down", "bearish multi-timeframe alignment"),
        ("strong_down", "strong bearish multi-timeframe alignment"),
    ):
        options.append(ConditionOption(f"alignment_band:{value}", label, "alignment_band", value))
    for value, label in (
        ("compressed", "below-normal compression"),
        ("normal", "normal compression"),
        ("expanded", "expanded volatility"),
    ):
        options.append(ConditionOption(f"compression_band:{value}", label, "compression_band", value))
    for value, label in (("up", "positive short trend"), ("flat", "flat short trend"), ("down", "negative short trend")):
        options.append(ConditionOption(f"trend_band:{value}", label, "trend_band", value))
    for value, label in (("up3", "three-or-more bullish candles"), ("down3", "three-or-more bearish candles"), ("short", "short candle streak")):
        options.append(ConditionOption(f"streak_band:{value}", label, "streak_band", value))
    return options


CONDITION_OPTIONS = _condition_options()
OUTCOME_OPTIONS: tuple[tuple[str, str], ...] = (
    ("excursion", "total price excursion"),
    ("absolute_return", "absolute closing move"),
    ("continuation", "continuation rate"),
    ("same_direction", "same-direction follow-through"),
    ("alignment_follow", "multi-timeframe alignment follow-through"),
    ("up_probability", "upward outcome rate"),
)
HORIZONS = (15, 30, 60, 240)


def generate_research_specs(generation: int, count: int = DEFAULT_BATCH_SIZE) -> list[dict[str, Any]]:
    """Generate a deterministic, effectively unbounded batch of unique hypotheses.

    The generation number is persisted in Supabase. A Railway restart therefore
    resumes at the next generation instead of repeating the same questions.
    """
    rng = random.Random(1700003 + generation * 7919)
    specs: dict[str, dict[str, Any]] = {}
    attempts = 0
    while len(specs) < count and attempts < count * 40:
        attempts += 1
        # Early generations favour simple, interpretable questions. Later
        # generations increasingly combine two and three independent contexts.
        if generation <= 1:
            condition_count = 1 if rng.random() < 0.55 else 2
        else:
            roll = rng.random()
            condition_count = 1 if roll < 0.15 else 2 if roll < 0.72 else 3
        chosen: list[ConditionOption] = []
        used_fields: set[str] = set()
        for option in rng.sample(CONDITION_OPTIONS, k=min(len(CONDITION_OPTIONS), condition_count * 6)):
            if option.field in used_fields:
                continue
            # Hour and session are highly dependent. Keeping only one avoids
            # generating thousands of tautological questions.
            if {option.field, *used_fields} >= {"hour_utc", "session"}:
                continue
            chosen.append(option)
            used_fields.add(option.field)
            if len(chosen) == condition_count:
                break
        if len(chosen) != condition_count:
            continue
        metric, metric_label = rng.choice(OUTCOME_OPTIONS)
        horizon = rng.choice(HORIZONS)
        definition = {
            "engine_version": RESEARCH_ENGINE_VERSION,
            "conditions": [{"field": item.field, "value": item.value} for item in sorted(chosen, key=lambda x: x.key)],
            "metric": metric,
            "horizon_minutes": horizon,
        }
        digest = hashlib.sha256(_canonical(definition).encode("utf-8")).hexdigest()
        job_key = f"history-{digest[:28]}"
        context = " and ".join(item.label for item in chosen)
        question = f"Does {context} materially change the {horizon}-minute {metric_label}?"
        specs[job_key] = {
            "job_key": job_key,
            "symbol": "XAU/USD",
            "snapshot_interval": SNAPSHOT_INTERVAL,
            "generation": generation,
            "priority": max(20, 82 - condition_count * 8 + (4 if horizon in (60, 240) else 0)),
            "category": "continuous_historical_research",
            "question": question,
            "rationale": "EVE generated this question automatically from stored multi-timeframe market context. It is tested chronologically and must survive unseen data and year-stability checks.",
            "test_definition": definition,
            "status": "queued",
        }
    return list(specs.values())


def _field_value(row: dict[str, Any], field: str) -> Any:
    if field == "alignment_band":
        return alignment_band(row.get("alignment_score"))
    if field == "compression_band":
        return compression_band(row.get("compression_ratio"))
    if field == "trend_band":
        return trend_band(row.get("trend_12_atr"))
    if field == "streak_band":
        return streak_band(row.get("streak"))
    return row.get(field)


def predicate_from_definition(definition: dict[str, Any]) -> Callable[[dict[str, Any]], bool]:
    conditions = list(definition.get("conditions") or [])

    def predicate(row: dict[str, Any]) -> bool:
        for condition in conditions:
            field = str(condition.get("field") or "")
            expected = condition.get("value")
            actual = _field_value(row, field)
            if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                if number(actual) != number(expected):
                    return False
            elif str(actual) != str(expected):
                return False
        return True

    return predicate


def metric_value(row: dict[str, Any], metric: str, horizon: int) -> float | None:
    outcome = outcome_for(row, horizon)
    if outcome is None:
        return None
    if metric == "excursion":
        return outcome_excursion(row, horizon)
    if metric == "absolute_return":
        return abs(number(outcome.get("close_return_pct")))
    if metric == "continuation":
        value = outcome.get("continuation")
        return None if value is None else 1.0 if value is True else 0.0
    if metric == "same_direction":
        actual = outcome_direction(row, horizon)
        direction = int(number(row.get("direction")))
        if actual is None or direction == 0:
            return None
        return 1.0 if actual == ("up" if direction > 0 else "down") else 0.0
    if metric == "alignment_follow":
        actual = outcome_direction(row, horizon)
        aligned = int(number(row.get("alignment_score")))
        if actual is None or aligned == 0:
            return None
        return 1.0 if actual == ("up" if aligned > 0 else "down") else 0.0
    if metric == "up_probability":
        actual = outcome_direction(row, horizon)
        return None if actual is None else 1.0 if actual == "up" else 0.0
    return None


def _effect(group: Iterable[float], baseline: Iterable[float], rate_metric: bool) -> float:
    group_values = list(group)
    baseline_values = list(baseline)
    if not group_values or not baseline_values:
        return 0.0
    group_mean = mean(group_values)
    baseline_mean = mean(baseline_values)
    if rate_metric:
        return (group_mean - baseline_mean) * 100.0
    if abs(baseline_mean) < 1e-12:
        return 0.0
    return ((group_mean / baseline_mean) - 1.0) * 100.0


def evaluate_research_spec(spec: dict[str, Any], rows: list[dict[str, Any]], tests_considered: int = 1000) -> dict[str, Any]:
    definition = dict(spec.get("test_definition") or {})
    metric = str(definition.get("metric") or "excursion")
    horizon = int(number(definition.get("horizon_minutes"), 60))
    predicate = predicate_from_definition(definition)
    train_rows, validation_rows, test_rows = split_chronologically(rows)
    rate_metric = metric in {"continuation", "same_direction", "alignment_follow", "up_probability"}

    def values(source: list[dict[str, Any]], conditional: bool) -> list[float]:
        result: list[float] = []
        for row in source:
            if conditional and not predicate(row):
                continue
            value = metric_value(row, metric, horizon)
            if value is not None:
                result.append(float(value))
        return result

    validation_group = values(validation_rows, True)
    validation_baseline = values(validation_rows, False)
    test_group = values(test_rows, True)
    test_baseline = values(test_rows, False)
    validation_effect = _effect(validation_group, validation_baseline, rate_metric)
    test_effect = _effect(test_group, test_baseline, rate_metric)
    direction_consistent = validation_effect == 0 or test_effect == 0 or (validation_effect > 0) == (test_effect > 0)
    stability = year_stability(rows, predicate, lambda row: metric_value(row, metric, horizon))
    sample_count = len(test_group)
    confidence = confidence_score(sample_count, test_effect, stability, tests_considered)
    minimum_effect = 3.0 if rate_metric else 6.0
    strong_effect = 6.0 if rate_metric else 10.0

    enough_data = len(validation_group) >= MIN_GROUP_VALIDATION and sample_count >= MIN_GROUP_TEST
    if (
        enough_data
        and direction_consistent
        and abs(test_effect) >= strong_effect
        and stability >= 0.72
        and confidence >= 82
    ):
        result_status = "validated"
    elif (
        enough_data
        and direction_consistent
        and abs(test_effect) >= minimum_effect
        and stability >= 0.55
        and confidence >= 62
    ):
        result_status = "promising"
    else:
        result_status = "rejected"

    context = " and ".join(
        f"{item.get('field')}={item.get('value')}" for item in definition.get("conditions") or []
    )
    unit = "percentage points" if rate_metric else "% versus baseline"
    summary = (
        f"{context or 'The selected context'} produced a locked-test effect of {test_effect:+.2f} {unit} "
        f"across {sample_count:,} observations. Validation effect was {validation_effect:+.2f}; "
        f"year stability was {stability * 100:.0f}%."
    )
    return {
        "result_status": result_status,
        "sample_count": sample_count,
        "effect_size": round(test_effect, 8),
        "confidence_score": round(confidence, 4),
        "stability_score": round(stability * 100.0, 4),
        "rows_scanned": len(rows),
        "summary": summary,
        "evidence": {
            "engine_version": RESEARCH_ENGINE_VERSION,
            "chronological_split": {"train": len(train_rows), "validation": len(validation_rows), "test": len(test_rows)},
            "validation_group_sample": len(validation_group),
            "test_group_sample": sample_count,
            "validation_baseline_sample": len(validation_baseline),
            "test_baseline_sample": len(test_baseline),
            "validation_effect": round(validation_effect, 8),
            "locked_test_effect": round(test_effect, 8),
            "direction_consistent": direction_consistent,
            "year_stability_fraction": round(stability, 8),
            "multiple_testing_penalty_applied": True,
            "tests_considered": tests_considered,
            "metric": metric,
            "horizon_minutes": horizon,
            "conditions": definition.get("conditions") or [],
        },
    }


class ContinuousHistoricalResearchService:
    """Dedicated 24/7 worker that mines stored history independently of markets."""

    def __init__(self, settings: Settings, repo: SupabaseRepository) -> None:
        self.settings = settings
        self.repo = repo
        self.worker_id = f"history-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
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
        if not self.settings.historical_research_enabled:
            logger.info("Continuous historical research is disabled")
            return
        await self.repo.reset_stale_historical_research_jobs()
        await self.repo.upsert_historical_research_state(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            status="active",
            worker_id=self.worker_id,
            heartbeat_at=utc_now().isoformat(),
            started_at=utc_now().isoformat(),
            last_error=None,
        )
        logger.info("Continuous historical research worker %s started", self.worker_id)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self.settings.historical_research_startup_delay_seconds)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self.repo.upsert_historical_research_state(
                    "XAU/USD",
                    SNAPSHOT_INTERVAL,
                    status="active",
                    worker_id=self.worker_id,
                    heartbeat_at=utc_now().isoformat(),
                    last_error=None,
                )
                await self._ensure_queue()
                job = await self.repo.claim_next_historical_research_job(self.worker_id)
                if job:
                    await self._execute_job(job)
                else:
                    await self._sleep(self.settings.historical_research_idle_seconds)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Continuous historical research cycle failed")
                await self.repo.upsert_historical_research_state(
                    "XAU/USD",
                    SNAPSHOT_INTERVAL,
                    status="error",
                    heartbeat_at=utc_now().isoformat(),
                    last_error=str(exc)[:4000],
                    last_result="Historical research recovered from an error and will retry automatically.",
                )
                await self._sleep(max(30.0, self.settings.historical_research_idle_seconds))
            await self._sleep(self.settings.historical_research_job_delay_seconds)

    async def _sleep(self, seconds: float) -> None:
        self._wake.clear()
        stop_task = asyncio.create_task(self._stop.wait())
        wake_task = asyncio.create_task(self._wake.wait())
        done, pending = await asyncio.wait(
            {stop_task, wake_task}, timeout=max(1.0, seconds), return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            await task

    async def _ensure_queue(self) -> None:
        await self.repo.refresh_historical_research_state("XAU/USD", SNAPSHOT_INTERVAL)
        state = await self.repo.get_historical_research_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        queue_count = int(number(state.get("queue_count")))
        if queue_count >= self.settings.historical_research_queue_floor:
            return
        generation = int(number(state.get("generator_generation"))) + 1
        specs = generate_research_specs(generation, self.settings.historical_research_seed_batch)
        await self.repo.upsert_historical_research_jobs(specs)
        await self.repo.upsert_historical_research_state(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            generator_generation=generation,
            last_generation_at=utc_now().isoformat(),
            last_result=f"Generated research batch {generation} with {len(specs)} new historical questions.",
        )
        await self.repo.refresh_historical_research_state("XAU/USD", SNAPSHOT_INTERVAL)

    async def _load_rows(self) -> list[dict[str, Any]]:
        learning_state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        latest_snapshot = as_utc(learning_state.get("last_snapshot_time"))
        cache_fresh = (
            self._rows_cache
            and latest_snapshot == self._cache_snapshot_time
            and self._cache_loaded_at is not None
            and utc_now() < self._cache_loaded_at + timedelta(minutes=self.settings.historical_research_cache_minutes)
        )
        if cache_fresh:
            return self._rows_cache
        await self.repo.upsert_historical_research_state(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            status="loading",
            heartbeat_at=utc_now().isoformat(),
            current_question="Refreshing the in-memory historical research dataset",
        )
        rows: list[dict[str, Any]] = []
        after: str | None = None
        page_number = 0
        while not self._stop.is_set():
            page = await self.repo.fetch_learning_snapshots_page(
                "XAU/USD", SNAPSHOT_INTERVAL, after=after, complete_only=True, limit=1000
            )
            if not page:
                break
            rows.extend(page)
            page_number += 1
            if page_number % 10 == 0:
                await self.repo.upsert_historical_research_state(
                    "XAU/USD",
                    SNAPSHOT_INTERVAL,
                    status="loading",
                    heartbeat_at=utc_now().isoformat(),
                    current_question=f"Refreshing historical memory: {len(rows):,} complete snapshots loaded",
                )
            if len(page) < 1000:
                break
            after = str(page[-1]["candle_time"])
        self._rows_cache = rows
        self._cache_snapshot_time = latest_snapshot
        self._cache_loaded_at = utc_now()
        return rows

    async def _execute_job(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        question = str(job.get("question") or "Historical research question")
        await self.repo.upsert_historical_research_state(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            status="researching",
            worker_id=self.worker_id,
            heartbeat_at=utc_now().isoformat(),
            current_job_id=job_id,
            current_question=question,
            last_job_started_at=utc_now().isoformat(),
            last_error=None,
        )
        try:
            rows = await self._load_rows()
            if len(rows) < 5_000:
                raise RuntimeError("The learning foundation does not yet contain enough complete historical snapshots")
            await self.repo.upsert_historical_research_state(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                status="researching",
                heartbeat_at=utc_now().isoformat(),
                current_job_id=job_id,
                current_question=question,
            )
            result = await asyncio.to_thread(
                evaluate_research_spec,
                job,
                rows,
                max(1000, int(number(job.get("generation"), 1)) * self.settings.historical_research_seed_batch),
            )
            await self.repo.complete_historical_research_job(job_id, result)
            question_status = {
                "validated": "answered",
                "promising": "promising",
                "rejected": "rejected",
            }[result["result_status"]]
            if result["result_status"] in {"promising", "validated"}:
                await self.repo.upsert_research_questions([{
                    "question_key": job["job_key"],
                    "symbol": "XAU/USD",
                    "category": job.get("category") or "continuous_historical_research",
                    "question": question,
                    "rationale": job.get("rationale"),
                    "priority": int(number(job.get("priority"), 50)),
                    "status": question_status,
                    "generated_by": RESEARCH_ENGINE_VERSION,
                    "test_definition": job.get("test_definition") or {},
                    "sample_count": result["sample_count"],
                    "effect_size": result["effect_size"],
                    "confidence_score": result["confidence_score"],
                    "evidence": result["evidence"],
                }])
                await self.repo.upsert_discoveries([{
                    "discovery_key": f"discovery-{job['job_key']}",
                    "symbol": "XAU/USD",
                    "title": question,
                    "summary": result["summary"],
                    "category": "continuous_historical_research",
                    "status": result["result_status"],
                    "sample_count": result["sample_count"],
                    "effect_size": result["effect_size"],
                    "confidence_score": result["confidence_score"],
                    "stability_score": result["stability_score"],
                    "evidence": result["evidence"],
                    "first_observed_at": rows[0].get("candle_time"),
                    "last_observed_at": rows[-1].get("candle_time"),
                }])
                await self.repo.log_event(
                    "success",
                    "historical-research",
                    f"Historical research finding {result['result_status']}",
                    {"question": question, "result": result},
                )
            await self.repo.upsert_historical_research_state(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                status="active",
                heartbeat_at=utc_now().isoformat(),
                current_job_id=None,
                current_question=None,
                last_job_finished_at=utc_now().isoformat(),
                last_result=result["summary"],
                last_error=None,
            )
            await self.repo.refresh_historical_research_state("XAU/USD", SNAPSHOT_INTERVAL)
        except Exception as exc:
            await self.repo.fail_historical_research_job(job_id, str(exc))
            await self.repo.upsert_historical_research_state(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                status="error",
                heartbeat_at=utc_now().isoformat(),
                current_job_id=None,
                current_question=None,
                last_job_finished_at=utc_now().isoformat(),
                last_error=str(exc)[:4000],
                last_result=f"Research job failed and was recorded: {question}",
            )
            raise
