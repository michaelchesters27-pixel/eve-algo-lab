from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.four_ccb_research import _metrics
from app.four_ccb_structure_research import FourCCBH1StructureDiscovery, StructureVariant

ENGINE_VERSION = "0.5.0"
STRATEGY_CODE = "four_ccb_h1_m1_execution_validation_v0_5"

BASE_COST_PRICE = 0.05
COST_SCENARIOS = {
    "baseline_0p05": 0.05,
    "double_0p10": 0.10,
    "triple_0p15": 0.15,
}
BREAKOUT_EXCESS_ATR_MIN = 0.10


@dataclass(frozen=True)
class ExecutionSignal:
    setup_index: int
    entry_index: int
    setup_time: datetime
    confirm_time: datetime
    entry_time: datetime
    hold_end_time: datetime
    side: str
    box_high: float
    box_low: float
    atr: float
    breakout_excess_atr: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "setup_time": self.setup_time.isoformat(),
            "confirm_time": self.confirm_time.isoformat(),
            "entry_time": self.entry_time.isoformat(),
            "hold_end_time": self.hold_end_time.isoformat(),
            "side": self.side,
            "box_high": round(self.box_high, 6),
            "box_low": round(self.box_low, 6),
            "atr": round(self.atr, 6),
            "breakout_excess_atr": round(self.breakout_excess_atr, 6),
        }


@dataclass(frozen=True)
class ExecutionTrade:
    signal: ExecutionSignal
    exit_time: datetime
    entry: float
    stop: float
    target: float
    risk_price: float
    gross_r: float
    exit_reason: str
    same_m1_both_sides: bool

    def net_r(self, cost_price: float) -> float:
        return self.gross_r - max(0.0, float(cost_price)) / self.risk_price


