from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.four_ccb_bias_research import BiasMethod, FourCCBH1BiasDiscovery
from app.four_ccb_research import _metrics, _profit_factor_for_sort

ENGINE_VERSION = "0.3.0"
STRATEGY_CODE = "four_ccb_h1_structure_discovery_v0_3"

Mode = Literal["plain", "reversal", "continuation"]
Confirmation = Literal["touch", "close"]
Structure = Literal[
    "overlap_only",
    "mother_bar",
    "progressive_inside",
    "body_overlap",
    "alternating_colours",
    "two_bull_two_bear",
    "contracting_ranges",
    "converging_range",
    "small_bodies",
    "body_overlap_alternating",
    "mother_bar_small_bodies",
]

STRUCTURES: tuple[Structure, ...] = (
    "overlap_only",
    "mother_bar",
    "progressive_inside",
    "body_overlap",
    "alternating_colours",
    "two_bull_two_bear",
    "contracting_ranges",
    "converging_range",
    "small_bodies",
    "body_overlap_alternating",
    "mother_bar_small_bodies",
)

BIAS_METHODS: tuple[BiasMethod, ...] = (
    "momentum_24h",
    "momentum_72h",
    "ema_20_50",
    "range_mid_20",
)


@dataclass(frozen=True)
class StructureVariant:
    structure: Structure
    box_atr_max: float
    mode: Mode
    impulse_atr_min: float
    reward_risk: float
    confirmation: Confirmation
    bias_method: BiasMethod

    def as_dict(self) -> dict[str, Any]:
        return {
            "structure": self.structure,
            "structure_rule": {
                "overlap_only": "baseline 4-candle common-overlap rule",
                "mother_bar": "candles 2-4 must stay fully inside candle 1 high-low",
                "progressive_inside": "each later candle must be fully inside the immediately previous candle",
                "body_overlap": "all four candle bodies must share a common price overlap of at least 8% of the full box range",
                "alternating_colours": "four non-doji bodies must alternate bullish/bearish colour",
                "two_bull_two_bear": "the four candles must contain exactly two bullish and two bearish bodies",
                "contracting_ranges": "ranges must contract with no step expanding more than 10%, and candle 4 range <= 80% of candle 1",
                "converging_range": "at least two of three highs step lower/equal and at least two of three lows step higher/equal, with candle 4 <= 75% of full box range",
                "small_bodies": "average body/range <= 45% and at least three candles have body/range <= 55%",
                "body_overlap_alternating": "body-overlap rule plus strict alternating candle colours",
                "mother_bar_small_bodies": "mother-bar rule plus the small-body rule",
            }[self.structure],
            "box_candles": 4,
            "common_overlap_min_fraction": 0.10,
            "box_atr_max": self.box_atr_max,
            "mode": self.mode,
            "impulse_lookback_h1": 3,
            "impulse_atr_min": self.impulse_atr_min if self.mode != "plain" else None,
            "reward_risk": self.reward_risk,
            "confirmation": self.confirmation,
            "bias_method": self.bias_method,
            "bias_rule": {
                "momentum_24h": "trade only in direction of last completed H1 close versus close 24 H1 bars earlier",
                "momentum_72h": "trade only in direction of last completed H1 close versus close 72 H1 bars earlier",
                "ema_20_50": "trade only with causal H1 EMA20 above/below EMA50 at the box start",
                "range_mid_20": "trade only with last completed H1 close above/below midpoint of previous 20 H1 high-low range",
            }[self.bias_method],
            "breakout_wait_h1": 4,
            "maximum_hold_h1": 24,
            "stop": "opposite side of the four-candle box",
        }


