from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from app.four_ccb_bias_research import BiasMethod, FourCCBH1BiasDiscovery
from app.four_ccb_research import _metrics, _profit_factor_for_sort

ENGINE_VERSION = "0.1.0"
STRATEGY_CODE = "four_ccb_daily_v0_1"

DailyExecution = Literal["bias_market", "breakout_touch", "breakout_close"]

START_HOURS_UTC: tuple[int, ...] = (0, 4, 6, 8, 12)
BIAS_METHODS: tuple[BiasMethod, ...] = ("momentum_24h", "ema_20_50")


@dataclass(frozen=True)
class DailyVariant:
    start_hour_utc: int
    box_atr_max: float
    overlap_min_fraction: float
    reward_risk: float
    execution: DailyExecution
    bias_method: BiasMethod
    breakout_wait_h1: int = 4

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": "4CCB Daily",
            "timeframe": "H1",
            "start_hour_utc": self.start_hour_utc,
            "box_candles": 4,
            "box_atr_max": self.box_atr_max,
            "common_overlap_min_fraction": self.overlap_min_fraction,
            "reward_risk": self.reward_risk,
            "execution": self.execution,
            "bias_method": self.bias_method,
            "breakout_wait_h1": self.breakout_wait_h1 if self.execution != "bias_market" else None,
            "maximum_hold_h1": 12,
            "maximum_new_trades_per_utc_day": 1,
            "one_position_at_a_time": True,
            "stop": "opposite side of the fixed four-H1-candle daily box",
            "cost_proxy_price_units_per_trade": 0.18,
        }