class FourCCBH1M1ExecutionValidator(FourCCBH1StructureDiscovery):
    """Frozen v0.4 candidate signal generator plus conservative M1 replay helpers.

    H1 creates the signal. M1 is used only after the signal is fully knowable.
    If one M1 candle can hit both stop and target, the stop is assumed first.
    """

    @staticmethod
    def primary_variant() -> StructureVariant:
        return StructureVariant(
            structure="mother_bar_small_bodies",
            box_atr_max=1.25,
            mode="plain",
            impulse_atr_min=0.0,
            reward_risk=2.0,
            confirmation="close",
            bias_method="ema_20_50",
        )

    @staticmethod
    def _side_matches(side: str, direction: int) -> bool:
        return (side == "buy" and direction > 0) or (side == "sell" and direction < 0)

    def signals(self) -> list[ExecutionSignal]:
        variant = self.primary_variant()
        end = len(self.candles)
        result: list[ExecutionSignal] = []
        index = max(self.atr_period, self.impulse_lookback, 73)

        while index + 5 < end:
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

            breakout = self._find_breakout(index + 4, end, box_high, box_low, variant, 0)
            if breakout is None:
                index += 1
                continue
            entry_index, side, entry = breakout
            if side in {"ambiguous", "invalidated"} or entry is None:
                index = max(index + 1, entry_index + 1)
                continue
            if not self._side_matches(side, bias_direction):
                index = max(index + 1, entry_index + 1)
                continue

            confirm_index = entry_index - 1
            if confirm_index < 0 or confirm_index >= end:
                index += 1
                continue
            confirm = self.candles[confirm_index]
            if side == "buy":
                excess = max(0.0, confirm.close - box_high)
            else:
                excess = max(0.0, box_low - confirm.close)
            breakout_excess_atr = excess / atr if atr > 0 else 0.0
            if breakout_excess_atr < BREAKOUT_EXCESS_ATR_MIN:
                index = max(index + 1, entry_index + 1)
                continue

            if entry_index >= end:
                break
            hold_end_index = min(end - 1, entry_index + self.maximum_hold)
            if hold_end_index > entry_index:
                hold_end_time = self.candles[hold_end_index].candle_time
            else:
                hold_end_time = self.candles[entry_index].candle_time + timedelta(hours=self.maximum_hold)

            result.append(
                ExecutionSignal(
                    setup_index=index,
                    entry_index=entry_index,
                    setup_time=self.candles[index].candle_time,
                    confirm_time=confirm.candle_time,
                    entry_time=self.candles[entry_index].candle_time,
                    hold_end_time=hold_end_time,
                    side=side,
                    box_high=box_high,
                    box_low=box_low,
                    atr=atr,
                    breakout_excess_atr=breakout_excess_atr,
                )
            )
            # Do not use H1 simulated exits to decide which later signals exist. M1 replay
            # enforces one-position-at-a-time chronologically using the actual replay exit.
            index = max(index + 1, entry_index + 1)

        return result

    @staticmethod
    def _parse_time(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @classmethod
    def replay_signal(cls, signal: ExecutionSignal, rows: list[dict[str, Any]]) -> ExecutionTrade | None:
        parsed = sorted(
            ((cls._parse_time(row["candle_time"]), row) for row in rows),
            key=lambda item: item[0],
        )
        parsed = [(stamp, row) for stamp, row in parsed if signal.entry_time <= stamp < signal.hold_end_time]
        if not parsed:
            return None

        first_time, first = parsed[0]
        if first_time > signal.entry_time + timedelta(minutes=2):
            return None
        entry = float(first["open"])
        stop = signal.box_low if signal.side == "buy" else signal.box_high
        risk = entry - stop if signal.side == "buy" else stop - entry
        if risk <= 0:
            return None
        target = entry + 2.0 * risk if signal.side == "buy" else entry - 2.0 * risk

        last_time = first_time
        last_close = entry
        for timestamp, candle in parsed:
            bar_open = float(candle["open"])
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
            last_time = timestamp
            last_close = close

            if signal.side == "buy":
                if bar_open <= stop:
                    gross = (bar_open - entry) / risk
                    return ExecutionTrade(signal, timestamp, entry, stop, target, risk, gross, "gap_stop", False)
                if bar_open >= target:
                    return ExecutionTrade(signal, timestamp, entry, stop, target, risk, 2.0, "gap_target", False)
                hit_stop = low <= stop
                hit_target = high >= target
            else:
                if bar_open >= stop:
                    gross = (entry - bar_open) / risk
                    return ExecutionTrade(signal, timestamp, entry, stop, target, risk, gross, "gap_stop", False)
                if bar_open <= target:
                    return ExecutionTrade(signal, timestamp, entry, stop, target, risk, 2.0, "gap_target", False)
                hit_stop = high >= stop
                hit_target = low <= target

            if hit_stop and hit_target:
                return ExecutionTrade(signal, timestamp, entry, stop, target, risk, -1.0, "stop_conservative_same_m1", True)
            if hit_stop:
                return ExecutionTrade(signal, timestamp, entry, stop, target, risk, -1.0, "stop", False)
            if hit_target:
                return ExecutionTrade(signal, timestamp, entry, stop, target, risk, 2.0, "target", False)

        # Require the M1 window to reach close enough to the H1-defined hold boundary.
        # Gold has a daily maintenance break, so allow a 90-minute tolerance.
        if last_time < signal.hold_end_time - timedelta(minutes=90):
            return None
        gross = (last_close - entry) / risk if signal.side == "buy" else (entry - last_close) / risk
        gross = max(-2.5, min(2.0, gross))
        return ExecutionTrade(signal, last_time, entry, stop, target, risk, gross, "time_exit", False)

    @staticmethod
    def metrics(trades: list[ExecutionTrade], cost_price: float) -> dict[str, Any]:
        pnls = [trade.net_r(cost_price) for trade in trades]
        metrics = _metrics(pnls, len(trades), 0, sum(trade.exit_reason == "time_exit" for trade in trades))
        metrics["same_m1_both_sides"] = sum(trade.same_m1_both_sides for trade in trades)
        metrics["cost_price_per_trade"] = cost_price
        return metrics

    @classmethod
    def grouped_metrics(cls, trades: list[ExecutionTrade], cost_price: float, key: str) -> dict[str, Any]:
        groups: dict[str, list[ExecutionTrade]] = {}
        for trade in trades:
            if key == "year":
                label = str(trade.signal.entry_time.year)
            elif key == "side":
                label = trade.signal.side
            else:
                raise ValueError(key)
            groups.setdefault(label, []).append(trade)
        return {label: cls.metrics(items, cost_price) for label, items in sorted(groups.items())}

    @classmethod
    def report(
        cls,
        h1_rows: list[dict[str, Any]],
        signals: list[ExecutionSignal],
        trades: list[ExecutionTrade],
        unresolved: int,
        skipped_while_open: int,
        m1_rows_loaded: int,
        m1_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        resolved_total = len(trades) + unresolved
        resolved_rate = len(trades) / resolved_total if resolved_total else 0.0
        cost_reports: dict[str, Any] = {}
        for label, cost in COST_SCENARIOS.items():
            cost_reports[label] = {
                "overall": cls.metrics(trades, cost),
                "2020_2023": cls.metrics([t for t in trades if t.signal.entry_time.year <= 2023], cost),
                "2024_plus": cls.metrics([t for t in trades if t.signal.entry_time.year >= 2024], cost),
                "2025_2026": cls.metrics([t for t in trades if t.signal.entry_time.year >= 2025], cost),
                "yearly": cls.grouped_metrics(trades, cost, "year"),
                "side": cls.grouped_metrics(trades, cost, "side"),
            }

        baseline = cost_reports["baseline_0p05"]
        later = baseline["2024_plus"]
        double_later = cost_reports["double_0p10"]["2024_plus"]
        triple_later = cost_reports["triple_0p15"]["2024_plus"]
        later_pf = later["profit_factor"]
        double_pf = double_later["profit_factor"]
        triple_pf = triple_later["profit_factor"]

        pass_base = (
            resolved_rate >= 0.98
            and later["trades"] >= 20
            and later["expectancy_r"] > 0
            and later["net_r"] > 0
            and later_pf is not None
            and later_pf >= 1.20
        )
        pass_double = (
            double_later["expectancy_r"] > 0
            and double_later["net_r"] > 0
            and double_pf is not None
            and double_pf >= 1.10
        )
        pass_triple = (
            triple_later["expectancy_r"] > 0
            and triple_later["net_r"] > 0
            and triple_pf is not None
            and triple_pf >= 1.02
        )
        verdict = "M1_EXECUTION_FAILED"
        if pass_base and pass_double and pass_triple:
            verdict = "M1_EXECUTION_SURVIVES_COST_STRESS"
        elif pass_base and pass_double:
            verdict = "M1_EXECUTION_PROMISING_COST_SENSITIVE"
        elif pass_base:
            verdict = "M1_EXECUTION_BASELINE_ONLY"

        return {
            "engine_version": ENGINE_VERSION,
            "strategy_code": STRATEGY_CODE,
            "research_question": "Does the frozen v0.4 4CCB candidate survive conservative M1 execution replay and 1x/2x/3x transaction-cost stress?",
            "important_note": "This is a reverse-engineered public-chart hypothesis, not a claim about private/VIP rules. Historical data has already informed earlier research; this is execution robustness, not a pristine discovery holdout.",
            "frozen_rules": {
                **cls.primary_variant().as_dict(),
                "breakout_close_excess_atr_min": BREAKOUT_EXCESS_ATR_MIN,
                "entry_execution": "first stored M1 open at the next H1 open",
                "same_m1_stop_and_target": "stop assumed first",
                "cost_scenarios_price_units": COST_SCENARIOS,
                "one_position_at_a_time": True,
            },
            "data": {
                "h1_candles": len(h1_rows),
                "h1_first": str(h1_rows[0]["candle_time"]) if h1_rows else None,
                "h1_last": str(h1_rows[-1]["candle_time"]) if h1_rows else None,
                "eligible_h1_signals": len(signals),
                "m1_rows_loaded_across_windows": m1_rows_loaded,
                "m1_state": m1_state or {},
                "resolved_trades": len(trades),
                "unresolved_signals": unresolved,
                "resolved_rate": round(resolved_rate, 6),
                "signals_skipped_while_position_open": skipped_while_open,
            },
            "cost_stress": cost_reports,
            "gates": {
                "baseline_2024_plus_pass": pass_base,
                "double_cost_2024_plus_pass": pass_double,
                "triple_cost_2024_plus_pass": pass_triple,
            },
            "verdict": verdict,
        }
