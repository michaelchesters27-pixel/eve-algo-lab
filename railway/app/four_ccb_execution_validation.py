from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.four_ccb_research import _metrics
from app.four_ccb_structure_research import FourCCBH1StructureDiscovery, StructureVariant

ENGINE_VERSION = "0.6.0"
STRATEGY_CODE = "four_ccb_h1_m1_execution_validation_v0_6"

# Existing generic execution stresses are retained for continuity. The broker-proxy
# scenarios do not alter the frozen signal logic. IC's public help material states
# that Raw Spread MT5 gold averages 1 pip and a 0.01-lot MT5 commission is rounded
# to $0.04 per side ($0.08 round turn). EVE's existing XAU model uses $1 P/L for a
# $1 XAU move at 0.01 lot, so $0.08 round-turn commission maps to 0.08 XAU price
# units. We conservatively infer 1 gold pip as 0.10 XAU price units from IC's own
# quoted XAU display convention. Therefore 0.18 is a public-data broker proxy, not
# a substitute for the exact Symbol Specification and measured spreads from the
# user's own MT5 account.
COST_SCENARIOS = {
    "legacy_0p05": 0.05,
    "legacy_0p10": 0.10,
    "legacy_0p15": 0.15,
    "ic_mt5_raw_proxy_0p18": 0.18,
    "adverse_0p25": 0.25,
    "severe_0p35": 0.35,
    "extreme_0p50": 0.50,
}
IC_MT5_RAW_PROXY_COST = 0.18
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
    def _failure_margin(cls, trades: list[ExecutionTrade]) -> dict[str, Any]:
        later = [trade for trade in trades if trade.signal.entry_time.year >= 2024]
        last_pass: dict[str, Any] | None = None
        first_fail: dict[str, Any] | None = None
        # A 0.01 XAU-price-unit grid is deliberately coarser than tick-level fitting;
        # this is a robustness boundary, not an optimizer.
        for step in range(0, 201):
            cost = round(step / 100.0, 2)
            metrics = cls.metrics(later, cost)
            pf = metrics.get("profit_factor")
            passes = (
                metrics["trades"] >= 20
                and metrics["expectancy_r"] > 0
                and metrics["net_r"] > 0
                and pf is not None
                and float(pf) >= 1.20
            )
            point = {
                "cost_price_per_trade": cost,
                "profit_factor": pf,
                "expectancy_r": metrics["expectancy_r"],
                "net_r": metrics["net_r"],
            }
            if passes:
                last_pass = point
                continue
            first_fail = point
            break
        return {
            "gate": "2024+ requires >=20 trades, positive expectancy/net R and PF >=1.20",
            "last_passing_cost": last_pass,
            "first_failing_cost": first_fail,
            "grid_step_price_units": 0.01,
            "grid_max_price_units": 2.0,
        }

    @staticmethod
    def _passes_cost_gate(metrics: dict[str, Any], minimum_pf: float) -> bool:
        pf = metrics.get("profit_factor")
        return (
            metrics["trades"] >= 20
            and metrics["expectancy_r"] > 0
            and metrics["net_r"] > 0
            and pf is not None
            and float(pf) >= minimum_pf
        )

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

        legacy_later = cost_reports["legacy_0p05"]["2024_plus"]
        legacy_double_later = cost_reports["legacy_0p10"]["2024_plus"]
        legacy_triple_later = cost_reports["legacy_0p15"]["2024_plus"]
        ic_later = cost_reports["ic_mt5_raw_proxy_0p18"]["2024_plus"]
        adverse_later = cost_reports["adverse_0p25"]["2024_plus"]
        severe_later = cost_reports["severe_0p35"]["2024_plus"]
        extreme_later = cost_reports["extreme_0p50"]["2024_plus"]

        pass_legacy = resolved_rate >= 0.98 and cls._passes_cost_gate(legacy_later, 1.20)
        pass_legacy_double = cls._passes_cost_gate(legacy_double_later, 1.10)
        pass_legacy_triple = cls._passes_cost_gate(legacy_triple_later, 1.02)
        pass_ic_proxy = resolved_rate >= 0.98 and cls._passes_cost_gate(ic_later, 1.20)
        pass_adverse = cls._passes_cost_gate(adverse_later, 1.10)
        pass_severe = cls._passes_cost_gate(severe_later, 1.05)
        pass_extreme = cls._passes_cost_gate(extreme_later, 1.00)

        verdict = "M1_BROKER_PROXY_FAILED"
        if pass_ic_proxy and pass_adverse and pass_severe and pass_extreme:
            verdict = "M1_BROKER_PROXY_SURVIVES_EXTREME_STRESS"
        elif pass_ic_proxy and pass_adverse and pass_severe:
            verdict = "M1_BROKER_PROXY_SURVIVES_SEVERE_STRESS"
        elif pass_ic_proxy and pass_adverse:
            verdict = "M1_BROKER_PROXY_SURVIVES_ADVERSE_STRESS"
        elif pass_ic_proxy:
            verdict = "M1_BROKER_PROXY_SURVIVES"

        return {
            "engine_version": ENGINE_VERSION,
            "strategy_code": STRATEGY_CODE,
            "research_question": "Does the frozen v0.4 4CCB candidate survive conservative M1 replay under an IC Markets MT5 Raw-Spread public-data cost proxy and wider adverse-cost margins?",
            "important_note": "This remains a reverse-engineered public-chart hypothesis. The 0.18 broker proxy uses public IC information plus EVE's existing XAU P/L conversion and must still be replaced by exact MT5 Symbol Specification plus measured live/demo spread and slippage telemetry before any live promotion.",
            "broker_proxy": {
                "broker": "IC Markets / IC",
                "platform": "MetaTrader 5",
                "account_model": "Raw Spread proxy",
                "public_average_gold_spread_pips": 1.0,
                "inferred_average_gold_spread_price_units": 0.10,
                "mt5_micro_lot_commission_usd_per_side_rounded": 0.04,
                "mt5_micro_lot_round_turn_commission_usd": 0.08,
                "eve_money_per_1_xau_price_move_at_0p01_lot_usd": 1.0,
                "commission_price_equivalent": 0.08,
                "all_in_proxy_price_units": IC_MT5_RAW_PROXY_COST,
                "status": "PUBLIC_DATA_PROXY_NOT_ACCOUNT_TELEMETRY",
            },
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
            "failure_margin": cls._failure_margin(trades),
            "gates": {
                "legacy_0p05_2024_plus_pass": pass_legacy,
                "legacy_0p10_2024_plus_pass": pass_legacy_double,
                "legacy_0p15_2024_plus_pass": pass_legacy_triple,
                "ic_mt5_raw_proxy_0p18_2024_plus_pass": pass_ic_proxy,
                "adverse_0p25_2024_plus_pass": pass_adverse,
                "severe_0p35_2024_plus_pass": pass_severe,
                "extreme_0p50_2024_plus_pass": pass_extreme,
            },
            "verdict": verdict,
        }