class FourCCBDailyResearch(FourCCBH1BiasDiscovery):
    """Research a high-frequency 4CCB descendant without changing the frozen 4CCB candidate.

    Every variant uses one fixed, causal four-H1-candle box per UTC trading day. The engine
    can either enter with the pre-box H1 bias at the next H1 open, or wait for a bias-aligned
    touch/close breakout. It never chooses the best setup after seeing the rest of the day.
    """

    spread_price = 0.18
    slippage_price = 0.0
    maximum_hold = 12

    def __init__(self, rows: list[dict[str, Any]]):
        super().__init__(rows)
        self.anchors: dict[int, list[int]] = {hour: [] for hour in START_HOURS_UTC}
        for index, candle in enumerate(self.candles):
            hour = candle.candle_time.hour
            if hour not in self.anchors or candle.candle_time.weekday() >= 5:
                continue
            if index + 4 >= len(self.candles):
                continue
            group = self.candles[index:index + 4]
            if any(item.candle_time.date() != candle.candle_time.date() for item in group):
                continue
            contiguous = all(
                int((group[pos].candle_time - group[pos - 1].candle_time).total_seconds()) == 3600
                for pos in range(1, 4)
            )
            if contiguous:
                self.anchors[hour].append(index)

    def _daily_box(self, index: int, atr: float, variant: DailyVariant) -> tuple[float, float] | None:
        group = self.candles[index:index + 4]
        if len(group) < 4 or atr <= 0:
            return None
        box_high = max(c.high for c in group)
        box_low = min(c.low for c in group)
        box_range = box_high - box_low
        if box_range <= 0 or box_range > atr * variant.box_atr_max:
            return None
        common_high = min(c.high for c in group)
        common_low = max(c.low for c in group)
        overlap = max(0.0, common_high - common_low)
        if overlap / box_range < variant.overlap_min_fraction:
            return None
        return box_high, box_low

    def _daily_breakout(
        self,
        start: int,
        end: int,
        box_high: float,
        box_low: float,
        bias_direction: int,
        variant: DailyVariant,
    ) -> tuple[int, str, float] | tuple[int, str, None] | None:
        desired = "buy" if bias_direction > 0 else "sell"
        last = min(end - 1, start + variant.breakout_wait_h1 - 1)
        close_confirmation = variant.execution == "breakout_close"
        for index in range(start, last + 1):
            candle = self.candles[index]
            if close_confirmation:
                up = candle.close > box_high
                down = candle.close < box_low
            else:
                up = candle.high > box_high
                down = candle.low < box_low
            if up and down:
                return index, "ambiguous", None
            if not up and not down:
                continue
            side = "buy" if up else "sell"
            if side != desired:
                return index, "invalidated", None
            if close_confirmation:
                entry_index = index + 1
                if entry_index >= end:
                    return None
                return entry_index, side, self.candles[entry_index].open
            entry = box_high if side == "buy" else box_low
            return index, side, entry
        return None

    def run_variant(self, variant: DailyVariant, start: int, end: int) -> dict[str, Any]:
        pnls: list[float] = []
        setups = 0
        ambiguous = 0
        time_exits = 0
        invalidated = 0
        busy_days_skipped = 0
        anchors = [index for index in self.anchors[variant.start_hour_utc] if start <= index and index + 4 < end]
        busy_until = start - 1

        for index in anchors:
            if index <= busy_until:
                busy_days_skipped += 1
                continue
            atr = self._atr_before(index)
            box = self._daily_box(index, atr, variant)
            if box is None:
                continue
            box_high, box_low = box
            bias_direction = self._bias_direction(index, variant.bias_method)
            if bias_direction == 0:
                continue
            setups += 1

            if variant.execution == "bias_market":
                entry_index = index + 4
                if entry_index >= end:
                    continue
                side = "buy" if bias_direction > 0 else "sell"
                entry = self.candles[entry_index].open
            else:
                breakout = self._daily_breakout(index + 4, end, box_high, box_low, bias_direction, variant)
                if breakout is None:
                    continue
                entry_index, side, entry = breakout
                if side == "ambiguous":
                    ambiguous += 1
                    continue
                if side == "invalidated" or entry is None:
                    invalidated += 1
                    continue

            trade = self._simulate_trade(
                entry_index,
                end,
                side,
                float(entry),
                box_high,
                box_low,
                variant.reward_risk,
            )
            if trade is None:
                continue
            exit_index, pnl_r, timed_out = trade
            pnls.append(pnl_r)
            busy_until = exit_index
            if timed_out:
                time_exits += 1

        result = variant.as_dict()
        metrics = _metrics(pnls, setups, ambiguous, time_exits)
        eligible_days = len(anchors)
        metrics["eligible_days"] = eligible_days
        metrics["setup_days_pct"] = round(100.0 * setups / eligible_days, 3) if eligible_days else 0.0
        metrics["trade_days_pct"] = round(100.0 * len(pnls) / eligible_days, 3) if eligible_days else 0.0
        metrics["counter_bias_breakout_invalidations"] = invalidated
        metrics["busy_days_skipped"] = busy_days_skipped
        metrics["daily_selection_score"] = round(
            float(metrics["selection_score"]) + 0.02 * float(metrics["trade_days_pct"]), 5
        )
        result["metrics"] = metrics
        return result

    @staticmethod
    def variants() -> list[DailyVariant]:
        result: list[DailyVariant] = []
        for start_hour in START_HOURS_UTC:
            for box_atr_max in (1.5, 2.0, 3.0):
                for overlap in (0.0, 0.05, 0.10):
                    for reward_risk in (1.0, 1.5, 2.0):
                        for execution in ("bias_market", "breakout_touch", "breakout_close"):
                            for bias_method in BIAS_METHODS:
                                result.append(
                                    DailyVariant(
                                        start_hour_utc=start_hour,
                                        box_atr_max=box_atr_max,
                                        overlap_min_fraction=overlap,
                                        reward_risk=reward_risk,
                                        execution=execution,
                                        bias_method=bias_method,
                                    )
                                )
        return result

    @staticmethod
    def _rank_key(result: dict[str, Any]) -> tuple[float, float, float, float, int]:
        metrics = result["metrics"]
        return (
            float(metrics["daily_selection_score"]),
            float(metrics["expectancy_r"]),
            _profit_factor_for_sort(metrics),
            float(metrics["trade_days_pct"]),
            int(metrics["trades"]),
        )

    @staticmethod
    def _variant_from_result(result: dict[str, Any]) -> DailyVariant:
        return DailyVariant(
            start_hour_utc=int(result["start_hour_utc"]),
            box_atr_max=float(result["box_atr_max"]),
            overlap_min_fraction=float(result["common_overlap_min_fraction"]),
            reward_risk=float(result["reward_risk"]),
            execution=str(result["execution"]),
            bias_method=str(result["bias_method"]),
            breakout_wait_h1=int(result.get("breakout_wait_h1") or 4),
        )

    @staticmethod
    def _variant_key(result: dict[str, Any]) -> tuple[Any, ...]:
        return (
            int(result["start_hour_utc"]),
            float(result["box_atr_max"]),
            float(result["common_overlap_min_fraction"]),
            float(result["reward_risk"]),
            str(result["execution"]),
            str(result["bias_method"]),
        )

    def run(self) -> dict[str, Any]:
        n = len(self.candles)
        if n < 5000:
            raise RuntimeError("At least 5,000 stored H1 candles are required for 4CCB Daily research")

        split_development = int(n * 0.50)
        split_validation = int(n * 0.75)
        variants = self.variants()
        development = [self.run_variant(variant, 0, split_development) for variant in variants]

        eligible = [
            item for item in development
            if item["metrics"]["trades"] >= 250 and item["metrics"]["trade_days_pct"] >= 60.0
        ]
        if not eligible:
            eligible = [
                item for item in development
                if item["metrics"]["trades"] >= 150 and item["metrics"]["trade_days_pct"] >= 40.0
            ]
        if not eligible:
            eligible = development
        ranked_development = sorted(eligible, key=self._rank_key, reverse=True)

        candidate_variants = [self._variant_from_result(item) for item in ranked_development[:24]]
        validation = [self.run_variant(variant, split_development, split_validation) for variant in candidate_variants]
        validation_eligible = [
            item for item in validation
            if item["metrics"]["trades"] >= 75 and item["metrics"]["trade_days_pct"] >= 50.0
        ]
        if not validation_eligible:
            validation_eligible = [item for item in validation if item["metrics"]["trades"] >= 50]
        if not validation_eligible:
            validation_eligible = validation
        champion_validation = max(validation_eligible, key=self._rank_key)
        champion_variant = self._variant_from_result(champion_validation)

        dev_metrics_by_key = {self._variant_key(item): item["metrics"] for item in development}
        champion_development_metrics = dev_metrics_by_key.get(self._variant_key(champion_validation), {})
        confirmation = self.run_variant(champion_variant, split_validation, n)
        full = self.run_variant(champion_variant, 0, n)

        validation_metrics = champion_validation["metrics"]
        confirmation_metrics = confirmation["metrics"]
        edge_pass = all(
            metrics["trades"] >= 75
            and metrics["expectancy_r"] > 0
            and metrics["net_r"] > 0
            and metrics["profit_factor"] is not None
            and metrics["profit_factor"] >= 1.15
            for metrics in (validation_metrics, confirmation_metrics)
        )
        frequency_pass = all(
            metrics["trade_days_pct"] >= 70.0
            for metrics in (validation_metrics, confirmation_metrics)
        )
        robust_pass = edge_pass and frequency_pass

        if robust_pass:
            verdict = "DAILY_FREQUENCY_EDGE_CONFIRMED"
        elif edge_pass:
            verdict = "EDGE_FOUND_BUT_DAILY_FREQUENCY_NOT_CONFIRMED"
        else:
            verdict = "NO_ROBUST_4CCB_DAILY_EDGE"

        return {
            "engine_version": ENGINE_VERSION,
            "strategy_code": STRATEGY_CODE,
            "name": "4CCB Daily",
            "research_question": "Can a fixed, causal four-H1-candle daily box produce a robust high-frequency Gold strategy approaching one trade per trading day?",
            "important_note": (
                "4CCB Daily is a separate research branch. It does not alter the frozen low-frequency 4CCB candidate. "
                "The engine never selects the best box after seeing the rest of the day, and it includes a 0.18 XAU price-unit per-trade broker-cost proxy."
            ),
            "data": {
                "h1_candles": n,
                "first_candle": self.candles[0].candle_time.isoformat(),
                "last_candle": self.candles[-1].candle_time.isoformat(),
                "development_end_exclusive": self.candles[split_development].candle_time.isoformat(),
                "validation_end_exclusive": self.candles[split_validation].candle_time.isoformat(),
            },
            "method": {
                "variant_count": len(variants),
                "fixed_start_hours_utc": list(START_HOURS_UTC),
                "bias_methods": list(BIAS_METHODS),
                "execution_families": ["next-H1-open with causal bias", "bias-aligned touch breakout", "bias-aligned close breakout"],
                "maximum_new_trades_per_day": 1,
                "one_position_at_a_time": True,
                "daily_frequency_target": ">=70% of eligible trading days in both validation and confirmation",
                "edge_gate": "PF >=1.15, positive expectancy/net R and >=75 trades in both validation and confirmation",
                "chronology": "50% development, 25% validation selection, 25% final confirmation",
            },
            "development_top_15": ranked_development[:15],
            "validation_candidates": sorted(validation, key=self._rank_key, reverse=True)[:15],
            "champion": {
                "rules": {key: value for key, value in champion_validation.items() if key != "metrics"},
                "development_metrics": champion_development_metrics,
                "validation_metrics": validation_metrics,
                "confirmation_metrics": confirmation_metrics,
                "full_history_metrics": full["metrics"],
                "edge_pass": edge_pass,
                "frequency_pass": frequency_pass,
                "robust_pass": robust_pass,
            },
            "verdict": verdict,
        }
