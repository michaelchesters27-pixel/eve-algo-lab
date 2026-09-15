from datetime import datetime, timedelta, timezone

from app.services.everyday_bot_hunt import (
    EVERYDAY_TRACK,
    TARGET_FULL_HISTORY_OPPORTUNITIES,
    apply_everyday_candidate_gate,
    apply_everyday_m1_gate,
    broadened_condition_sets,
    build_everyday_specs,
    opportunity_coverage,
)


def _source():
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "job_key": "daily-source",
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "result_status": "validated",
        "confidence_score": 90,
        "effect_size": 8.0,
        "question": "Does Tuesday at 13:00 in a down trend show continuation?",
        "test_definition": {
            "metric": "same_direction",
            "horizon_minutes": 30,
            "conditions": [
                {"field": "weekday", "value": 2},
                {"field": "hour_utc", "value": 13},
                {"field": "trend_band", "value": "down"},
            ],
        },
    }


def _rules():
    return {
        "research_track": EVERYDAY_TRACK,
        "source_conditions": [],
        "condition_mode": "include",
        "direction_rule": "current_direction",
        "horizon_minutes": 15,
        "cooldown_minutes": 15,
        "stop_atr": 1.0,
        "target_atr": 2.0,
        "cost_r": 0.03,
    }


def _rows():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = []
    # 120 trading dates x 10 opportunities = 1,200 full-history opportunities.
    for day in range(120):
        date = start + timedelta(days=day)
        for slot in range(10):
            rows.append({
                "candle_time": (date + timedelta(minutes=15 * slot)).isoformat(),
                "direction": 1,
                "alignment_score": 1,
                "trend_12_atr": 0.2,
                "streak": 1,
                "atr_14": 10.0,
            })
    return rows


def test_broadening_removes_calendar_and_can_remove_exact_hour():
    variants = broadened_condition_sets(_source()["test_definition"]["conditions"])
    assert variants[0] == (
        "daily_window",
        [{"field": "hour_utc", "value": 13}, {"field": "trend_band", "value": "down"}],
    )
    assert variants[1] == ("daily_broad", [{"field": "trend_band", "value": "down"}])


def test_everyday_specs_are_explicitly_tagged_and_not_calendar_specialised():
    specs = build_everyday_specs([_source()], generation=1)
    assert specs
    assert all(item["rules"]["research_track"] == EVERYDAY_TRACK for item in specs)
    assert all(item["family"].startswith("everyday_") for item in specs)
    for item in specs:
        fields = {condition["field"] for condition in item["rules"]["source_conditions"]}
        assert "weekday" not in fields
        assert "month" not in fields
        assert "quarter" not in fields
        assert "week_of_month" not in fields


def test_opportunity_coverage_counts_broad_daily_activity():
    coverage = opportunity_coverage(_rows(), _rules())
    assert coverage["opportunities"] == 1200
    assert coverage["opportunity_days"] == 120
    assert coverage["daily_coverage"] == 1.0


def test_candidate_gate_requires_pf_1_5_and_1000_plus_opportunities():
    candidate = {"rules": _rules()}
    good = {
        "result_status": "validated",
        "metrics": {
            "validation": {"trades": 180, "profit_factor": 1.58, "expectancy_r": 0.18, "stability": 1.0},
            "locked_test": {"trades": 180, "profit_factor": 1.57, "expectancy_r": 0.17, "stability": 1.0},
        },
        "evidence": {},
    }
    passed = apply_everyday_candidate_gate(candidate, good, _rows())
    assert passed["result_status"] == "validated"
    assert passed["metrics"]["everyday_hunt"]["target_passed"] is True
    assert passed["metrics"]["everyday_hunt"]["full_history"]["opportunities"] >= TARGET_FULL_HISTORY_OPPORTUNITIES

    weak_pf = {
        "result_status": "validated",
        "metrics": {
            "validation": {"trades": 180, "profit_factor": 1.49, "expectancy_r": 0.18, "stability": 1.0},
            "locked_test": {"trades": 180, "profit_factor": 1.60, "expectancy_r": 0.17, "stability": 1.0},
        },
        "evidence": {},
    }
    failed = apply_everyday_candidate_gate(candidate, weak_pf, _rows())
    assert failed["result_status"] != "validated"
    assert failed["metrics"]["everyday_hunt"]["target_passed"] is False


def test_m1_gate_refuses_to_freeze_if_everyday_target_is_missed():
    candidate = {"rules": _rules()}
    base_result = {
        "result_status": "ready_for_mt5_generation",
        "frozen_rules": _rules(),
        "profit_factor": 1.60,
        "expectancy_r": 0.20,
        "robust_profile_ratio": 100.0,
        "metrics": {
            "standard_cost": {
                "validation": {"trades": 180, "profit_factor": 1.60, "expectancy_r": 0.20, "year_stability": 1.0},
                "locked_test": {"trades": 180, "profit_factor": 1.55, "expectancy_r": 0.18, "year_stability": 1.0, "max_drawdown_r": 10.0},
            },
            "elevated_cost": {"locked_test": {"profit_factor": 1.30, "expectancy_r": 0.10}},
            "severe_cost": {"locked_test": {"profit_factor": 1.10, "expectancy_r": 0.05}},
        },
        "evidence": {},
    }
    passed = apply_everyday_m1_gate(candidate, base_result, _rows())
    assert passed["result_status"] == "ready_for_mt5_generation"
    assert passed["metrics"]["everyday_hunt"]["ready"] is True

    miss = {
        **base_result,
        "frozen_rules": _rules(),
        "metrics": {
            **base_result["metrics"],
            "standard_cost": {
                "validation": {"trades": 180, "profit_factor": 1.60, "expectancy_r": 0.20, "year_stability": 1.0},
                "locked_test": {"trades": 180, "profit_factor": 1.49, "expectancy_r": 0.18, "year_stability": 1.0, "max_drawdown_r": 10.0},
            },
        },
        "evidence": {},
        "result_status": "ready_for_mt5_generation",
    }
    rejected_for_freeze = apply_everyday_m1_gate(candidate, miss, _rows())
    assert rejected_for_freeze["result_status"] != "ready_for_mt5_generation"
    assert rejected_for_freeze["frozen_rules"] == {}
    assert rejected_for_freeze["metrics"]["everyday_hunt"]["ready"] is False
