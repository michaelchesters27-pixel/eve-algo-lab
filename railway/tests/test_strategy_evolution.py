from datetime import datetime, timedelta, timezone

from app.services.strategy_evolution import (
    evaluate_evolution_candidate,
    generate_evolution_specs,
    merge_conditions,
    strategy_seed_to_lineage,
)


def seed_candidate():
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "candidate_key": "strategy-seed",
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "name": "Alignment Continuation Seed",
        "family": "alignment_continuation",
        "rules": {
            "source_conditions": [{"field": "direction", "value": 1}],
            "condition_mode": "include",
            "direction_rule": "current_direction",
            "horizon_minutes": 60,
            "stop_atr": 0.75,
            "target_atr": 3.0,
            "cooldown_minutes": 15,
            "cost_r": 0.03,
        },
        "result_status": "validated",
        "profit_factor": 1.4,
        "expectancy_r": 0.1,
        "max_drawdown_r": 5.0,
        "trades_total": 150,
        "metrics": {
            "validation": {
                "trades": 80, "wins": 44, "losses": 36, "win_rate": 55,
                "net_r": 8, "expectancy_r": 0.1, "profit_factor": 1.3,
                "max_drawdown_r": 4, "yearly_expectancy": {"2024": 0.1}, "stability": 1.0,
            }
        },
    }


def make_lineage(seed=None):
    lineage = strategy_seed_to_lineage(seed or seed_candidate())
    lineage["id"] = "22222222-2222-2222-2222-222222222222"
    return lineage


def make_rows(count=4000, fail_locked=False):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    locked_start = int(count * 0.85)
    rows = []
    for index in range(count):
        bullish = index % 3 == 0
        locked_failure = fail_locked and index >= locked_start and bullish
        rows.append({
            "candle_time": (start + timedelta(minutes=15 * index)).isoformat(),
            "close": 2000.0,
            "atr_14": 10.0,
            "direction": 1 if bullish else -1,
            "alignment_score": 1 if bullish else -1,
            "outcomes": {
                "60": {
                    "close_return_pct": 0.30 if bullish else -0.10,
                    "max_up_atr": 2.0 if bullish and not locked_failure else 0.1,
                    "max_down_atr": 2.0 if locked_failure else 0.2,
                    "direction": "down" if locked_failure else "up",
                }
            },
        })
    return rows


def target_child(lineage):
    rules = dict(lineage["champion_rules"])
    rules["target_atr"] = 1.5
    return {
        "id": "33333333-3333-3333-3333-333333333333",
        "lineage_id": lineage["id"],
        "generation": 1,
        "mutation_type": "target",
        "name": "Target mutation",
        "hypothesis": "Lower target may capture the observed move.",
        "parent_rules": lineage["champion_rules"],
        "rules": rules,
        "changes": {"target_atr": "3.00 → 1.50"},
    }


def test_merge_conditions_rejects_conflicts_and_deduplicates():
    first = [{"field": "weekday", "value": 1}]
    assert merge_conditions(first, [{"field": "weekday", "value": 2}]) is None
    merged = merge_conditions(first, [{"field": "session", "value": "london"}, {"field": "weekday", "value": 1}])
    assert merged == [{"field": "session", "value": "london"}, {"field": "weekday", "value": 1}]


def test_generate_evolution_specs_are_unique_and_controlled():
    first = make_lineage()
    second_seed = seed_candidate()
    second_seed["id"] = "44444444-4444-4444-4444-444444444444"
    second_seed["candidate_key"] = "strategy-session"
    second_seed["name"] = "London Alignment"
    second_seed["rules"] = {**second_seed["rules"], "source_conditions": [{"field": "session", "value": "london"}]}
    second = make_lineage(second_seed)
    second["id"] = "55555555-5555-5555-5555-555555555555"

    specs = generate_evolution_specs([first, second], generation=1)
    assert specs
    assert len({item["child_key"] for item in specs}) == len(specs)
    assert any(item["mutation_type"] == "combination" for item in specs)
    for item in specs:
        assert item["parent_rules"]
        assert item["rules"]
        assert item["changes"]
        assert item["selection_config"]["selection_period"] == "validation only"
        assert item["status"] == "queued"


def test_evolution_promotes_validation_improvement_and_audits_locked_data():
    lineage = make_lineage()
    evaluation = evaluate_evolution_candidate(target_child(lineage), make_rows())
    result = evaluation.result
    assert result["selection_passed"] is True
    assert evaluation.promote_for_next_generation is True
    assert result["validation_improvement"] > 0
    assert result["profit_factor"] >= 1.05
    assert result["result_status"] in {"champion", "elite"}
    assert result["parent_comparison"]["selection_used_locked_test"] is False


def test_locked_catastrophe_is_safety_veto_not_parameter_selection():
    lineage = make_lineage()
    evaluation = evaluate_evolution_candidate(target_child(lineage), make_rows(fail_locked=True))
    result = evaluation.result
    assert result["selection_passed"] is True
    assert result["parent_comparison"]["selection_used_locked_test"] is False
    assert result["parent_comparison"]["catastrophic_locked_failure"] is True
    assert evaluation.promote_for_next_generation is False
    assert result["result_status"] == "rejected"
