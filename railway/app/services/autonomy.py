from __future__ import annotations

import asyncio
import json
import logging
import math
import socket
import statistics
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from app.services.learning import SNAPSHOT_INTERVAL, as_utc, number, safe_pct
from app.services.supabase_repo import SupabaseRepository
from app.settings import Settings

logger = logging.getLogger(__name__)

MODEL_HORIZONS = (15, 60, 240)
MODEL_FEATURE_VERSION = "eve-context-features-v1"
MODEL_MIN_BUCKET = 50
MODEL_ALPHA = 2.0
RESEARCH_MIN_SAMPLE = 150
RESEARCH_TOP_FINDINGS = 12


@dataclass(frozen=True)
class Evaluation:
    rows: int
    accuracy: float
    brier: float
    log_loss: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "accuracy": round(self.accuracy, 8),
            "brier": round(self.brier, 8),
            "log_loss": round(self.log_loss, 8),
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def sign(value: float, tolerance: float = 1e-12) -> int:
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def outcome_for(row: dict[str, Any], horizon: int) -> dict[str, Any] | None:
    outcomes = row.get("outcomes") or {}
    result = outcomes.get(str(horizon)) if isinstance(outcomes, dict) else None
    return result if isinstance(result, dict) else None


def outcome_direction(row: dict[str, Any], horizon: int) -> str | None:
    outcome = outcome_for(row, horizon)
    value = str((outcome or {}).get("direction") or "")
    return value if value in {"up", "down", "flat"} else None


def outcome_excursion(row: dict[str, Any], horizon: int) -> float | None:
    outcome = outcome_for(row, horizon)
    if not outcome:
        return None
    up = outcome.get("max_up_atr")
    down = outcome.get("max_down_atr")
    if up is None or down is None:
        return None
    return max(number(up), number(down))


def split_chronologically(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda item: str(item.get("candle_time") or ""))
    if len(ordered) < 30:
        return ordered, [], []
    train_end = max(1, int(len(ordered) * 0.70))
    validation_end = max(train_end + 1, int(len(ordered) * 0.85))
    validation_end = min(validation_end, len(ordered) - 1)
    return ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:]


def alignment_band(value: Any) -> str:
    score = int(number(value))
    if score >= 3:
        return "strong_up"
    if score >= 1:
        return "up"
    if score <= -3:
        return "strong_down"
    if score <= -1:
        return "down"
    return "neutral"


def compression_band(value: Any) -> str:
    ratio = number(value, 1.0)
    if ratio < 0.72:
        return "compressed"
    if ratio > 1.35:
        return "expanded"
    return "normal"


def trend_band(value: Any) -> str:
    trend = number(value)
    if trend >= 0.18:
        return "up"
    if trend <= -0.18:
        return "down"
    return "flat"


def streak_band(value: Any) -> str:
    streak = int(number(value))
    if streak >= 3:
        return "up3"
    if streak <= -3:
        return "down3"
    return "short"


def model_feature_levels(row: dict[str, Any]) -> list[tuple[str, ...]]:
    regime = str(row.get("regime") or "unknown")
    session = str(row.get("session") or "unknown")
    direction = str(int(number(row.get("direction"))))
    align = alignment_band(row.get("alignment_score"))
    compression = compression_band(row.get("compression_ratio"))
    trend = trend_band(row.get("trend_12_atr"))
    weekday = str(int(number(row.get("weekday"))))
    month = str(int(number(row.get("month"))))
    return [
        ("full", regime, session, direction, align, compression, trend, weekday, month),
        ("context", regime, session, direction, align, compression, trend),
        ("regime_session", regime, session, direction, align),
        ("regime", regime, direction),
        ("direction", direction),
        ("global",),
    ]


def _empty_class_counts() -> dict[str, int]:
    return {"up": 0, "down": 0, "flat": 0}


def train_context_model(rows: list[dict[str, Any]], horizons: Sequence[int] = MODEL_HORIZONS) -> dict[str, Any]:
    counts: dict[str, dict[str, dict[str, int]]] = {str(horizon): {} for horizon in horizons}
    trained_rows: dict[str, int] = {str(horizon): 0 for horizon in horizons}

    for row in rows:
        levels = model_feature_levels(row)
        for horizon in horizons:
            actual = outcome_direction(row, horizon)
            if actual is None:
                continue
            trained_rows[str(horizon)] += 1
            for key in levels:
                encoded = json.dumps(key, separators=(",", ":"))
                bucket = counts[str(horizon)].setdefault(encoded, _empty_class_counts())
                bucket[actual] += 1

    pruned: dict[str, dict[str, dict[str, int]]] = {}
    for horizon, horizon_counts in counts.items():
        pruned[horizon] = {
            key: bucket
            for key, bucket in horizon_counts.items()
            if key == '["global"]' or sum(bucket.values()) >= 20
        }

    return {
        "model_type": "hierarchical_context_frequency",
        "feature_version": MODEL_FEATURE_VERSION,
        "alpha": MODEL_ALPHA,
        "minimum_bucket": MODEL_MIN_BUCKET,
        "horizons": list(horizons),
        "trained_rows": trained_rows,
        "counts": pruned,
    }


