from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from app.four_ccb_research import _metrics
from app.four_ccb_structure_research import FourCCBH1StructureDiscovery, StructureVariant

ENGINE_VERSION = "0.4.0"
STRATEGY_CODE = "four_ccb_h1_candidate_audit_v0_4"


@dataclass(frozen=True)
class Candidate:
    code: str
    label: str
    variant: StructureVariant


class FourCCBH1CandidateAudit(FourCCBH1StructureDiscovery):
    """Audit a frozen short-list from v0.3 instead of launching another parameter search.

    The purpose is to answer three questions:
    1. Does the mother-bar + small-body idea survive 2025-2026?
    2. Is performance stable across years, sides and sessions?
    3. Which predeclared context filter, if any, improves the early sample and then
       continues to work from 2024 onward without further tuning?
    """

    @staticmethod
    def candidates() -> list[Candidate]:
        common = dict(
            structure="mother_bar_small_bodies",
            mode="plain",
            impulse_atr_min=0.0,
            confirmation="close",
            bias_method="ema_20_50",
        )
        return [
            Candidate(
                "mb_small_ema_close_1p25_1p5r",
                "Mother bar + small bodies · EMA bias · close breakout · 1.25 ATR · 1.5R",
                StructureVariant(box_atr_max=1.25, reward_risk=1.5, **common),
            ),
            Candidate(
                "mb_small_ema_close_1p25_2r",
                "Mother bar + small bodies · EMA bias · close breakout · 1.25 ATR · 2R",
                StructureVariant(box_atr_max=1.25, reward_risk=2.0, **common),
            ),
            Candidate(
                "mb_small_ema_close_1p50_2r",
                "Mother bar + small bodies · EMA bias · close breakout · 1.50 ATR · 2R",
                StructureVariant(box_atr_max=1.50, reward_risk=2.0, **common),
            ),
            Candidate(
                "benchmark_small_body_mom24_touch_2r",
                "Benchmark · small bodies · 24H momentum · touch breakout · 1.50 ATR · 2R",
                StructureVariant(
                    structure="small_bodies",
                    box_atr_max=1.50,
                    mode="plain",
                    impulse_atr_min=0.0,
                    reward_risk=2.0,
                    confirmation="touch",
                    bias_method="momentum_24h",
                ),
            ),
        ]

    @staticmethod
    def _side_matches(side: str, direction: int) -> bool:
        return (side == "buy" and direction > 0) or (side == "sell" and direction < 0)

    def _trade_log(self, variant: StructureVariant) -> tuple[list[dict[str, Any]], dict[str, int]]:
        trades: list[dict[str, Any]] = []
        counters = {"setups": 0, "ambiguous": 0, "time_exits": 0, "bias_filtered": 0}
        end = len(self.candles)
        index = max(self.atr_period, self.impulse_lookback, 73)

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

            counters["setups"] += 1
            breakout = self._find_breakout(index + 4, end, box_high, box_low, variant, 0)
            if breakout is None:
                index += 1
                continue

            entry_index, side, entry = breakout
            if side == "ambiguous":
                counters["ambiguous"] += 1
                index = entry_index + 1
                continue
            if side == "invalidated" or entry is None:
                index = entry_index + 1
                continue
            if not self._side_matches_bias(side, bias_direction):
                counters["bias_filtered"] += 1
                index = entry_index + 1
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
                index = entry_index + 1
                continue

            exit_index, pnl_r, timed_out = trade
            if timed_out:
                counters["time_exits"] += 1

            confirm_index = entry_index - 1 if variant.confirmation == "close" else entry_index
            confirm_index = max(0, confirm_index)
            confirm = self.candles[confirm_index]
            first = self.candles[index]
            last_index = index - 1
            ema_spread_atr = abs(self.ema20[last_index] - self.ema50[last_index]) / atr if atr > 0 else 0.0
            box_mid = (box_high + box_low) / 2.0
            box_atr = (box_high - box_low) / atr if atr > 0 else 0.0
            momentum24 = self._bias_direction(index, "momentum_24h")
            aligned_momentum24 = self._side_matches(side, momentum24)
            on_bias_side_ema20 = (side == "buy" and box_mid >= self.ema20[last_index]) or (
                side == "sell" and box_mid <= self.ema20[last_index]
            )
            if side == "buy":
                breakout_excess_atr = max(0.0, confirm.close - box_high) / atr if atr > 0 else 0.0
            else:
                breakout_excess_atr = max(0.0, box_low - confirm.close) / atr if atr > 0 else 0.0

            trades.append(
                {
                    "setup_time": first.candle_time,
                    "entry_time": self.candles[entry_index].candle_time,
                    "confirm_time": confirm.candle_time,
                    "exit_time": self.candles[exit_index].candle_time,
                    "side": side,
                    "pnl_r": float(pnl_r),
                    "timed_out": bool(timed_out),
                    "box_atr": float(box_atr),
                    "ema_spread_atr": float(ema_spread_atr),
                    "aligned_momentum24": bool(aligned_momentum24),
                    "on_bias_side_ema20": bool(on_bias_side_ema20),
                    "breakout_excess_atr": float(breakout_excess_atr),
                    "confirm_hour_utc": int(confirm.candle_time.hour),
                    "breakout_delay_bars": int(confirm_index - (index + 4) + 1),
                }
            )
            index = max(index + 1, exit_index + 1)

        return trades, counters

    @staticmethod
    def _trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
        pnls = [float(t["pnl_r"]) for t in trades]
        return _metrics(pnls, len(trades), 0, sum(bool(t["timed_out"]) for t in trades))

    @classmethod
    def _group_metrics(cls, trades: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trade in trades:
            groups[key_fn(trade)].append(trade)
        return {key: cls._trade_metrics(items) for key, items in sorted(groups.items())}

    @staticmethod
    def _session(trade: dict[str, Any]) -> str:
        hour = int(trade["confirm_hour_utc"])
        if 0 <= hour <= 6:
            return "00-06_asia"
        if 7 <= hour <= 12:
            return "07-12_london"
        if 13 <= hour <= 16:
            return "13-16_london_ny"
        if 17 <= hour <= 21:
            return "17-21_ny_late"
        return "22-23_rollover"

    @staticmethod
    def _filter_specs() -> dict[str, Callable[[dict[str, Any]], bool]]:
        return {
            "all": lambda t: True,
            "core_07_16": lambda t: 7 <= int(t["confirm_hour_utc"]) <= 16,
            "ema_strength_ge_0p15": lambda t: float(t["ema_spread_atr"]) >= 0.15,
            "ema_strength_ge_0p25": lambda t: float(t["ema_spread_atr"]) >= 0.25,
            "box_le_1p00_atr": lambda t: float(t["box_atr"]) <= 1.00,
            "breakout_excess_ge_0p10": lambda t: float(t["breakout_excess_atr"]) >= 0.10,
            "breakout_excess_ge_0p20": lambda t: float(t["breakout_excess_atr"]) >= 0.20,
            "box_on_bias_side_ema20": lambda t: bool(t["on_bias_side_ema20"]),
            "ema_and_momentum24_agree": lambda t: bool(t["aligned_momentum24"]),
            "core_plus_ema_strength": lambda t: 7 <= int(t["confirm_hour_utc"]) <= 16 and float(t["ema_spread_atr"]) >= 0.15,
        }

    @classmethod
    def _context_filter_audit(cls, trades: list[dict[str, Any]]) -> dict[str, Any]:
        early = [t for t in trades if int(t["entry_time"].year) <= 2023]
        later = [t for t in trades if int(t["entry_time"].year) >= 2024]
        rows: list[dict[str, Any]] = []
        for name, predicate in cls._filter_specs().items():
            early_filtered = [t for t in early if predicate(t)]
            later_filtered = [t for t in later if predicate(t)]
            early_metrics = cls._trade_metrics(early_filtered)
            later_metrics = cls._trade_metrics(later_filtered)
            rows.append({"filter": name, "early_2020_2023": early_metrics, "later_2024_plus": later_metrics})

        eligible = [
            row
            for row in rows
            if row["filter"] != "all" and int(row["early_2020_2023"]["trades"]) >= 25
        ]
        if eligible:
            selected = max(
                eligible,
                key=lambda row: (
                    float(row["early_2020_2023"]["selection_score"]),
                    float(row["early_2020_2023"]["expectancy_r"]),
                    float(row["early_2020_2023"]["profit_factor"] or 0.0),
                ),
            )
        else:
            selected = next(row for row in rows if row["filter"] == "all")

        later_metrics = selected["later_2024_plus"]
        later_pf = later_metrics["profit_factor"]
        pass_later = (
            int(later_metrics["trades"]) >= 20
            and float(later_metrics["net_r"]) > 0
            and float(later_metrics["expectancy_r"]) > 0
            and later_pf is not None
            and float(later_pf) >= 1.10
        )
        return {
            "selection_rule": "choose one predeclared filter using only 2020-2023; report it unchanged on 2024+",
            "selected": selected,
            "later_pass": pass_later,
            "all_filters": rows,
        }

    @classmethod
    def _candidate_report(cls, candidate: Candidate, trades: list[dict[str, Any]], counters: dict[str, int]) -> dict[str, Any]:
        by_year = cls._group_metrics(trades, lambda t: str(t["entry_time"].year))
        profitable_years = sum(float(m["net_r"]) > 0 for m in by_year.values())
        losing_years = sum(float(m["net_r"]) < 0 for m in by_year.values())
        recent = [t for t in trades if int(t["entry_time"].year) >= 2025]
        return {
            "code": candidate.code,
            "label": candidate.label,
            "rules": candidate.variant.as_dict(),
            "overall": cls._trade_metrics(trades),
            "2025_2026": cls._trade_metrics(recent),
            "yearly": by_year,
            "year_stability": {"profitable_years": profitable_years, "losing_years": losing_years},
            "side": cls._group_metrics(trades, lambda t: str(t["side"])),
            "session_utc": cls._group_metrics(trades, cls._session),
            "breakout_delay": cls._group_metrics(trades, lambda t: f"bar_{t['breakout_delay_bars']}"),
            "counters": counters,
            "context_filter_audit": cls._context_filter_audit(trades) if candidate.code == "mb_small_ema_close_1p25_2r" else None,
        }

    def run(self) -> dict[str, Any]:
        if len(self.candles) < 1000:
            raise RuntimeError("At least 1,000 H1 candles are required for the fixed 4CCB candidate audit")

        reports: list[dict[str, Any]] = []
        for candidate in self.candidates():
            trades, counters = self._trade_log(candidate.variant)
            reports.append(self._candidate_report(candidate, trades, counters))

        primary = next(item for item in reports if item["code"] == "mb_small_ema_close_1p25_2r")
        recent = primary["2025_2026"]
        recent_pf = recent["profit_factor"]
        primary_recent_pass = (
            int(recent["trades"]) >= 20
            and float(recent["net_r"]) > 0
            and float(recent["expectancy_r"]) > 0
            and recent_pf is not None
            and float(recent_pf) >= 1.10
        )
        context_pass = bool(primary["context_filter_audit"]["later_pass"])

        verdict = "KEEP_RESEARCHING_CONTEXT"
        if primary_recent_pass and context_pass:
            verdict = "PROMOTE_TO_EXECUTION_VALIDATION"
        elif not primary_recent_pass and not context_pass:
            verdict = "PRIMARY_CANDIDATE_FAILED_ROBUSTNESS"

        return {
            "engine_version": ENGINE_VERSION,
            "strategy_code": STRATEGY_CODE,
            "research_question": "Does the frozen mother-bar + small-body + EMA-bias 4CCB candidate survive year-by-year and recent-history audit, and can one predeclared context filter improve robustness?",
            "important_note": "This is a reverse-engineered public-chart research hypothesis, not a claim about private/VIP rules. Late history has been seen by earlier experiments, so 2025-2026 is a robustness check rather than a pristine holdout.",
            "data": {
                "h1_candles": len(self.candles),
                "first_candle": self.candles[0].candle_time.isoformat(),
                "last_candle": self.candles[-1].candle_time.isoformat(),
            },
            "protocol": {
                "candidate_count": len(reports),
                "primary_candidate": "mb_small_ema_close_1p25_2r",
                "no_global_parameter_search": True,
                "context_filter_selection": "predeclared filters selected on 2020-2023 only, then frozen on 2024+",
                "execution_warning": "H1 OHLC only; lower-timeframe/tick replay required before live automation",
            },
            "candidates": reports,
            "primary_recent_pass": primary_recent_pass,
            "context_filter_later_pass": context_pass,
            "verdict": verdict,
        }
