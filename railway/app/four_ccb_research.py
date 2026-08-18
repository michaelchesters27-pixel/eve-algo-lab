from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ENGINE_VERSION = "0.1.0"
STRATEGY_CODE = "four_ccb_h1_discovery_v0_1"

Mode = Literal["plain", "reversal", "continuation"]
Confirmation = Literal["touch", "close"]


@dataclass(frozen=True)
class Candle:
    candle_time: datetime
    open: float
    high: float
    low: float
    close: float

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Candle":
        value = row["candle_time"]
        candle_time = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return cls(
            candle_time=candle_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )


@dataclass(frozen=True)
class Variant:
    box_atr_max: float
    mode: Mode
    impulse_atr_min: float
    reward_risk: float
    confirmation: Confirmation

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
            "breakout_wait_h1": 4,
            "maximum_hold_h1": 24,
            "stop": "opposite side of the four-candle box",
        }


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _longest_losing_streak(values: list[float]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _metrics(pnls: list[float], setups: int, ambiguous_breakouts: int, time_exits: int) -> dict[str, Any]:
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    expectancy = sum(pnls) / len(pnls) if pnls else 0.0
    win_rate = len(wins) / len(pnls) * 100.0 if pnls else 0.0
    score = expectancy * math.sqrt(len(pnls)) - 0.02 * _max_drawdown(pnls) if pnls else -999.0
    return {
        "setups": setups,
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 3),
        "net_r": round(sum(pnls), 3),
        "expectancy_r": round(expectancy, 5),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "max_drawdown_r": round(_max_drawdown(pnls), 3),
        "longest_losing_streak": _longest_losing_streak(pnls),
        "ambiguous_breakouts_skipped": ambiguous_breakouts,
        "time_exits": time_exits,
        "selection_score": round(score, 5),
    }


def _profit_factor_for_sort(metrics: dict[str, Any]) -> float:
    value = metrics.get("profit_factor")
    return float(value) if value is not None else 99.0