def predict_context_model(model: dict[str, Any], row: dict[str, Any], horizon: int) -> dict[str, Any]:
    horizon_counts = ((model.get("counts") or {}).get(str(horizon)) or {})
    alpha = number(model.get("alpha"), MODEL_ALPHA)
    minimum_bucket = int(number(model.get("minimum_bucket"), MODEL_MIN_BUCKET))
    selected_counts = _empty_class_counts()
    selected_level = "global"

    for key in model_feature_levels(row):
        encoded = json.dumps(key, separators=(",", ":"))
        bucket = horizon_counts.get(encoded)
        if not bucket:
            continue
        sample_count = sum(int(bucket.get(label, 0)) for label in ("up", "down", "flat"))
        if key[0] == "global" or sample_count >= minimum_bucket:
            selected_counts = {label: int(bucket.get(label, 0)) for label in ("up", "down", "flat")}
            selected_level = key[0]
            break

    total = sum(selected_counts.values())
    denominator = total + alpha * 3.0
    probabilities = {
        label: (selected_counts[label] + alpha) / denominator if denominator > 0 else 1.0 / 3.0
        for label in ("up", "down", "flat")
    }
    predicted = max(probabilities, key=probabilities.get)
    return {
        "direction": predicted,
        "probabilities": probabilities,
        "sample_count": total,
        "backoff_level": selected_level,
    }


def baseline_probabilities(rows: list[dict[str, Any]], horizon: int) -> dict[str, float]:
    counts = Counter(outcome_direction(row, horizon) for row in rows)
    counts.pop(None, None)
    total = sum(counts.values())
    alpha = MODEL_ALPHA
    return {
        label: (counts.get(label, 0) + alpha) / (total + alpha * 3.0) if total else 1.0 / 3.0
        for label in ("up", "down", "flat")
    }


def evaluate_probabilities(actual: list[str], predicted: list[dict[str, float]]) -> Evaluation:
    if not actual:
        return Evaluation(rows=0, accuracy=0.0, brier=0.0, log_loss=0.0)
    correct = 0
    brier_total = 0.0
    log_total = 0.0
    labels = ("up", "down", "flat")
    for actual_label, probabilities in zip(actual, predicted):
        predicted_label = max(labels, key=lambda label: number(probabilities.get(label)))
        correct += int(predicted_label == actual_label)
        brier_total += sum((number(probabilities.get(label)) - (1.0 if label == actual_label else 0.0)) ** 2 for label in labels)
        log_total += -math.log(max(1e-12, number(probabilities.get(actual_label), 1e-12)))
    count = len(actual)
    return Evaluation(
        rows=count,
        accuracy=correct / count,
        brier=brier_total / count,
        log_loss=log_total / count,
    )


def evaluate_context_model(model: dict[str, Any], rows: list[dict[str, Any]], horizon: int) -> Evaluation:
    actual: list[str] = []
    predicted: list[dict[str, float]] = []
    for row in rows:
        label = outcome_direction(row, horizon)
        if label is None:
            continue
        actual.append(label)
        predicted.append(predict_context_model(model, row, horizon)["probabilities"])
    return evaluate_probabilities(actual, predicted)


def evaluate_baseline(probabilities: dict[str, float], rows: list[dict[str, Any]], horizon: int) -> Evaluation:
    actual = [label for row in rows if (label := outcome_direction(row, horizon)) is not None]
    return evaluate_probabilities(actual, [probabilities] * len(actual))


def build_challenger(rows: list[dict[str, Any]], model_key: str | None = None) -> dict[str, Any]:
    eligible = [row for row in rows if all(outcome_direction(row, horizon) is not None for horizon in MODEL_HORIZONS)]
    train_rows, validation_rows, test_rows = split_chronologically(eligible)
    if len(train_rows) < 5_000 or len(validation_rows) < 1_000 or len(test_rows) < 1_000:
        raise ValueError("Not enough complete chronological snapshots to train a challenger safely")

    model = train_context_model(train_rows)
    horizon_metrics: dict[str, Any] = {}
    all_validation_improved = True
    all_test_improved = True
    test_brier_gains: list[float] = []
    test_accuracy_gains: list[float] = []

    for horizon in MODEL_HORIZONS:
        baseline = baseline_probabilities(train_rows, horizon)
        validation_model = evaluate_context_model(model, validation_rows, horizon)
        validation_baseline = evaluate_baseline(baseline, validation_rows, horizon)
        test_model = evaluate_context_model(model, test_rows, horizon)
        test_baseline = evaluate_baseline(baseline, test_rows, horizon)
        validation_brier_gain = validation_baseline.brier - validation_model.brier
        test_brier_gain = test_baseline.brier - test_model.brier
        test_accuracy_gain = test_model.accuracy - test_baseline.accuracy
        all_validation_improved = all_validation_improved and validation_brier_gain > 0
        all_test_improved = all_test_improved and test_brier_gain > 0
        test_brier_gains.append(test_brier_gain)
        test_accuracy_gains.append(test_accuracy_gain)
        horizon_metrics[str(horizon)] = {
            "baseline_probabilities": baseline,
            "validation": {
                "model": validation_model.as_dict(),
                "baseline": validation_baseline.as_dict(),
                "brier_gain": round(validation_brier_gain, 8),
            },
            "test": {
                "model": test_model.as_dict(),
                "baseline": test_baseline.as_dict(),
                "brier_gain": round(test_brier_gain, 8),
                "accuracy_gain": round(test_accuracy_gain, 8),
            },
        }

    average_brier_gain = mean(test_brier_gains)
    average_accuracy_gain = mean(test_accuracy_gains)
    promotable = (
        all_validation_improved
        and all_test_improved
        and average_brier_gain >= 0.0025
        and average_accuracy_gain >= 0.005
        and len(test_rows) >= 5_000
    )
    reason = (
        "Passed chronological validation and locked-test promotion thresholds."
        if promotable
        else "Kept as challenger because it did not beat the baseline strongly enough across every locked horizon."
    )
    generated_at = utc_now()
    model_key = model_key or f"eve-context-{generated_at.strftime('%Y%m%d-%H%M%S')}"
    return {
        "model_key": model_key,
        "name": "EVE Hierarchical Context Model",
        "model_type": "hierarchical_context_frequency",
        "role": "challenger",
        "status": "ready",
        "version": generated_at.strftime("%Y.%m.%d.%H%M"),
        "trained_from": str(train_rows[0].get("candle_time")),
        "trained_to": str(train_rows[-1].get("candle_time")),
        "feature_version": MODEL_FEATURE_VERSION,
        "training_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "test_rows": len(test_rows),
        "promotable": promotable,
        "promotion_reason": reason,
        "evaluation_period": {
            "validation_from": str(validation_rows[0].get("candle_time")),
            "validation_to": str(validation_rows[-1].get("candle_time")),
            "test_from": str(test_rows[0].get("candle_time")),
            "test_to": str(test_rows[-1].get("candle_time")),
        },
        "metrics": {
            "horizons": horizon_metrics,
            "average_test_brier_gain": round(average_brier_gain, 8),
            "average_test_accuracy_gain": round(average_accuracy_gain, 8),
            "promotion_thresholds": {
                "all_validation_horizons_improve": True,
                "all_test_horizons_improve": True,
                "minimum_average_brier_gain": 0.0025,
                "minimum_average_accuracy_gain": 0.005,
                "minimum_test_rows": 5000,
            },
        },
        "artifact": model,
        "notes": reason,
    }


