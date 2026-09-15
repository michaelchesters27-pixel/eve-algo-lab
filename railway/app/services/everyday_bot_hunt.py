from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from app.services import high_resolution_validation as validation_module
from app.services import strategy_lab as strategy_lab_module
from app.services.autonomy import number, split_chronologically
from app.services.historical_research import predicate_from_definition
from app.services.learning import as_utc


EVERYDAY_TRACK = "everyday_bot_v1"
TARGET_PF = 1.50
TARGET_FULL_HISTORY_OPPORTUNITIES = 1000
TARGET_FULL_DAILY_COVERAGE = 0.60
MIN_SEGMENT_DAILY_COVERAGE = 0.55
MAX_EVERYDAY_SPECS_PER_GENERATION = 180

CALENDAR_FIELDS = {"weekday", "month", "quarter", "week_of_month"}
EXACT_TIME_FIELDS = {"hour_utc"}
RISK_GRID = (
    (0.75, 1.50),
    (1.00, 2.00),
    (1.00, 2.50),
    (1.25, 2.50),
    (1.50, 3.00),
)


def _canonical_condition(condition: dict[str, Any]) -> tuple[str, str]:
    return str(condition.get("field") or ""), repr(condition.get("value"))


def _dedupe_conditions(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for condition in conditions:
        key = _canonical_condition(condition)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        output.append(dict(condition))
    return output


def broadened_condition_sets(source_conditions: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Build broad rules that can plausibly fire on most trading days.

    Calendar restrictions are always removed. A second variant also removes an
    exact UTC hour so EVE can test whether the underlying market behaviour works
    throughout a wider intraday window. Empty conditions are allowed: that is a
    legitimate test of the direction rule itself, not a forced trade.
    """

    without_calendar = _dedupe_conditions(
        [item for item in source_conditions if str(item.get("field") or "") not in CALENDAR_FIELDS]
    )
    without_calendar_or_hour = _dedupe_conditions(
        [item for item in without_calendar if str(item.get("field") or "") not in EXACT_TIME_FIELDS]
    )
    variants: list[tuple[str, list[dict[str, Any]]]] = [("daily_window", without_calendar)]
    if without_calendar_or_hour != without_calendar:
        variants.append(("daily_broad", without_calendar_or_hour))
    return variants


def _risk_pair(source: dict[str, Any], generation: int, variant: str, family: str) -> tuple[float, float]:
    identity = f"{source.get('job_key')}|{source.get('id')}|{generation}|{variant}|{family}"
    bucket = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16) % len(RISK_GRID)
    return RISK_GRID[bucket]


def build_everyday_specs(source_jobs: list[dict[str, Any]], generation: int) -> list[dict[str, Any]]:
    """Create a controlled high-frequency search lane from strong research evidence."""

    output: dict[str, dict[str, Any]] = {}
    ordered_sources = sorted(
        (item for item in source_jobs if item.get("result_status") in {"validated", "promising"}),
        key=lambda item: (item.get("result_status") != "validated", -number(item.get("confidence_score"))),
    )
    for source in ordered_sources:
        definition = dict(source.get("test_definition") or {})
        source_conditions = list(definition.get("conditions") or [])
        horizon = max(15, min(240, int(number(definition.get("horizon_minutes"), 60))))
        families = strategy_lab_module.infer_families(source)
        for variant_name, broad_conditions in broadened_condition_sets(source_conditions):
            for base_family, direction_rule, condition_mode in families:
                stop_atr, target_atr = _risk_pair(source, generation, variant_name, base_family)
                family = f"everyday_{base_family}"
                rules = {
                    "engine_version": strategy_lab_module.STRATEGY_ENGINE_VERSION,
                    "research_track": EVERYDAY_TRACK,
                    "target_profit_factor": TARGET_PF,
                    "target_full_history_opportunities": TARGET_FULL_HISTORY_OPPORTUNITIES,
                    "target_daily_coverage": TARGET_FULL_DAILY_COVERAGE,
                    "source_conditions": broad_conditions,
                    "condition_mode": condition_mode,
                    "direction_rule": direction_rule,
                    "horizon_minutes": horizon,
                    "stop_atr": stop_atr,
                    "target_atr": target_atr,
                    "cooldown_minutes": horizon,
                    "cost_r": 0.03,
                    "research_grade_only": True,
                }
                digest = hashlib.sha256(
                    strategy_lab_module.canonical(
                        {"source": source.get("job_key"), "family": family, "variant": variant_name, "rules": rules}
                    ).encode()
                ).hexdigest()
                key = f"strategy-everyday-{digest[:20]}"
                mode_label = "use" if condition_mode == "include" else "avoid"
                rr = target_atr / stop_atr
                output[key] = {
                    "candidate_key": key,
                    "symbol": source.get("symbol") or "XAU/USD",
                    "snapshot_interval": source.get("snapshot_interval") or strategy_lab_module.SNAPSHOT_INTERVAL,
                    "generation": generation,
                    "priority": 94 if source.get("result_status") == "validated" else 82,
                    "source_research_job_id": source.get("id"),
                    "source_job_key": source.get("job_key"),
                    "source_question": source.get("question"),
                    "name": f"Everyday Hunt · {base_family.replace('_', ' ').title()} · {variant_name.replace('_', ' ').title()} · {rr:.1f}R",
                    "family": family,
                    "hypothesis": (
                        "Search specifically for a broad, repeatable XAUUSD edge that can appear on most trading days. "
                        f"Remove calendar over-specialisation, {mode_label} the remaining market context, use "
                        f"{direction_rule.replace('_', ' ')}, and demand PF >= {TARGET_PF:.2f} without forcing trades."
                    ),
                    "rules": rules,
                    "backtest_config": {
                        "chronological_split": [0.70, 0.15, 0.15],
                        "non_overlapping_trades": True,
                        "conservative_same_bar_resolution": True,
                        "metric_unit": "R",
                        "research_track": EVERYDAY_TRACK,
                    },
                    "status": "queued",
                }
                if len(output) >= MAX_EVERYDAY_SPECS_PER_GENERATION:
                    return list(output.values())
    return list(output.values())


def opportunity_coverage(rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    predicate = predicate_from_definition({"conditions": rules.get("source_conditions") or []})
    condition_mode = str(rules.get("condition_mode") or "include")
    direction_rule = str(rules.get("direction_rule") or "current_direction")
    horizon = max(5, int(number(rules.get("horizon_minutes"), 60)))
    cooldown = max(5, int(number(rules.get("cooldown_minutes"), horizon)))

    available_days: set[str] = set()
    opportunity_days: set[str] = set()
    opportunities = 0
    next_allowed = None
    for row in rows:
        candle_time = as_utc(row.get("candle_time"))
        if candle_time is None:
            continue
        day = candle_time.date().isoformat()
        available_days.add(day)
        if next_allowed and candle_time < next_allowed:
            continue
        matched = predicate(row)
        eligible = matched if condition_mode == "include" else not matched
        if not eligible:
            continue
        direction = strategy_lab_module.candidate_direction(row, direction_rule)
        if direction == 0:
            continue
        opportunities += 1
        opportunity_days.add(day)
        next_allowed = candle_time + timedelta(minutes=cooldown)

    total_days = len(available_days)
    covered_days = len(opportunity_days)
    coverage = covered_days / total_days if total_days else 0.0
    return {
        "available_days": total_days,
        "opportunity_days": covered_days,
        "daily_coverage": round(coverage, 8),
        "opportunities": opportunities,
        "opportunities_per_covered_day": round(opportunities / covered_days, 4) if covered_days else 0.0,
    }


def apply_everyday_candidate_gate(
    candidate: dict[str, Any], result: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    if rules.get("research_track") != EVERYDAY_TRACK:
        return result

    train_rows, validation_rows, locked_rows = split_chronologically(rows)
    full_coverage = opportunity_coverage(rows, rules)
    validation_coverage = opportunity_coverage(validation_rows, rules)
    locked_coverage = opportunity_coverage(locked_rows, rules)
    validation_metrics = dict(result.get("metrics", {}).get("validation") or {})
    locked_metrics = dict(result.get("metrics", {}).get("locked_test") or {})

    validation_pf = number(validation_metrics.get("profit_factor"))
    locked_pf = number(locked_metrics.get("profit_factor"))
    validation_exp = number(validation_metrics.get("expectancy_r"))
    locked_exp = number(locked_metrics.get("expectancy_r"))
    validation_trades = int(number(validation_metrics.get("trades")))
    locked_trades = int(number(locked_metrics.get("trades")))
    validation_stability = number(validation_metrics.get("stability"))
    locked_stability = number(locked_metrics.get("stability"))

    target_pass = (
        full_coverage["opportunities"] >= TARGET_FULL_HISTORY_OPPORTUNITIES
        and full_coverage["daily_coverage"] >= TARGET_FULL_DAILY_COVERAGE
        and validation_coverage["daily_coverage"] >= MIN_SEGMENT_DAILY_COVERAGE
        and locked_coverage["daily_coverage"] >= MIN_SEGMENT_DAILY_COVERAGE
        and validation_trades >= 100
        and locked_trades >= 100
        and validation_pf >= TARGET_PF
        and locked_pf >= TARGET_PF
        and validation_exp >= 0.10
        and locked_exp >= 0.10
        and min(validation_stability, locked_stability) >= 0.75
    )
    elite_pass = (
        target_pass
        and validation_pf >= 1.65
        and locked_pf >= 1.65
        and min(validation_coverage["daily_coverage"], locked_coverage["daily_coverage"]) >= 0.65
        and min(validation_stability, locked_stability) >= 0.90
    )
    promising = (
        validation_trades >= 80
        and locked_trades >= 80
        and validation_pf >= 1.25
        and locked_pf >= 1.30
        and validation_exp > 0
        and locked_exp > 0
        and full_coverage["daily_coverage"] >= 0.45
    )

    if elite_pass:
        result["result_status"] = "elite"
    elif target_pass:
        result["result_status"] = "validated"
    elif promising:
        result["result_status"] = "promising"
    else:
        result["result_status"] = "rejected"

    hunt = {
        "track": EVERYDAY_TRACK,
        "target_profit_factor": TARGET_PF,
        "target_full_history_opportunities": TARGET_FULL_HISTORY_OPPORTUNITIES,
        "target_full_daily_coverage": TARGET_FULL_DAILY_COVERAGE,
        "full_history": full_coverage,
        "validation": validation_coverage,
        "locked_test": locked_coverage,
        "target_passed": target_pass,
        "elite_passed": elite_pass,
        "train_rows": len(train_rows),
    }
    result.setdefault("metrics", {})["everyday_hunt"] = hunt
    result.setdefault("evidence", {})["everyday_hunt"] = hunt
    result["evidence"]["summary"] = (
        f"Everyday Hunt: PF validation {validation_pf:.2f}, locked {locked_pf:.2f}; "
        f"full-history opportunities {full_coverage['opportunities']:,}; daily coverage "
        f"{full_coverage['daily_coverage'] * 100:.1f}% (locked {locked_coverage['daily_coverage'] * 100:.1f}%). "
        f"Target {'PASSED' if target_pass else 'not passed'}."
    )
    return result


def apply_everyday_m1_gate(
    candidate: dict[str, Any], result: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    if rules.get("research_track") != EVERYDAY_TRACK:
        return result

    _, validation_rows, locked_rows = split_chronologically(rows)
    full_coverage = opportunity_coverage(rows, rules)
    validation_coverage = opportunity_coverage(validation_rows, rules)
    locked_coverage = opportunity_coverage(locked_rows, rules)
    metrics = dict(result.get("metrics") or {})
    standard = dict(metrics.get("standard_cost") or {})
    elevated = dict(metrics.get("elevated_cost") or {})
    severe = dict(metrics.get("severe_cost") or {})
    validation = dict(standard.get("validation") or {})
    locked = dict(standard.get("locked_test") or {})
    elevated_locked = dict(elevated.get("locked_test") or {})
    severe_locked = dict(severe.get("locked_test") or {})

    reasons: list[str] = []
    checks = (
        (full_coverage["opportunities"] >= TARGET_FULL_HISTORY_OPPORTUNITIES,
         f"Needs at least {TARGET_FULL_HISTORY_OPPORTUNITIES:,} full-history opportunities."),
        (full_coverage["daily_coverage"] >= TARGET_FULL_DAILY_COVERAGE,
         f"Full-history daily coverage must be at least {TARGET_FULL_DAILY_COVERAGE * 100:.0f}%."),
        (validation_coverage["daily_coverage"] >= MIN_SEGMENT_DAILY_COVERAGE,
         f"Validation daily coverage must be at least {MIN_SEGMENT_DAILY_COVERAGE * 100:.0f}%."),
        (locked_coverage["daily_coverage"] >= MIN_SEGMENT_DAILY_COVERAGE,
         f"Locked daily coverage must be at least {MIN_SEGMENT_DAILY_COVERAGE * 100:.0f}%."),
        (int(number(validation.get("trades"))) >= 100 and int(number(locked.get("trades"))) >= 100,
         "Needs at least 100 resolved M1 trades in both validation and locked periods."),
        (number(validation.get("profit_factor")) >= TARGET_PF and number(locked.get("profit_factor")) >= TARGET_PF,
         f"M1 profit factor must be at least {TARGET_PF:.2f} in both validation and locked periods."),
        (number(validation.get("expectancy_r")) >= 0.10 and number(locked.get("expectancy_r")) >= 0.10,
         "M1 expectancy must be at least +0.10R in both validation and locked periods."),
        (number(elevated_locked.get("profit_factor")) >= 1.20 and number(elevated_locked.get("expectancy_r")) > 0,
         "Elevated-cost locked PF must remain at least 1.20 with positive expectancy."),
        (number(severe_locked.get("profit_factor")) >= 1.05 and number(severe_locked.get("expectancy_r")) > 0,
         "Severe-cost locked PF must remain above 1.05 with positive expectancy."),
        (number(result.get("robust_profile_ratio")) >= 75.0,
         "At least 75% of parameter-neighbour profiles must remain profitable."),
        (number(validation.get("year_stability")) >= 1.0 and number(locked.get("year_stability")) >= 1.0,
         "Both M1 chronological periods must remain positive in every represented year."),
        (number(locked.get("max_drawdown_r")) <= max(20.0, int(number(locked.get("trades"))) * 0.15),
         "Locked M1 drawdown is too large for the Everyday Hunt standard."),
    )
    for passed, reason in checks:
        if not passed:
            reasons.append(reason)

    original_ready = result.get("result_status") == "ready_for_mt5_generation"
    everyday_ready = original_ready and not reasons
    if not everyday_ready:
        # Never freeze an Everyday Hunt strategy that misses the stated PF/frequency target.
        result["result_status"] = "replay_validated" if (
            number(validation.get("expectancy_r")) > 0 and number(locked.get("expectancy_r")) > 0
        ) else "rejected"
        result["frozen_rules"] = {}

    hunt = {
        "track": EVERYDAY_TRACK,
        "target_profit_factor": TARGET_PF,
        "full_history": full_coverage,
        "validation": validation_coverage,
        "locked_test": locked_coverage,
        "ready": everyday_ready,
        "reasons": reasons,
    }
    result.setdefault("metrics", {})["everyday_hunt"] = hunt
    result.setdefault("evidence", {})["everyday_hunt"] = hunt
    result["evidence"]["verdict"] = (
        "EVERYDAY BOT TARGET PASSED: PF >= 1.50, broad daily coverage, 1,000+ historical opportunities, "
        "M1 replay, cost stress and robustness all passed. Rules may be frozen for demo MT5 generation."
        if everyday_ready
        else "EVERYDAY BOT TARGET NOT PASSED: the strategy remains research-only and will not be frozen. "
             + " ".join(reasons[:4])
    )
    return result


def apply_everyday_bot_hunt() -> None:
    """Install the dedicated Everyday Bot hunt after queue/diversity patches."""

    if getattr(strategy_lab_module, "_eve_everyday_bot_hunt_applied", False):
        return

    original_generate = strategy_lab_module.generate_candidate_specs
    original_evaluate = strategy_lab_module.evaluate_candidate
    original_m1_evaluate = validation_module.evaluate_high_resolution_candidate

    def generate_with_everyday(source_jobs: list[dict[str, Any]], generation: int) -> list[dict[str, Any]]:
        normal = original_generate(source_jobs, generation)
        everyday = build_everyday_specs(source_jobs, generation)
        merged = {str(item.get("candidate_key")): item for item in normal}
        for item in everyday:
            merged[str(item.get("candidate_key"))] = item
        return list(merged.values())

    def evaluate_with_everyday(candidate: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        result = original_evaluate(candidate, rows)
        return apply_everyday_candidate_gate(candidate, result, rows)

    async def m1_with_everyday(repo, candidate, rows, progress=None):
        result = await original_m1_evaluate(repo, candidate, rows, progress)
        return apply_everyday_m1_gate(candidate, result, rows)

    strategy_lab_module.generate_candidate_specs = generate_with_everyday
    strategy_lab_module.evaluate_candidate = evaluate_with_everyday
    validation_module.evaluate_high_resolution_candidate = m1_with_everyday
    setattr(strategy_lab_module, "_eve_everyday_bot_hunt_applied", True)
