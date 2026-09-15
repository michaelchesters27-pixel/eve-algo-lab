from app.services import mt5_generator
from app.services.strategy_diversity import (
    diversified_candidate_direction,
    diversified_generate_evolution_specs,
    diversified_generate_mq5_source,
    diversified_infer_families,
    diversified_plain_rule_summary,
)
from app.services.strategy_evolution import strategy_seed_to_lineage


def _source(metric: str, effect: float = 10.0, job_key: str = "history-diversity"):
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "job_key": job_key,
        "effect_size": effect,
        "test_definition": {
            "conditions": [{"field": "session", "value": "london"}],
            "metric": metric,
            "horizon_minutes": 30,
        },
    }


def _frozen(direction_rule: str):
    return {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "strategy_code": "EVE-DIVERSE12345",
        "rule_hash": "d" * 64,
        "symbol": "XAU/USD",
        "source_validation_job_id": "223e4567-e89b-12d3-a456-426614174000",
        "source_kind": "strategy",
        "name": "Diversity strategy",
        "family": "trend_reversal",
        "version": "1.0",
        "rules": {
            "source_conditions": [{"field": "hour_utc", "value": 13}],
            "condition_mode": "include",
            "direction_rule": direction_rule,
            "stop_atr": 0.75,
            "target_atr": 2.0,
            "horizon_minutes": 30,
            "cooldown_minutes": 30,
        },
        "validation_metrics": {
            "standard_cost": {
                "locked_test": {
                    "profit_factor": 1.5,
                    "expectancy_r": 0.2,
                    "trades": 120,
                    "max_drawdown_r": 8.0,
                }
            }
        },
        "validation_evidence": {"verdict": "Passed"},
        "status": "ready_for_mt5_generation",
    }


def _lineage():
    seed = {
        "id": "31111111-1111-1111-1111-111111111111",
        "candidate_key": "strategy-diverse-seed",
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "name": "Momentum continuation seed",
        "family": "momentum_continuation",
        "rules": {
            "source_conditions": [{"field": "session", "value": "london"}],
            "condition_mode": "include",
            "direction_rule": "current_direction",
            "horizon_minutes": 30,
            "stop_atr": 1.0,
            "target_atr": 2.0,
            "cooldown_minutes": 30,
            "cost_r": 0.03,
        },
        "result_status": "validated",
        "profit_factor": 1.5,
        "expectancy_r": 0.2,
        "max_drawdown_r": 6.0,
        "trades_total": 150,
        "metrics": {
            "validation": {
                "trades": 80,
                "wins": 40,
                "losses": 40,
                "win_rate": 50,
                "net_r": 16,
                "expectancy_r": 0.2,
                "profit_factor": 1.5,
                "max_drawdown_r": 6,
                "yearly_expectancy": {"2025": 0.2},
                "stability": 1.0,
            }
        },
    }
    lineage = strategy_seed_to_lineage(seed)
    lineage["id"] = "32222222-2222-2222-2222-222222222222"
    return lineage


def test_negative_directional_findings_create_reversal_families():
    assert diversified_infer_families(_source("continuation", -8.0)) == [
        ("momentum_reversal", "inverse_current_direction", "include")
    ]
    assert diversified_infer_families(_source("alignment_follow", -8.0)) == [
        ("alignment_reversal", "inverse_alignment_direction", "include")
    ]


def test_magnitude_research_is_distributed_beyond_momentum_and_alignment():
    families = set()
    for index in range(40):
        families.update(
            family
            for family, _, _ in diversified_infer_families(
                _source("excursion", 12.0, f"job-{index}")
            )
        )
    assert "momentum_continuation" in families
    assert "alignment_continuation" in families
    assert "momentum_reversal" in families
    assert "alignment_reversal" in families
    assert "trend_continuation" in families
    assert "trend_reversal" in families
    assert "streak_continuation" in families
    assert "streak_reversal" in families


def test_new_direction_rules_are_real_opposites_and_independent_signals():
    row = {"direction": 1, "alignment_score": -2, "trend_12_atr": 0.4, "streak": -3}
    assert diversified_candidate_direction(row, "inverse_current_direction") == -1
    assert diversified_candidate_direction(row, "inverse_alignment_direction") == 1
    assert diversified_candidate_direction(row, "trend_direction") == 1
    assert diversified_candidate_direction(row, "inverse_trend_direction") == -1
    assert diversified_candidate_direction(row, "streak_direction") == -1
    assert diversified_candidate_direction(row, "inverse_streak_direction") == 1


def test_evolution_adds_cross_concept_direction_mutation():
    specs = diversified_generate_evolution_specs([_lineage()], generation=1)
    direction_rules = {
        str(item.get("rules", {}).get("direction_rule"))
        for item in specs
        if item.get("mutation_type") == "direction"
    }
    assert "alignment_direction" in direction_rules
    assert "inverse_current_direction" in direction_rules


def test_mt5_generator_supports_diverse_direction_rules_without_weakening_safety():
    frozen = _frozen("inverse_trend_direction")
    source = diversified_generate_mq5_source(frozen)
    assert "return -SignDouble(f.trend_12_atr);" in source
    assert "InpEnableTrading             = false" in source
    assert frozen["rule_hash"] in source
    assert not mt5_generator.static_validate_mq5(source, frozen)
    assert "fade the short-term trend" in diversified_plain_rule_summary(frozen["rules"])
