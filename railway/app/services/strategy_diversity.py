from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from app.services import demo_eligibility as demo_eligibility_module
from app.services import mt5_generator as mt5_generator_module
from app.services import strategy_evolution as strategy_evolution_module
from app.services import strategy_lab as strategy_lab_module
from app.services.autonomy import number


# This compatibility layer deliberately broadens strategy *concepts* without
# weakening any of EVE's existing chronological, M1, cost-stress or robustness
# gates. It is installed before app.main creates the workers.

DIRECTION_SUMMARIES = {
    "inverse_current_direction": "fade the current M5 candle direction",
    "inverse_alignment_direction": "trade against multi-timeframe alignment",
    "trend_direction": "follow the short-term trend",
    "inverse_trend_direction": "fade the short-term trend",
    "streak_direction": "follow the current candle streak",
    "inverse_streak_direction": "fade the current candle streak",
}

MQL_DIRECTION_CODE = {
    "inverse_current_direction": "return -f.direction;",
    "inverse_alignment_direction": "return -SignInt(f.alignment_score);",
    "trend_direction": "return SignDouble(f.trend_12_atr);",
    "inverse_trend_direction": "return -SignDouble(f.trend_12_atr);",
    "streak_direction": "return SignInt(f.streak);",
    "inverse_streak_direction": "return -SignInt(f.streak);",
}

DIRECTION_MUTATION_OPTIONS = {
    "current_direction": ("inverse_current_direction", "trend_direction", "streak_direction"),
    "alignment_direction": ("inverse_alignment_direction", "trend_direction", "streak_direction"),
    "fixed_long": ("trend_direction", "current_direction", "inverse_current_direction"),
    "fixed_short": ("trend_direction", "current_direction", "inverse_current_direction"),
    "inverse_current_direction": ("current_direction", "inverse_alignment_direction", "inverse_trend_direction"),
    "inverse_alignment_direction": ("alignment_direction", "inverse_current_direction", "inverse_trend_direction"),
    "trend_direction": ("inverse_trend_direction", "current_direction", "alignment_direction"),
    "inverse_trend_direction": ("trend_direction", "inverse_current_direction", "inverse_alignment_direction"),
    "streak_direction": ("inverse_streak_direction", "current_direction", "trend_direction"),
    "inverse_streak_direction": ("streak_direction", "inverse_current_direction", "inverse_trend_direction"),
}


_original_candidate_direction = strategy_lab_module.candidate_direction
_original_generate_evolution_specs = strategy_evolution_module.generate_evolution_specs
_original_generate_mq5_source = mt5_generator_module.generate_mq5_source
_original_plain_rule_summary = demo_eligibility_module.plain_rule_summary
_original_snapshot_context = demo_eligibility_module.snapshot_context
_original_direction_is_ready = demo_eligibility_module.direction_is_ready


def _sign(value: Any) -> int:
    parsed = number(value)
    return 1 if parsed > 0 else -1 if parsed < 0 else 0


