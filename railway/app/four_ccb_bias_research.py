from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.four_ccb_research import FourCCBH1Discovery, _metrics, _profit_factor_for_sort

ENGINE_VERSION = "0.2.0"
STRATEGY_CODE = "four_ccb_h1_bias_discovery_v0_2"

BiasMethod = Literal["momentum_24h", "momentum_72h", "ema_20_50", "range_mid_20"]
Mode = Literal["plain", "reversal", "continuation"]
Confirmation = Literal["touch", "close"]


@dataclass(frozen=True)
class BiasVariant:
    box_atr_max: float
    mode: Mode
    impulse_atr_min: float
    reward_risk: float
    confirmation: Confirmation
    bias_method: BiasMethod

    def as_dict(self) -> dict[str, Any]:
        return {
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


class FourCCBH1BiasDiscovery(FourCCBH1Discovery):
    """Second 4CCB experiment: only take breakouts aligned with a causal H1 bias.

    Bias definitions are predeclared and chosen on the development two-thirds only.
    The winning fixed rule is then run once on the untouched final third.
    """

    def __init__(self, rows: list[dict[str, Any]]):
        super().__init__(rows)
        closes = [c.close for c in self.candles]
        self.ema20 = self._ema(closes, 20)
        self.ema50 = self._ema(closes, 50)

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2.0 / (period + 1.0)
        result = [values[0]]
        for value in values[1:]:
            result.append(alpha * value + (1.0 - alpha) * result[-1])
        return result

    def _bias_direction(self, index: int, method: BiasMethod) -> int:
        # index is the first candle of the 4-candle box. Only information ending at index-1 is used.
        last_index = index - 1
        if last_index < 1:
            return 0

        if method == "momentum_24h":
            earlier = last_index - 24
            if earlier < 0:
                return 0
            delta = self.candles[last_index].close - self.candles[earlier].close
        elif method == "momentum_72h":
            earlier = last_index - 72
            if earlier < 0:
                return 0
            delta = self.candles[last_index].close - self.candles[earlier].close
        elif method == "ema_20_50":
            if last_index < 50:
                return 0
            delta = self.ema20[last_index] - self.ema50[last_index]
        else:
            lookback = 20
            start = last_index - lookback + 1
            if start < 0:
                return 0
            group = self.candles[start:last_index + 1]
            midpoint = (max(c.high for c in group) + min(c.low for c in group)) / 2.0
            delta = self.candles[last_index].close - midpoint

        if delta > 0:
            return 1
        if delta < 0:
            return -1
        return 0

    @staticmethod
    def _side_matches_bias(side: str, bias_direction: int) -> bool:
        return (side == "buy" and bias_direction > 0) or (side == "sell" and bias_direction < 0)

    def run_variant(self, variant: BiasVariant, start: int, end: int) -> dict[str, Any]:
        pnls: list[float] = []
        setups = 0
        ambiguous = 0
        time_exits = 0
        bias_filtered = 0
        index = max(start, self.atr_period, self.impulse_lookback, 73)

        while index + 4 < end:
            atr = self._atr_before(index)
            box = self._box(index, atr, variant.box_atr_max)
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
    def variants() -> list[BiasVariant]:
        result: list[BiasVariant] = []
        for bias_method in ("momentum_24h", "momentum_72h", "ema_20_50", "range_mid_20"):
            for box_atr_max in (1.0, 1.25, 1.5):
                for reward_risk in (1.0, 1.5, 2.0):
                    for confirmation in ("touch", "close"):
                        result.append(BiasVariant(box_atr_max, "plain", 0.0, reward_risk, confirmation, bias_method))
                        for mode in ("reversal", "continuation"):
                            for impulse_atr_min in (0.75, 1.0, 1.25):
                                result.append(BiasVariant(box_atr_max, mode, impulse_atr_min, reward_risk, confirmation, bias_method))
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
    def _family_leader(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
        family = [item for item in items if item.get(key) == value and item["metrics"]["trades"] >= 30]
        if not family:
            family = [item for item in items if item.get(key) == value]
        if not family:
            return None
        best = max(family, key=FourCCBH1BiasDiscovery._rank_key)
        return {
            key: value,
            "best_rules": {k: v for k, v in best.items() if k != "metrics"},
            "development_metrics": best["metrics"],
        }

    def run(self) -> dict[str, Any]:
        n = len(self.candles)
        if n < 500:
            raise RuntimeError("At least 500 stored H1 candles are required for 4CCB bias discovery")

        split = int(n * (2.0 / 3.0))
        variants = self.variants()
        development = [self.run_variant(variant, 0, split) for variant in variants]
        eligible = [item for item in development if item["metrics"]["trades"] >= 40]
        if not eligible:
            eligible = [item for item in development if item["metrics"]["trades"] >= 20]
        if not eligible:
            eligible = development
        ranked = sorted(eligible, key=self._rank_key, reverse=True)
        champion_dev = ranked[0]
        champion_variant = BiasVariant(
            box_atr_max=float(champion_dev["box_atr_max"]),
            mode=str(champion_dev["mode"]),
            impulse_atr_min=float(champion_dev["impulse_atr_min"] or 0.0),
            reward_risk=float(champion_dev["reward_risk"]),
            confirmation=str(champion_dev["confirmation"]),
            bias_method=str(champion_dev["bias_method"]),
        )
        untouched = self.run_variant(champion_variant, split, n)
        full = self.run_variant(champion_variant, 0, n)
        untouched_metrics = untouched["metrics"]
        pf = untouched_metrics["profit_factor"]
        out_of_sample_pass = (
            untouched_metrics["trades"] >= 20
            and untouched_metrics["expectancy_r"] > 0
            and pf is not None
            and pf >= 1.15
            and untouched_metrics["net_r"] > 0
        )

        return {
            "engine_version": ENGINE_VERSION,
            "strategy_code": STRATEGY_CODE,
            "research_question": "Does adding a causal H1 directional bias turn the plausible 4CCB family into an out-of-sample edge?",
            "important_note": "This is a reverse-engineered research family based on visible chart behaviour, not a reproduction of any private VIP rules.",
            "data": {
                "h1_candles": n,
                "first_candle": self.candles[0].candle_time.isoformat(),
                "last_candle": self.candles[-1].candle_time.isoformat(),
                "development_end_exclusive": self.candles[split].candle_time.isoformat(),
                "development_candles": split,
                "untouched_candles": n - split,
            },
            "method": {
                "base_4ccb": "same four-candle compression/breakout family as v0.1",
                "bias_requirement": "every trade must agree with the bias calculated before the first candle of the 4-candle box",
                "bias_variants": [
                    "24-H1 close momentum",
                    "72-H1 close momentum",
                    "causal H1 EMA20/EMA50 alignment",
                    "last close versus midpoint of previous 20-H1 range",
                ],
                "targets_r": [1.0, 1.5, 2.0],
                "confirmation_variants": ["touch", "H1 close outside then next H1 open"],
                "context_variants": ["plain", "reversal after impulse", "continuation after impulse"],
                "selection": "504 bias-filtered variants tested on development two-thirds; one champion frozen and run once on untouched final third",
            },
            "variant_count": len(variants),
            "bias_family_leaders": {
                method: self._family_leader(development, "bias_method", method)
                for method in ("momentum_24h", "momentum_72h", "ema_20_50", "range_mid_20")
            },
            "mode_family_leaders": {
                mode: self._family_leader(development, "mode", mode)
                for mode in ("plain", "reversal", "continuation")
            },
            "development_top_12": ranked[:12],
            "champion": {
                "rules": {key: value for key, value in champion_dev.items() if key != "metrics"},
                "development_metrics": champion_dev["metrics"],
                "untouched_metrics": untouched_metrics,
                "full_history_metrics": full["metrics"],
                "out_of_sample_pass": out_of_sample_pass,
            },
            "verdict": "PROMISING_OUT_OF_SAMPLE" if out_of_sample_pass else "NO_CONFIRMED_OUT_OF_SAMPLE_EDGE",
        }