def year_stability(rows: list[dict[str, Any]], predicate, value_getter, baseline_getter=None) -> float:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        timestamp = as_utc(row.get("candle_time"))
        if timestamp:
            by_year[timestamp.year].append(row)
    signs: list[int] = []
    for year_rows in by_year.values():
        group_values = [value_getter(row) for row in year_rows if predicate(row) and value_getter(row) is not None]
        if len(group_values) < 20:
            continue
        baseline_values = [
            (baseline_getter(row) if baseline_getter else value_getter(row))
            for row in year_rows
            if (baseline_getter(row) if baseline_getter else value_getter(row)) is not None
        ]
        if not baseline_values:
            continue
        signs.append(sign(mean(group_values) - mean(baseline_values)))
    if not signs:
        return 0.0
    positive = sum(1 for value in signs if value > 0)
    negative = sum(1 for value in signs if value < 0)
    return max(positive, negative) / len(signs)


def confidence_score(sample_count: int, effect_size: float, stability: float, tests_considered: int = 1) -> float:
    sample_component = min(30.0, math.log10(max(10, sample_count)) * 10.0)
    effect_component = min(35.0, abs(effect_size) * 1.5)
    stability_component = max(0.0, min(25.0, stability * 25.0))
    multiple_test_penalty = min(20.0, math.log10(max(1, tests_considered)) * 7.0)
    return max(0.0, min(99.0, 15.0 + sample_component + effect_component + stability_component - multiple_test_penalty))