class FourCCBH1Discovery:
    """Exploratory reconstruction of a four-candle H1 consolidation breakout family.

    This is not represented as the proprietary rules of any third party. It deliberately
    tests a small, predeclared family of plausible four-candle compression/breakout rules.
    """

    atr_period = 20
    overlap_min_fraction = 0.10
    impulse_lookback = 3
    breakout_wait = 4
    maximum_hold = 24
    spread_price = 0.05
    slippage_price = 0.0

    def __init__(self, rows: list[dict[str, Any]]):
        self.candles = [Candle.from_row(row) for row in rows]
        self.true_ranges = self._true_ranges(self.candles)
        self.atr_prefix = [0.0]
        for value in self.true_ranges:
            self.atr_prefix.append(self.atr_prefix[-1] + value)

    @staticmethod
    def _true_ranges(candles: list[Candle]) -> list[float]:
        values: list[float] = []
        previous_close: float | None = None
        for candle in candles:
            if previous_close is None:
                tr = candle.high - candle.low
            else:
                tr = max(
                    candle.high - candle.low,
                    abs(candle.high - previous_close),
                    abs(candle.low - previous_close),
                )
            values.append(max(0.0, tr))
            previous_close = candle.close
        return values

    def _atr_before(self, index: int) -> float:
        if index < self.atr_period:
            return 0.0
        total = self.atr_prefix[index] - self.atr_prefix[index - self.atr_period]
        return total / self.atr_period

    def _box(self, index: int, atr: float, box_atr_max: float) -> tuple[float, float] | None:
        group = self.candles[index:index + 4]
        if len(group) < 4 or atr <= 0:
            return None
        box_high = max(c.high for c in group)
        box_low = min(c.low for c in group)
        box_range = box_high - box_low
        if box_range <= 0 or box_range > atr * box_atr_max:
            return None

        common_high = min(c.high for c in group)
        common_low = max(c.low for c in group)
        common_overlap = max(0.0, common_high - common_low)
        if common_overlap / box_range < self.overlap_min_fraction:
            return None
        return box_high, box_low

    def _impulse_direction(self, index: int, atr: float, minimum: float) -> int:
        if index < self.impulse_lookback or atr <= 0:
            return 0
        first = self.candles[index - self.impulse_lookback]
        last = self.candles[index - 1]
        move = last.close - first.open
        if abs(move) < atr * minimum:
            return 0
        return 1 if move > 0 else -1

    def _direction_allowed(self, mode: Mode, impulse_direction: int, side: str) -> bool:
        if mode == "plain":
            return True
        if impulse_direction == 0:
            return False
        desired = "buy" if impulse_direction > 0 else "sell"
        if mode == "reversal":
            desired = "sell" if impulse_direction > 0 else "buy"
        return side == desired

    def _find_breakout(
        self,
        start: int,
        end: int,
        box_high: float,
        box_low: float,
        variant: Variant,
        impulse_direction: int,
    ) -> tuple[int, str, float] | tuple[int, str, None] | None:
        last = min(end - 1, start + self.breakout_wait - 1)
        for index in range(start, last + 1):
            candle = self.candles[index]
            if variant.confirmation == "touch":
                up = candle.high > box_high
                down = candle.low < box_low
            else:
                up = candle.close > box_high
                down = candle.close < box_low

            if up and down:
                return index, "ambiguous", None
            if not up and not down:
                continue

            side = "buy" if up else "sell"
            if not self._direction_allowed(variant.mode, impulse_direction, side):
                return index, "invalidated", None

            if variant.confirmation == "touch":
                entry = box_high if side == "buy" else box_low
                return index, side, entry

            entry_index = index + 1
            if entry_index >= end:
                return None
            return entry_index, side, self.candles[entry_index].open
        return None

    def _simulate_trade(
        self,
        entry_index: int,
        end: int,
        side: str,
        entry: float,
        box_high: float,
        box_low: float,
        reward_risk: float,
    ) -> tuple[int, float, bool] | None:
        if side == "buy":
            stop = box_low
            risk = entry - stop
        else:
            stop = box_high
            risk = stop - entry
        if risk <= 0:
            return None

        target = entry + reward_risk * risk if side == "buy" else entry - reward_risk * risk
        cost_r = (self.spread_price + 2.0 * self.slippage_price) / risk
        final_index = min(end - 1, entry_index + self.maximum_hold - 1)

        for index in range(entry_index, final_index + 1):
            candle = self.candles[index]
            if side == "buy":
                stop_hit = candle.low <= stop
                target_hit = candle.high >= target
            else:
                stop_hit = candle.high >= stop
                target_hit = candle.low <= target

            if stop_hit and target_hit:
                return index, -1.0 - cost_r, False
            if stop_hit:
                return index, -1.0 - cost_r, False
            if target_hit:
                return index, reward_risk - cost_r, False

        close = self.candles[final_index].close
        raw_r = (close - entry) / risk if side == "buy" else (entry - close) / risk
        return final_index, raw_r - cost_r, True

    def run_variant(self, variant: Variant, start: int, end: int) -> dict[str, Any]:
        pnls: list[float] = []
        setups = 0
        ambiguous = 0
        time_exits = 0
        index = max(start, self.atr_period, self.impulse_lookback)

        while index + 4 < end:
            atr = self._atr_before(index)
            box = self._box(index, atr, variant.box_atr_max)
            if box is None:
                index += 1
                continue
            box_high, box_low = box

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
        return result

    @staticmethod
    def variants() -> list[Variant]:
        result: list[Variant] = []
        for box_atr_max in (1.0, 1.25, 1.5):
            for reward_risk in (1.0, 1.5, 2.0):
                for confirmation in ("touch", "close"):
                    result.append(
                        Variant(
                            box_atr_max=box_atr_max,
                            mode="plain",
                            impulse_atr_min=0.0,
                            reward_risk=reward_risk,
                            confirmation=confirmation,
                        )
                    )
                    for mode in ("reversal", "continuation"):
                        for impulse_atr_min in (0.75, 1.0, 1.25):
                            result.append(
                                Variant(
                                    box_atr_max=box_atr_max,
                                    mode=mode,
                                    impulse_atr_min=impulse_atr_min,
                                    reward_risk=reward_risk,
                                    confirmation=confirmation,
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
    def _summarise_family(items: list[dict[str, Any]], mode: str) -> dict[str, Any] | None:
        family = [item for item in items if item["mode"] == mode and item["metrics"]["trades"] >= 40]
        if not family:
            family = [item for item in items if item["mode"] == mode]
        if not family:
            return None
        best = max(family, key=FourCCBH1Discovery._rank_key)
        return {
            "mode": mode,
            "best_rules": {key: value for key, value in best.items() if key != "metrics"},
            "development_metrics": best["metrics"],
        }

    def run(self) -> dict[str, Any]:
        n = len(self.candles)
        if n < 500:
            raise RuntimeError("At least 500 stored H1 candles are required for 4CCB discovery")

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
        champion_variant = Variant(
            box_atr_max=float(champion_dev["box_atr_max"]),
            mode=str(champion_dev["mode"]),
            impulse_atr_min=float(champion_dev["impulse_atr_min"] or 0.0),
            reward_risk=float(champion_dev["reward_risk"]),
            confirmation=str(champion_dev["confirmation"]),
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

        first = self.candles[0].candle_time.isoformat()
        last = self.candles[-1].candle_time.isoformat()
        split_time = self.candles[split].candle_time.isoformat()

        return {
            "engine_version": ENGINE_VERSION,
            "strategy_code": STRATEGY_CODE,
            "research_question": "Does a plausible H1 four-candle consolidation breakout family show an out-of-sample edge on stored XAU/USD history?",
            "important_note": (
                "This is a reverse-engineered research family based on visible chart behaviour, not a claim to reproduce any private or proprietary VIP rule set."
            ),
            "data": {
                "h1_candles": n,
                "first_candle": first,
                "last_candle": last,
                "development_end_exclusive": split_time,
                "development_candles": split,
                "untouched_candles": n - split,
            },
            "method": {
                "box": "4 consecutive H1 candles with at least 10% common price overlap",
                "compression": "4-candle high-low range must be no more than 1.0, 1.25 or 1.5 times causal ATR(20)",
                "breakout": "first qualifying break within the next 4 H1 candles",
                "confirmation_variants": ["intrabar touch of box edge", "H1 close outside then enter next H1 open"],
                "context_variants": [
                    "plain breakout",
                    "reversal after a 3-H1 impulse of at least 0.75/1.0/1.25 ATR",
                    "continuation after the same impulse filter",
                ],
                "stop": "opposite edge of four-candle box",
                "targets_r": [1.0, 1.5, 2.0],
                "maximum_hold_h1": self.maximum_hold,
                "same_bar_stop_and_target": "counted as stop first (conservative)",
                "spread_price_deduction": self.spread_price,
                "selection": "all variants tested only on first two-thirds; one champion frozen and then tested once on final untouched third",
            },
            "variant_count": len(variants),
            "family_leaders": {
                mode: self._summarise_family(development, mode)
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
            "verdict": (
                "PROMISING_OUT_OF_SAMPLE"
                if out_of_sample_pass
                else "NO_CONFIRMED_OUT_OF_SAMPLE_EDGE"
            ),
        }