def diversified_infer_families(source: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Route research into a wider set of genuinely different trade directions.

    Existing directional research keeps a natural interpretation, including true
    reversal families when continuation/alignment evidence is negative. Research
    that only proves a context changes movement size is distributed deterministically
    across four concept pairs, preventing the factory from funnelling nearly every
    useful context back into momentum/alignment continuation.
    """

    definition = dict(source.get("test_definition") or {})
    metric = str(definition.get("metric") or "excursion")
    effect = number(source.get("effect_size"))
    positive = effect >= 0

    if metric in {"continuation", "same_direction"}:
        if positive:
            return [("momentum_continuation", "current_direction", "include")]
        return [("momentum_reversal", "inverse_current_direction", "include")]

    if metric == "alignment_follow":
        if positive:
            return [("alignment_continuation", "alignment_direction", "include")]
        return [("alignment_reversal", "inverse_alignment_direction", "include")]

    if metric == "up_probability":
        return [("directional_bias", "fixed_long" if positive else "fixed_short", "include")]

    condition_mode = "include" if positive else "exclude"
    portfolios = (
        (
            ("momentum_continuation", "current_direction", condition_mode),
            ("alignment_continuation", "alignment_direction", condition_mode),
        ),
        (
            ("momentum_reversal", "inverse_current_direction", condition_mode),
            ("alignment_reversal", "inverse_alignment_direction", condition_mode),
        ),
        (
            ("trend_continuation", "trend_direction", condition_mode),
            ("trend_reversal", "inverse_trend_direction", condition_mode),
        ),
        (
            ("streak_continuation", "streak_direction", condition_mode),
            ("streak_reversal", "inverse_streak_direction", condition_mode),
        ),
    )
    identity = str(source.get("job_key") or source.get("id") or source.get("question") or "")
    bucket = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16) % len(portfolios)
    return list(portfolios[bucket])


def diversified_candidate_direction(row: dict[str, Any], rule: str) -> int:
    if rule == "inverse_current_direction":
        return -_sign(row.get("direction"))
    if rule == "inverse_alignment_direction":
        return -_sign(row.get("alignment_score"))
    if rule == "trend_direction":
        return _sign(row.get("trend_12_atr"))
    if rule == "inverse_trend_direction":
        return -_sign(row.get("trend_12_atr"))
    if rule == "streak_direction":
        return _sign(row.get("streak"))
    if rule == "inverse_streak_direction":
        return -_sign(row.get("streak"))
    return _original_candidate_direction(row, rule)


def diversified_generate_evolution_specs(
    lineages: list[dict[str, Any]], generation: int
) -> list[dict[str, Any]]:
    """Keep normal mutations, plus one controlled cross-concept direction mutation."""

    original = _original_generate_evolution_specs(lineages, generation)
    specs = {str(item.get("child_key")): item for item in original}
    active = [item for item in lineages if item.get("status") == "active" and item.get("champion_rules")]
    active = active[: strategy_evolution_module.MAX_ACTIVE_LINEAGES]

    for index, lineage in enumerate(active):
        parent_rules = dict(lineage.get("champion_rules") or {})
        direction = str(parent_rules.get("direction_rule") or "current_direction")
        alternatives = DIRECTION_MUTATION_OPTIONS.get(direction) or ()
        if not alternatives:
            continue
        alternative = alternatives[(max(1, generation) - 1 + index) % len(alternatives)]
        rules = {
            **parent_rules,
            "direction_rule": alternative,
            "engine_version": strategy_evolution_module.EVOLUTION_ENGINE_VERSION,
        }
        child = strategy_evolution_module._child_spec(
            lineage,
            generation,
            "direction",
            rules,
            {"direction_rule": f"{direction} → {alternative}", "diversity_expansion": True},
        )
        specs[str(child.get("child_key"))] = child

    return list(specs.values())


def diversified_generate_mq5_source(frozen: dict[str, Any]) -> str:
    """Generate parity-safe MQ5 for the additional direction rules."""

    rules = dict(frozen.get("rules") or {})
    direction_rule = str(rules.get("direction_rule") or "current_direction")
    replacement = MQL_DIRECTION_CODE.get(direction_rule)
    if replacement is None:
        return _original_generate_mq5_source(frozen)

    proxy = deepcopy(frozen)
    proxy_rules = dict(proxy.get("rules") or {})
    proxy_rules["direction_rule"] = "current_direction"
    proxy["rules"] = proxy_rules
    source = _original_generate_mq5_source(proxy)
    marker = "return f.direction;"
    if marker not in source:
        raise ValueError("MT5 generator direction marker not found for diversity rule")
    return source.replace(marker, replacement, 1)


def diversified_snapshot_context(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    fields = _original_snapshot_context(snapshot)
    row = dict(snapshot or {})
    fields["trend_12_atr"] = number(row.get("trend_12_atr"))
    fields["streak"] = int(number(row.get("streak")))
    return fields


def diversified_direction_is_ready(direction_rule: str, fields: dict[str, Any]) -> bool:
    if direction_rule == "inverse_current_direction":
        return int(number(fields.get("direction"))) != 0
    if direction_rule == "inverse_alignment_direction":
        return int(number(fields.get("alignment_score"))) != 0
    if direction_rule in {"trend_direction", "inverse_trend_direction"}:
        return abs(number(fields.get("trend_12_atr"))) > 1e-12
    if direction_rule in {"streak_direction", "inverse_streak_direction"}:
        return int(number(fields.get("streak"))) != 0
    return _original_direction_is_ready(direction_rule, fields)


def diversified_plain_rule_summary(rules: dict[str, Any]) -> str:
    summary = _original_plain_rule_summary(rules)
    direction_rule = str(rules.get("direction_rule") or "current_direction")
    description = DIRECTION_SUMMARIES.get(direction_rule)
    if description:
        summary = summary.replace("use the frozen direction rule.", f"{description}.")
    return summary


def apply_strategy_diversity() -> None:
    """Install broader strategy directions before worker construction."""

    if getattr(strategy_lab_module, "_eve_strategy_diversity_applied", False):
        return

    strategy_lab_module.infer_families = diversified_infer_families
    strategy_lab_module.candidate_direction = diversified_candidate_direction
    strategy_evolution_module.generate_evolution_specs = diversified_generate_evolution_specs

    demo_eligibility_module.snapshot_context = diversified_snapshot_context
    demo_eligibility_module.direction_is_ready = diversified_direction_is_ready
    demo_eligibility_module.plain_rule_summary = diversified_plain_rule_summary

    mt5_generator_module.generate_mq5_source = diversified_generate_mq5_source
    # mt5_generator imports this symbol directly, so keep its manifest text in sync.
    mt5_generator_module.plain_rule_summary = diversified_plain_rule_summary

    setattr(strategy_lab_module, "_eve_strategy_diversity_applied", True)