class FourCCBH1StructureDiscovery(FourCCBH1BiasDiscovery):
    """Third 4CCB experiment: infer what may qualify the four highlighted H1 candles.

    Stage 1 screens a deliberately small set of visible candle-relationship hypotheses.
    Stage 2 tunes only the four strongest structure families on the first half of history.
    Stage 3 selects one frozen rule on the next chronological quarter and reports the
    final quarter separately as confirmation. The late period is not described as a
    pristine holdout because earlier 4CCB experiments have already inspected it.
    """

    @staticmethod
    def _colour(candle: Any) -> int:
        if candle.close > candle.open:
            return 1
        if candle.close < candle.open:
            return -1
        return 0

    @staticmethod
    def _body_ratio(candle: Any) -> float:
        full_range = candle.high - candle.low
        if full_range <= 0:
            return 0.0
        return abs(candle.close - candle.open) / full_range

    def _structure_pass(self, index: int, structure: Structure, box_high: float, box_low: float) -> bool:
        group = self.candles[index:index + 4]
        if len(group) < 4:
            return False
        box_range = box_high - box_low
        if box_range <= 0:
            return False

        def mother_bar() -> bool:
            first = group[0]
            return all(c.high <= first.high and c.low >= first.low for c in group[1:])

        def progressive_inside() -> bool:
            return all(
                group[pos].high <= group[pos - 1].high and group[pos].low >= group[pos - 1].low
                for pos in range(1, 4)
            )

        def body_overlap() -> bool:
            common_high = min(max(c.open, c.close) for c in group)
            common_low = max(min(c.open, c.close) for c in group)
            overlap = max(0.0, common_high - common_low)
            return overlap / box_range >= 0.08

        def alternating_colours() -> bool:
            colours = [self._colour(c) for c in group]
            return all(colour != 0 for colour in colours) and all(
                colours[pos] != colours[pos - 1] for pos in range(1, 4)
            )

        def two_bull_two_bear() -> bool:
            colours = [self._colour(c) for c in group]
            return colours.count(1) == 2 and colours.count(-1) == 2

        def contracting_ranges() -> bool:
            ranges = [c.high - c.low for c in group]
            if any(value <= 0 for value in ranges):
                return False
            gentle_contraction = all(ranges[pos] <= ranges[pos - 1] * 1.10 for pos in range(1, 4))
            return gentle_contraction and ranges[-1] <= ranges[0] * 0.80

        def converging_range() -> bool:
            high_steps = sum(group[pos].high <= group[pos - 1].high for pos in range(1, 4))
            low_steps = sum(group[pos].low >= group[pos - 1].low for pos in range(1, 4))
            last_range = group[-1].high - group[-1].low
            return high_steps >= 2 and low_steps >= 2 and last_range <= box_range * 0.75

        def small_bodies() -> bool:
            ratios = [self._body_ratio(c) for c in group]
            return sum(ratios) / 4.0 <= 0.45 and sum(value <= 0.55 for value in ratios) >= 3

        if structure == "overlap_only":
            return True
        if structure == "mother_bar":
            return mother_bar()
        if structure == "progressive_inside":
            return progressive_inside()
        if structure == "body_overlap":
            return body_overlap()
        if structure == "alternating_colours":
            return alternating_colours()
        if structure == "two_bull_two_bear":
            return two_bull_two_bear()
        if structure == "contracting_ranges":
            return contracting_ranges()
        if structure == "converging_range":
            return converging_range()
        if structure == "small_bodies":
            return small_bodies()
        if structure == "body_overlap_alternating":
            return body_overlap() and alternating_colours()
        if structure == "mother_bar_small_bodies":
            return mother_bar() and small_bodies()
        return False

    def _qualified_box(self, index: int, atr: float, variant: StructureVariant) -> tuple[float, float] | None:
        box = self._box(index, atr, variant.box_atr_max)
        if box is None:
            return None
        box_high, box_low = box
        if not self._structure_pass(index, variant.structure, box_high, box_low):
            return None
        return box_high, box_low

    def run_variant(self, variant: StructureVariant, start: int, end: int) -> dict[str, Any]:
        pnls: list[float] = []
        setups = 0
        ambiguous = 0
        time_exits = 0
        bias_filtered = 0
        index = max(start, self.atr_period, self.impulse_lookback, 73)

        while index + 4 < end:
            atr = self._atr_before(index)
            box = self._qualified_box(index, atr, variant)
            if box is None:
                index += 1
                continue
            box_high, box_low = box

            bias_direction = self._bias_direction(index, variant.bias_method)
            if bias_direction == 0:
                index += 1
                continue

            impulse_direction = 0
            if variant.mode != "plain":
                impulse_direction = self._impulse_direction(index, atr, variant.impulse_atr_min)
                if impulse_direction == 0:
                    index += 1
                    continue

            setups += 1
            breakout = self._find_breakout(
                index + 4,
                end,
                box_high,
                box_low,
                variant,
                impulse_direction,
            )
            if breakout is None:
                index += 1
                continue

            breakout_index, side, entry = breakout
            if side == "ambiguous":
                ambiguous += 1
                index = breakout_index + 1
                continue
            if side == "invalidated" or entry is None:
                index = breakout_index + 1
                continue
            if not self._side_matches_bias(side, bias_direction):
                bias_filtered += 1
                index = breakout_index + 1
                continue

            trade = self._simulate_trade(
                breakout_index,
                end,
                side,
                float(entry),
                box_high,
                box_low,
                variant.reward_risk,
            )
            if trade is None:
                index = breakout_index + 1
                continue

            exit_index, pnl_r, timed_out = trade
            pnls.append(pnl_r)
            if timed_out:
                time_exits += 1
            index = max(index + 1, exit_index + 1)

        result = variant.as_dict()
        result["metrics"] = _metrics(pnls, setups, ambiguous, time_exits)
        result["metrics"]["counter_bias_breakouts_filtered"] = bias_filtered
        return result

    @staticmethod
    def screen_variants() -> list[StructureVariant]:
        # Screen structures with one representative execution per context family, derived
        # from the broad v0.2 development leaders rather than tuning every parameter at once.
        mode_specs: tuple[tuple[Mode, float, float], ...] = (
            ("plain", 0.0, 2.0),
            ("reversal", 1.25, 1.5),
            ("continuation", 1.25, 1.0),
        )
        result: list[StructureVariant] = []
        for structure in STRUCTURES:
            for bias_method in BIAS_METHODS:
                for mode, impulse_atr_min, reward_risk in mode_specs:
                    result.append(
                        StructureVariant(
                            structure=structure,
                            box_atr_max=1.5,
                            mode=mode,
                            impulse_atr_min=impulse_atr_min,
                            reward_risk=reward_risk,
                            confirmation="touch",
                            bias_method=bias_method,
                        )
                    )
        return result

    @staticmethod
    def tune_variants(structures: list[Structure]) -> list[StructureVariant]:
        result: list[StructureVariant] = []
        for structure in structures:
            for bias_method in BIAS_METHODS:
                for box_atr_max in (1.0, 1.25, 1.5):
                    for reward_risk in (1.0, 1.5, 2.0):
                        for confirmation in ("touch", "close"):
                            result.append(
                                StructureVariant(
                                    structure=structure,
                                    box_atr_max=box_atr_max,
                                    mode="plain",
                                    impulse_atr_min=0.0,
                                    reward_risk=reward_risk,
                                    confirmation=confirmation,
                                    bias_method=bias_method,
                                )
                            )
                            for mode in ("reversal", "continuation"):
                                for impulse_atr_min in (0.75, 1.0, 1.25):
                                    result.append(
                                        StructureVariant(
                                            structure=structure,
                                            box_atr_max=box_atr_max,
                                            mode=mode,
                                            impulse_atr_min=impulse_atr_min,
                                            reward_risk=reward_risk,
                                            confirmation=confirmation,
                                            bias_method=bias_method,
                                        )
                                    )
        return result

    @staticmethod
    def _rank_key(result: dict[str, Any]) -> tuple[float, float, float, int]:
        metrics = result["metrics"]
        return (
            float(metrics["selection_score"]),
            float(metrics["expectancy_r"]),
            _profit_factor_for_sort(metrics),
            int(metrics["trades"]),
        )

    @staticmethod
    def _variant_from_result(result: dict[str, Any]) -> StructureVariant:
        return StructureVariant(
            structure=str(result["structure"]),
            box_atr_max=float(result["box_atr_max"]),
            mode=str(result["mode"]),
            impulse_atr_min=float(result["impulse_atr_min"] or 0.0),
            reward_risk=float(result["reward_risk"]),
            confirmation=str(result["confirmation"]),
            bias_method=str(result["bias_method"]),
        )

    @staticmethod
    def _variant_key(result: dict[str, Any]) -> tuple[Any, ...]:
        return (
            result["structure"],
            float(result["box_atr_max"]),
            result["mode"],
            float(result["impulse_atr_min"] or 0.0),
            float(result["reward_risk"]),
            result["confirmation"],
            result["bias_method"],
        )

    def _structure_leaders(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        leaders: list[dict[str, Any]] = []
        for structure in STRUCTURES:
            family = [item for item in items if item["structure"] == structure and item["metrics"]["trades"] >= 30]
            if not family:
                family = [item for item in items if item["structure"] == structure and item["metrics"]["trades"] >= 15]
            if not family:
                continue
            best = max(family, key=self._rank_key)
            leaders.append(best)
        return sorted(leaders, key=self._rank_key, reverse=True)

    def run(self) -> dict[str, Any]:
        n = len(self.candles)
        if n < 1000:
            raise RuntimeError("At least 1,000 stored H1 candles are required for 4CCB structure discovery")

        split_development = int(n * 0.50)
        split_validation = int(n * 0.75)

        screen_variants = self.screen_variants()
        screen_results = [self.run_variant(variant, 0, split_development) for variant in screen_variants]
        structure_leaders = self._structure_leaders(screen_results)
        if not structure_leaders:
            raise RuntimeError("No 4CCB structure family produced enough development trades to continue")

        selected_structures: list[Structure] = [str(item["structure"]) for item in structure_leaders[:4]]
        tune_variants = self.tune_variants(selected_structures)
        development = [self.run_variant(variant, 0, split_development) for variant in tune_variants]
        eligible = [item for item in development if item["metrics"]["trades"] >= 30]
        if not eligible:
            eligible = [item for item in development if item["metrics"]["trades"] >= 15]
        if not eligible:
            eligible = development
        ranked_development = sorted(eligible, key=self._rank_key, reverse=True)

        candidate_development = ranked_development[:30]
        candidate_variants = [self._variant_from_result(item) for item in candidate_development]
        validation = [self.run_variant(variant, split_development, split_validation) for variant in candidate_variants]
        validation_eligible = [item for item in validation if item["metrics"]["trades"] >= 15]
        if not validation_eligible:
            validation_eligible = [item for item in validation if item["metrics"]["trades"] >= 8]
        if not validation_eligible:
            validation_eligible = validation
        champion_validation = max(validation_eligible, key=self._rank_key)
        champion_variant = self._variant_from_result(champion_validation)

        dev_metrics_by_key = {self._variant_key(item): item["metrics"] for item in development}
        champion_key = self._variant_key(champion_validation)
        champion_development_metrics = dev_metrics_by_key.get(champion_key, {})

        confirmation = self.run_variant(champion_variant, split_validation, n)
        full = self.run_variant(champion_variant, 0, n)
        validation_metrics = champion_validation["metrics"]
        confirmation_metrics = confirmation["metrics"]
        validation_pf = validation_metrics["profit_factor"]
        confirmation_pf = confirmation_metrics["profit_factor"]

        robust_pass = (
            validation_metrics["trades"] >= 15
            and confirmation_metrics["trades"] >= 15
            and validation_metrics["expectancy_r"] > 0
            and confirmation_metrics["expectancy_r"] > 0
            and validation_pf is not None
            and confirmation_pf is not None
            and validation_pf >= 1.10
            and confirmation_pf >= 1.10
            and validation_metrics["net_r"] > 0
            and confirmation_metrics["net_r"] > 0
        )

        return {
            "engine_version": ENGINE_VERSION,
            "strategy_code": STRATEGY_CODE,
            "research_question": "Which visible four-candle relationship best explains a useful H1 4CCB setup when combined with causal directional bias?",
            "important_note": (
                "These are reverse-engineered candle-relationship hypotheses based on public chart appearance. "
                "They do not claim to reproduce any private/VIP rules. Because earlier 4CCB experiments already inspected late history, "
                "the final quarter is chronological confirmation, not a pristine untouched holdout."
            ),
            "data": {
                "h1_candles": n,
                "first_candle": self.candles[0].candle_time.isoformat(),
                "last_candle": self.candles[-1].candle_time.isoformat(),
                "development_end_exclusive": self.candles[split_development].candle_time.isoformat(),
                "validation_end_exclusive": self.candles[split_validation].candle_time.isoformat(),
                "development_candles": split_development,
                "validation_candles": split_validation - split_development,
                "confirmation_candles": n - split_validation,
            },
            "method": {
                "structures_screened": list(STRUCTURES),
                "screen_variant_count": len(screen_variants),
                "screening": "first 50% of history; 11 structure hypotheses x 4 causal bias methods x 3 representative context executions",
                "selected_structures": selected_structures,
                "tuned_variant_count": len(tune_variants),
                "tuning": "only the four strongest structure families are expanded across ATR width, RR, breakout confirmation, bias and impulse context on the first 50%",
                "validation": "top 30 development rules are frozen and compared on the next 25%",
                "confirmation": "one validation champion is frozen and reported on the final 25%",
                "robust_pass_rule": "validation and confirmation each require >=15 trades, positive expectancy/net R and PF >=1.10",
            },
            "structure_screen_leaders": [
                {
                    "structure": item["structure"],
                    "rules": {key: value for key, value in item.items() if key != "metrics"},
                    "development_metrics": item["metrics"],
                }
                for item in structure_leaders
            ],
            "development_top_15": ranked_development[:15],
            "validation_candidates": sorted(validation, key=self._rank_key, reverse=True)[:15],
            "champion": {
                "rules": {key: value for key, value in champion_validation.items() if key != "metrics"},
                "development_metrics": champion_development_metrics,
                "validation_metrics": validation_metrics,
                "confirmation_metrics": confirmation_metrics,
                "full_history_metrics": full["metrics"],
                "robust_pass": robust_pass,
            },
            "verdict": "STRUCTURE_EDGE_SURVIVED_CONFIRMATION" if robust_pass else "NO_ROBUST_STRUCTURE_EDGE_CONFIRMED",
        }