def test_named_question(question: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    key = str(question.get("question_key") or "")
    train_rows, _, test_rows = split_chronologically(rows)
    if not test_rows:
        return {"status": "rejected", "sample_count": 0, "effect_size": 0.0, "confidence_score": 0.0, "stability_score": 0.0, "evidence": {"reason": "No locked test data"}}

    if key == "compression-next-60m-expansion":
        threshold = percentile([number(row.get("compression_ratio"), 1.0) for row in train_rows], 0.25)
        predicate = lambda row: number(row.get("compression_ratio"), 1.0) <= threshold
        value = lambda row: outcome_excursion(row, 60)
        group = [value(row) for row in test_rows if predicate(row) and value(row) is not None]
        baseline = [value(row) for row in test_rows if value(row) is not None]
        effect = ((mean(group) / mean(baseline)) - 1.0) * 100.0 if group and mean(baseline) else 0.0
        stability = year_stability(rows, predicate, value)
        title = "Compressed M5 states and the next 60-minute expansion"
    elif key == "three-candle-momentum-continuation":
        predicate = lambda row: abs(int(number(row.get("streak")))) >= 3
        value = lambda row: 1.0 if (outcome_for(row, 30) or {}).get("continuation") is True else 0.0
        group = [value(row) for row in test_rows if predicate(row) and outcome_for(row, 30) is not None]
        baseline = [value(row) for row in test_rows if outcome_for(row, 30) is not None]
        effect = (mean(group) - mean(baseline)) * 100.0 if group and baseline else 0.0
        stability = year_stability(rows, predicate, value)
        title = "Three-candle momentum and 30-minute continuation"
    elif key == "multihorizon-alignment-60m":
        predicate = lambda row: abs(int(number(row.get("alignment_score")))) >= 3
        def value(row):
            actual = outcome_direction(row, 60)
            aligned = sign(number(row.get("alignment_score")))
            return None if actual is None or aligned == 0 else 1.0 if actual == ("up" if aligned > 0 else "down") else 0.0
        group = [value(row) for row in test_rows if predicate(row) and value(row) is not None]
        baseline = [value(row) for row in test_rows if value(row) is not None]
        effect = (mean(group) - mean(baseline)) * 100.0 if group and baseline else 0.0
        stability = year_stability(rows, predicate, value)
        title = "Multi-timeframe alignment and 60-minute direction"
    elif key == "session-weekday-interaction":
        train_groups: dict[tuple[int, str], list[float]] = defaultdict(list)
        for row in train_rows:
            outcome = outcome_for(row, 60)
            if outcome is not None:
                train_groups[(int(number(row.get("weekday"))), str(row.get("session")))].append(abs(number(outcome.get("close_return_pct"))))
        eligible = [(group_key, values) for group_key, values in train_groups.items() if len(values) >= RESEARCH_MIN_SAMPLE]
        selected = max(eligible, key=lambda item: mean(item[1]))[0] if eligible else (0, "none")
        predicate = lambda row: (int(number(row.get("weekday"))), str(row.get("session"))) == selected
        value = lambda row: abs(number((outcome_for(row, 60) or {}).get("close_return_pct"))) if outcome_for(row, 60) else None
        group = [value(row) for row in test_rows if predicate(row) and value(row) is not None]
        baseline = [value(row) for row in test_rows if value(row) is not None]
        effect = ((mean(group) / mean(baseline)) - 1.0) * 100.0 if group and mean(baseline) else 0.0
        stability = year_stability(rows, predicate, value)
        title = f"Weekday/session interaction {selected[0]} · {selected[1]}"
    elif key == "regime-pattern-failure":
        train_groups: dict[str, list[float]] = defaultdict(list)
        for row in train_rows:
            outcome = outcome_for(row, 60)
            if outcome is not None:
                train_groups[str(row.get("regime"))].append(1.0 if outcome.get("continuation") is True else 0.0)
        eligible = [(name, values) for name, values in train_groups.items() if len(values) >= RESEARCH_MIN_SAMPLE]
        best = max(eligible, key=lambda item: mean(item[1]))[0] if eligible else "range"
        predicate = lambda row: str(row.get("regime")) == best
        value = lambda row: 1.0 if (outcome_for(row, 60) or {}).get("continuation") is True else 0.0
        group = [value(row) for row in test_rows if predicate(row) and outcome_for(row, 60) is not None]
        baseline = [value(row) for row in test_rows if outcome_for(row, 60) is not None]
        effect = (mean(group) - mean(baseline)) * 100.0 if group and baseline else 0.0
        stability = year_stability(rows, predicate, value)
        title = f"Regime-dependent continuation · {best}"
    else:
        evidence = question.get("evidence") or {}
        sample_count = int(question.get("sample_count") or evidence.get("sample_count") or 0)
        effect = number(question.get("effect_size"), number(evidence.get("effect_vs_baseline_pct")))
        stability = 0.50
        confidence = confidence_score(sample_count, effect, stability, 12)
        status = "promising" if sample_count >= 40 and abs(effect) >= 5.0 and confidence >= 55 else "rejected"
        return {
            "status": status,
            "sample_count": sample_count,
            "effect_size": round(effect, 6),
            "confidence_score": round(confidence, 3),
            "stability_score": round(stability * 100.0, 3),
            "evidence": {**evidence, "method": "calendar_baseline_observation_pending_yearly_validation"},
            "title": str(question.get("question") or "Calendar observation"),
        }

    sample_count = len(group)
    confidence = confidence_score(sample_count, effect, stability, 5)
    if sample_count < RESEARCH_MIN_SAMPLE or stability < 0.45 or abs(effect) < 1.0:
        status = "rejected"
    elif confidence >= 78 and stability >= 0.70 and abs(effect) >= 5.0:
        status = "answered"
    elif confidence >= 62 and stability >= 0.55 and abs(effect) >= 3.0:
        status = "promising"
    else:
        status = "rejected"
    return {
        "status": status,
        "sample_count": sample_count,
        "effect_size": round(effect, 6),
        "confidence_score": round(confidence, 3),
        "stability_score": round(stability * 100.0, 3),
        "title": title,
        "evidence": {
            "locked_test_sample": sample_count,
            "locked_test_baseline_sample": len(baseline),
            "effect_size": round(effect, 6),
            "stability_fraction": round(stability, 6),
            "method": "chronological_train_select_locked_test",
        },
    }


def candidate_dimensions(rows: list[dict[str, Any]]) -> list[tuple[str, Any, Any]]:
    compression_threshold = percentile([number(row.get("compression_ratio"), 1.0) for row in rows], 0.25)
    dimensions: list[tuple[str, Any, Any]] = []
    for weekday in range(1, 6):
        dimensions.append((f"weekday={weekday}", lambda row, weekday=weekday: int(number(row.get("weekday"))) == weekday, {"weekday": weekday}))
    for month in range(1, 13):
        dimensions.append((f"month={month}", lambda row, month=month: int(number(row.get("month"))) == month, {"month": month}))
    for session in ("asia", "london", "new_york", "off_session"):
        dimensions.append((f"session={session}", lambda row, session=session: str(row.get("session")) == session, {"session": session}))
    for regime in ("compression", "trend_up", "trend_down", "high_volatility", "range"):
        dimensions.append((f"regime={regime}", lambda row, regime=regime: str(row.get("regime")) == regime, {"regime": regime}))
    for hour in range(24):
        dimensions.append((f"hour={hour}", lambda row, hour=hour: int(number(row.get("hour_utc"))) == hour, {"hour_utc": hour}))
    dimensions.extend([
        ("alignment=strong", lambda row: abs(int(number(row.get("alignment_score")))) >= 3, {"alignment": "strong"}),
        ("compression=low", lambda row: number(row.get("compression_ratio"), 1.0) <= compression_threshold, {"compression_lte": compression_threshold}),
        ("streak=up3", lambda row: int(number(row.get("streak"))) >= 3, {"streak": "up3"}),
        ("streak=down3", lambda row: int(number(row.get("streak"))) <= -3, {"streak": "down3"}),
    ])
    return dimensions


def discover_hypotheses(rows: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    train_rows, _, test_rows = split_chronologically(rows)
    if not test_rows:
        return 0, []
    dimensions = candidate_dimensions(train_rows)
    candidates: list[dict[str, Any]] = []
    tests = 0

    combinations: list[tuple[str, Any, dict[str, Any]]] = []
    for name, predicate, definition in dimensions:
        combinations.append((name, predicate, definition))
    session_dimensions = [item for item in dimensions if item[0].startswith("session=")]
    weekday_dimensions = [item for item in dimensions if item[0].startswith("weekday=")]
    regime_dimensions = [item for item in dimensions if item[0].startswith("regime=")]
    for first in weekday_dimensions:
        for second in session_dimensions:
            combinations.append((f"{first[0]} & {second[0]}", lambda row, a=first[1], b=second[1]: a(row) and b(row), {**first[2], **second[2]}))
    for first in regime_dimensions:
        for second in session_dimensions:
            combinations.append((f"{first[0]} & {second[0]}", lambda row, a=first[1], b=second[1]: a(row) and b(row), {**first[2], **second[2]}))

    baseline_test_values = [outcome_excursion(row, 60) for row in test_rows]
    baseline_test_values = [value for value in baseline_test_values if value is not None]
    baseline_mean = mean(baseline_test_values)

    for name, predicate, definition in combinations:
        tests += 1
        train_group = [outcome_excursion(row, 60) for row in train_rows if predicate(row)]
        train_group = [value for value in train_group if value is not None]
        if len(train_group) < RESEARCH_MIN_SAMPLE:
            continue
        test_group = [outcome_excursion(row, 60) for row in test_rows if predicate(row)]
        test_group = [value for value in test_group if value is not None]
        if len(test_group) < max(50, RESEARCH_MIN_SAMPLE // 3) or baseline_mean <= 0:
            continue
        effect = ((mean(test_group) / baseline_mean) - 1.0) * 100.0
        stability = year_stability(rows, predicate, lambda row: outcome_excursion(row, 60))
        confidence = confidence_score(len(test_group), effect, stability, len(combinations))
        if effect < 7.5 or stability < 0.55 or confidence < 60:
            continue
        key = uuid.uuid5(uuid.NAMESPACE_URL, f"eve:{name}:60m-excursion").hex
        candidates.append({
            "question_key": f"auto-{key[:20]}",
            "discovery_key": f"auto-{key[:24]}",
            "category": "autonomous_pattern_discovery",
            "question": f"Why has {name} produced larger 60-minute moves than the general market?",
            "rationale": f"The locked test sample was {effect:.1f}% above the baseline 60-minute excursion.",
            "title": f"{name} has shown above-baseline 60-minute expansion",
            "summary": f"Across {len(test_group):,} locked-test observations, the average 60-minute excursion was {effect:.1f}% above baseline. Year stability was {stability * 100:.0f}%. This remains conditional evidence, not a guaranteed trade signal.",
            "sample_count": len(test_group),
            "effect_size": round(effect, 6),
            "confidence_score": round(confidence, 3),
            "stability_score": round(stability * 100.0, 3),
            "definition": definition,
            "evidence": {
                "locked_test_sample": len(test_group),
                "locked_test_effect_pct": round(effect, 6),
                "year_stability_fraction": round(stability, 6),
                "tests_considered": len(combinations),
                "multiple_testing_penalty_applied": True,
                "horizon_minutes": 60,
            },
        })

    candidates.sort(key=lambda item: (item["confidence_score"], item["effect_size"]), reverse=True)
    return tests, candidates[:RESEARCH_TOP_FINDINGS]


def prediction_payload(model_row: dict[str, Any], snapshot: dict[str, Any], horizon: int, source: str) -> dict[str, Any]:
    prediction = predict_context_model(model_row.get("artifact") or {}, snapshot, horizon)
    probabilities = prediction["probabilities"]
    expected_move = None
    return {
        "symbol": snapshot.get("symbol") or "XAU/USD",
        "model_key": model_row["model_key"],
        "source": source,
        "snapshot_time": snapshot["candle_time"],
        "horizon_minutes": horizon,
        "predicted_direction": prediction["direction"],
        "probability_up": probabilities["up"],
        "probability_down": probabilities["down"],
        "probability_flat": probabilities["flat"],
        "expected_move_atr": expected_move,
        "explanation": {
            "backoff_level": prediction["backoff_level"],
            "historical_bucket_sample": prediction["sample_count"],
            "regime": snapshot.get("regime"),
            "session": snapshot.get("session"),
            "alignment_band": alignment_band(snapshot.get("alignment_score")),
            "compression_band": compression_band(snapshot.get("compression_ratio")),
        },
        "status": "pending",
    }


def brier_score_for_prediction(prediction: dict[str, Any], actual: str) -> float:
    probabilities = {
        "up": number(prediction.get("probability_up")),
        "down": number(prediction.get("probability_down")),
        "flat": number(prediction.get("probability_flat")),
    }
    return sum((probabilities[label] - (1.0 if label == actual else 0.0)) ** 2 for label in probabilities)


class AutonomousLearningService:
    def __init__(self, settings: Settings, repo: SupabaseRepository) -> None:
        self.settings = settings
        self.repo = repo
        self.worker_id = f"autonomy-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._manual_wake = asyncio.Event()
        self._cycle_lock = asyncio.Lock()

    async def stop(self) -> None:
        self._stop.set()
        self._manual_wake.set()

    async def request_cycle(self) -> None:
        self._manual_wake.set()

    async def loop(self) -> None:
        if not self.settings.autonomous_learning_enabled:
            logger.info("Autonomous learning is disabled by configuration")
            return
        logger.info("Autonomous learning worker %s started", self.worker_id)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self.settings.autonomous_startup_delay_seconds)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self.run_cycle("scheduled")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Autonomous learning cycle failed")
            self._manual_wake.clear()
            try:
                await asyncio.wait_for(
                    self._wait_for_wake_or_stop(),
                    timeout=self.settings.autonomous_cycle_minutes * 60,
                )
            except asyncio.TimeoutError:
                pass

    async def _wait_for_wake_or_stop(self) -> None:
        stop_task = asyncio.create_task(self._stop.wait())
        wake_task = asyncio.create_task(self._manual_wake.wait())
        done, pending = await asyncio.wait({stop_task, wake_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            await task

    async def run_cycle(self, trigger: str = "manual") -> dict[str, Any]:
        if self._cycle_lock.locked():
            return {"status": "skipped", "message": "An autonomous cycle is already running"}
        async with self._cycle_lock:
            run = await self.repo.create_autonomous_run({
                "symbol": "XAU/USD",
                "cycle_type": "full_cycle",
                "trigger_source": trigger,
                "status": "running",
                "stage": "starting",
                "worker_id": self.worker_id,
                "started_at": utc_now().isoformat(),
                "message": "EVE autonomous cycle started",
            })
            run_id = str(run["id"])
            metrics: dict[str, Any] = {
                "learning_queued": False,
                "predictions_created": 0,
                "predictions_graded": 0,
                "questions_tested": 0,
                "discoveries_survived": 0,
                "model_trained": False,
                "model_promoted": False,
            }
            try:
                state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
                if not state.get("initial_build_complete"):
                    await self.repo.update_autonomous_run(
                        run_id,
                        status="skipped",
                        stage="waiting_for_foundation",
                        message="Initial learning foundation has not been built yet",
                        metrics=metrics,
                        finished_at=utc_now().isoformat(),
                    )
                    return {"status": "skipped", "message": "Initial learning foundation has not been built yet"}

                await self.repo.upsert_learning_state(
                    "XAU/USD",
                    SNAPSHOT_INTERVAL,
                    autonomous_status="active",
                    last_auto_cycle_at=utc_now().isoformat(),
                    next_auto_cycle_at=(utc_now() + timedelta(minutes=self.settings.autonomous_cycle_minutes)).isoformat(),
                    last_auto_message="Checking new candles, outcomes, research questions and models",
                    last_auto_error=None,
                )

                await self.repo.update_autonomous_run(run_id, stage="incremental_learning", message="Checking whether new completed candles need to be learned")
                metrics["learning_queued"] = await self._queue_incremental_learning_if_needed()

                await self.repo.update_autonomous_run(run_id, stage="grading_predictions", message="Grading predictions whose future outcomes are now known")
                metrics["predictions_graded"] = await self._grade_pending_predictions()

                await self.repo.update_autonomous_run(run_id, stage="predictions", message="Recording fresh approved and shadow predictions")
                metrics["predictions_created"] = await self._create_latest_predictions()

                state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or state
                active_learning = await self.repo.has_active_learning_run("XAU/USD", SNAPSHOT_INTERVAL)
                research_due = self._due(state.get("last_research_cycle_at"), self.settings.autonomous_research_hours)
                model_due = self._due(state.get("last_model_training_at"), self.settings.autonomous_model_hours)

                research_rows: list[dict[str, Any]] | None = None
                if not active_learning and (research_due or model_due):
                    await self.repo.update_autonomous_run(run_id, stage="loading_research_memory", message="Loading complete learning snapshots once for this autonomous cycle")
                    research_rows = await self._fetch_all_snapshots(complete_only=True)

                if research_rows is not None and research_due:
                    await self.repo.update_autonomous_run(run_id, stage="autonomous_research", message="EVE is testing existing and newly generated questions")
                    research_result = await self._run_research_cycle(research_rows)
                    metrics.update(research_result)

                if research_rows is not None and model_due:
                    await self.repo.update_autonomous_run(run_id, stage="challenger_training", message="Training and testing a new challenger model on chronological holdouts")
                    model_result = await self._train_challenger(research_rows)
                    metrics.update(model_result)

                await self.repo.refresh_autonomous_learning_state("XAU/USD", SNAPSHOT_INTERVAL)
                await self.repo.upsert_learning_state(
                    "XAU/USD",
                    SNAPSHOT_INTERVAL,
                    autonomous_status="active",
                    last_auto_cycle_at=utc_now().isoformat(),
                    next_auto_cycle_at=(utc_now() + timedelta(minutes=self.settings.autonomous_cycle_minutes)).isoformat(),
                    last_auto_message=self._cycle_message(metrics),
                    last_auto_error=None,
                )
                await self.repo.update_autonomous_run(
                    run_id,
                    status="complete",
                    stage="complete",
                    message=self._cycle_message(metrics),
                    metrics=metrics,
                    finished_at=utc_now().isoformat(),
                )
                return {"status": "complete", "metrics": metrics}
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Autonomous run %s failed", run_id)
                await self.repo.update_autonomous_run(
                    run_id,
                    status="failed",
                    stage="failed",
                    message="Autonomous cycle failed — see Railway logs",
                    error=str(exc)[:4000],
                    metrics=metrics,
                    finished_at=utc_now().isoformat(),
                )
                await self.repo.upsert_learning_state(
                    "XAU/USD",
                    SNAPSHOT_INTERVAL,
                    autonomous_status="error",
                    last_auto_error=str(exc)[:4000],
                    last_auto_message="Autonomous cycle failed",
                )
                raise

    @staticmethod
    def _due(value: Any, hours: int) -> bool:
        timestamp = as_utc(value)
        return timestamp is None or utc_now() >= timestamp + timedelta(hours=hours)

    @staticmethod
    def _cycle_message(metrics: dict[str, Any]) -> str:
        pieces = []
        if metrics.get("learning_queued"):
            pieces.append("new-candle learning queued")
        pieces.append(f"{int(metrics.get('predictions_graded') or 0)} predictions graded")
        if metrics.get("questions_tested"):
            pieces.append(f"{int(metrics['questions_tested'])} questions tested")
        if metrics.get("discoveries_survived"):
            pieces.append(f"{int(metrics['discoveries_survived'])} findings survived")
        if metrics.get("model_trained"):
            pieces.append("challenger trained")
        if metrics.get("model_promoted"):
            pieces.append("challenger promoted")
        return " · ".join(pieces) if pieces else "Autonomous checks complete"

    async def _queue_incremental_learning_if_needed(self) -> bool:
        if await self.repo.has_active_learning_run("XAU/USD", SNAPSHOT_INTERVAL):
            return False
        state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        source_state = await self.repo.get_state("XAU/USD", "5min") or {}
        latest_source = as_utc(source_state.get("latest_stored"))
        latest_snapshot = as_utc(state.get("last_snapshot_time"))
        if not latest_source or not latest_snapshot:
            return False
        # A 15-minute research anchor is available only once its M5 candle is stored.
        if latest_source <= latest_snapshot + timedelta(minutes=10):
            return False
        await self.repo.create_learning_run({
            "symbol": "XAU/USD",
            "source_interval": "5min",
            "snapshot_interval": SNAPSHOT_INTERVAL,
            "full_rebuild": False,
            "message": "Autonomous new-candle learning update queued",
        })
        await self.repo.upsert_learning_state(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            status="queued",
            last_auto_message="New completed candles detected; incremental learning queued",
        )
        await self.repo.log_event(
            "info",
            "autonomy",
            "Autonomous incremental learning update queued",
            {"latest_source": latest_source.isoformat(), "latest_snapshot": latest_snapshot.isoformat()},
        )
        return True

    async def _fetch_all_snapshots(self, complete_only: bool = True) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            page = await self.repo.fetch_learning_snapshots_page(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                after=after,
                complete_only=complete_only,
                limit=1000,
            )
            if not page:
                break
            rows.extend(page)
            if len(page) < 1000:
                break
            after = str(page[-1]["candle_time"])
        return rows

    async def _run_research_cycle(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if len(rows) < 5_000:
            return {"questions_tested": 0, "discoveries_survived": 0}
        questions = await self.repo.list_research_questions("XAU/USD", limit=100)
        tested = 0
        survived = 0
        named_findings: list[dict[str, Any]] = []
        for question in questions:
            if question.get("status") == "archived":
                continue
            # v1.7 continuous-history questions have already completed their own
            # chronological validation and locked test. Do not overwrite those
            # results with the older generic v1.6 fallback evaluator.
            if str(question.get("generated_by") or "").startswith("continuous-history-"):
                continue
            result = test_named_question(question, rows)
            tested += 1
            await self.repo.update_research_question(
                str(question["id"]),
                status=result["status"],
                sample_count=result["sample_count"],
                effect_size=result["effect_size"],
                confidence_score=result["confidence_score"],
                evidence={**(question.get("evidence") or {}), "autonomous_test": result["evidence"]},
            )
            if result["status"] in {"promising", "answered"}:
                survived += 1
                discovery_key = f"question-{question['question_key']}"
                named_findings.append({
                    "discovery_key": discovery_key,
                    "symbol": "XAU/USD",
                    "question_id": question.get("id"),
                    "title": result.get("title") or question.get("question"),
                    "summary": f"Locked chronological testing found an effect of {result['effect_size']:.2f} with {result['sample_count']:,} test observations and {result['stability_score']:.0f}% year stability.",
                    "category": question.get("category") or "research",
                    "status": "validated" if result["status"] == "answered" and result["confidence_score"] >= 85 else "promising",
                    "sample_count": result["sample_count"],
                    "effect_size": result["effect_size"],
                    "confidence_score": result["confidence_score"],
                    "stability_score": result["stability_score"],
                    "evidence": result["evidence"],
                    "first_observed_at": rows[0].get("candle_time"),
                    "last_observed_at": rows[-1].get("candle_time"),
                })

        generated_tests, generated = discover_hypotheses(rows)
        tested += generated_tests
        auto_questions: list[dict[str, Any]] = []
        auto_discoveries: list[dict[str, Any]] = []
        for item in generated:
            status = "answered" if item["confidence_score"] >= 85 and item["stability_score"] >= 75 else "promising"
            auto_questions.append({
                "question_key": item["question_key"],
                "symbol": "XAU/USD",
                "category": item["category"],
                "question": item["question"],
                "rationale": item["rationale"],
                "priority": min(100, int(item["confidence_score"])),
                "status": status,
                "generated_by": "eve-autonomous-research-v1",
                "evidence": item["evidence"],
                "test_definition": item["definition"],
                "sample_count": item["sample_count"],
                "effect_size": item["effect_size"],
                "confidence_score": item["confidence_score"],
            })
            auto_discoveries.append({
                "discovery_key": item["discovery_key"],
                "symbol": "XAU/USD",
                "title": item["title"],
                "summary": item["summary"],
                "category": item["category"],
                "status": "validated" if status == "answered" else "promising",
                "sample_count": item["sample_count"],
                "effect_size": item["effect_size"],
                "confidence_score": item["confidence_score"],
                "stability_score": item["stability_score"],
                "evidence": item["evidence"],
                "first_observed_at": rows[0].get("candle_time"),
                "last_observed_at": rows[-1].get("candle_time"),
            })
        await self.repo.upsert_research_questions(auto_questions)
        await self.repo.upsert_discoveries(named_findings + auto_discoveries)
        survived += len(auto_discoveries)

        report = {
            "symbol": "XAU/USD",
            "report_date": utc_now().date().isoformat(),
            "cycle_started_at": utc_now().isoformat(),
            "questions_tested": tested,
            "questions_rejected": max(0, tested - survived),
            "discoveries_promising": sum(1 for item in named_findings + auto_discoveries if item["status"] == "promising"),
            "discoveries_validated": sum(1 for item in named_findings + auto_discoveries if item["status"] == "validated"),
            "summary": f"EVE tested {tested:,} predefined and generated hypotheses. {survived:,} findings survived the locked chronological and year-stability filters.",
            "metrics": {
                "snapshot_rows": len(rows),
                "generated_candidate_tests": generated_tests,
                "multiple_testing_penalty_applied": True,
            },
            "findings": (named_findings + auto_discoveries)[:10],
        }
        await self.repo.upsert_research_report(report)
        await self.repo.upsert_learning_state(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            last_research_cycle_at=utc_now().isoformat(),
            questions_tested_last_cycle=tested,
            last_auto_message=report["summary"],
        )
        return {"questions_tested": tested, "discoveries_survived": survived}

    async def _train_challenger(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        latest_complete = as_utc(rows[-1].get("candle_time")) if rows else None
        newest_model_time = None
        for key in (state.get("challenger_model_key"), state.get("approved_model_key")):
            if not key:
                continue
            existing_model = await self.repo.get_model(str(key))
            evaluation_period = (existing_model or {}).get("evaluation_period") or {}
            observed_to = as_utc(evaluation_period.get("test_to") or (existing_model or {}).get("trained_to"))
            if observed_to and (newest_model_time is None or observed_to > newest_model_time):
                newest_model_time = observed_to
        if latest_complete and newest_model_time and latest_complete <= newest_model_time:
            await self.repo.upsert_learning_state(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                last_model_training_at=utc_now().isoformat(),
                last_auto_message="Model training skipped because no new complete learning snapshots exist.",
            )
            return {"model_trained": False, "model_promoted": False}
        challenger = build_challenger(rows)
        challenger["parent_model_key"] = state.get("approved_model_key")
        await self.repo.upsert_model(challenger)
        promoted = False
        if challenger["promotable"] and self.settings.autonomous_model_promotion_enabled:
            await self.repo.promote_model(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                challenger["model_key"],
                state.get("approved_model_key"),
            )
            promoted = True
        else:
            await self.repo.upsert_learning_state(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                challenger_model_key=challenger["model_key"],
            )
        await self.repo.upsert_learning_state(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            last_model_training_at=utc_now().isoformat(),
            last_auto_message=challenger["promotion_reason"],
        )
        await self.repo.log_event(
            "success",
            "autonomy",
            "Autonomous challenger training complete",
            {
                "model_key": challenger["model_key"],
                "promotable": challenger["promotable"],
                "promoted": promoted,
                "metrics": challenger["metrics"],
            },
        )
        return {"model_trained": True, "model_promoted": promoted}

    async def _create_latest_predictions(self) -> int:
        snapshot = await self.repo.get_latest_learning_snapshot("XAU/USD", SNAPSHOT_INTERVAL)
        if not snapshot:
            return 0
        state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        model_keys: list[tuple[str, str]] = []
        if state.get("approved_model_key"):
            model_keys.append((str(state["approved_model_key"]), "approved"))
        if state.get("challenger_model_key") and state.get("challenger_model_key") != state.get("approved_model_key"):
            model_keys.append((str(state["challenger_model_key"]), "shadow"))
        created = 0
        for model_key, source in model_keys:
            model = await self.repo.get_model(model_key)
            if not model or not model.get("artifact"):
                continue
            for horizon in MODEL_HORIZONS:
                # Never create a "prediction" after that horizon's outcome is already known.
                if outcome_for(snapshot, horizon) is not None:
                    continue
                payload = prediction_payload(model, snapshot, horizon, source)
                inserted = await self.repo.upsert_prediction(payload)
                created += int(bool(inserted))
        return created

    async def _grade_pending_predictions(self) -> int:
        pending = await self.repo.list_pending_predictions("XAU/USD", limit=300)
        graded = 0
        for prediction in pending:
            snapshot = await self.repo.get_learning_snapshot(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                str(prediction["snapshot_time"]),
            )
            if not snapshot:
                continue
            horizon = int(prediction["horizon_minutes"])
            outcome = outcome_for(snapshot, horizon)
            if not outcome:
                continue
            actual = str(outcome.get("direction") or "unclear")
            if actual not in {"up", "down", "flat"}:
                continue
            predicted = str(prediction.get("predicted_direction") or "unclear")
            score = brier_score_for_prediction(prediction, actual)
            await self.repo.grade_prediction(
                str(prediction["id"]),
                actual_direction=actual,
                actual_return_pct=number(outcome.get("close_return_pct")),
                actual_max_up_atr=None if outcome.get("max_up_atr") is None else number(outcome.get("max_up_atr")),
                actual_max_down_atr=None if outcome.get("max_down_atr") is None else number(outcome.get("max_down_atr")),
                brier_score=score,
                grade={
                    "correct_direction": predicted == actual,
                    "predicted_direction": predicted,
                    "actual_direction": actual,
                },
            )
            graded += 1
        return graded
