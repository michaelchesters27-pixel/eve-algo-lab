from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.backtesting.comex_closing_momentum import (
    ComexClosingMomentumBacktester,
    ComexClosingMomentumParameters,
)
from app.backtesting.fixed_ladder_v261 import Candle, FixedLadderParameters, FixedLadderV261Backtester
from app.backtesting.gold_h4_trend import (
    GoldH4TrendBacktester,
    GoldH4TrendParameters,
    build_trend_events,
)
from app.backtesting.gold_h1_trend import (
    GoldH1TrendBacktester,
    GoldH1TrendParameters,
    build_trend_events as build_h1_trend_events,
)
from app.backtesting.gold_session_anomaly import (
    GoldSessionAnomalyBacktester,
    GoldSessionAnomalyParameters,
)
from app.backtesting.liquidity_basket import LiquidityBasketBacktester, LiquidityBasketParameters
from app.backtesting.london_opening_range import LondonOpeningRangeBacktester, LondonOpeningRangeParameters
from app.backtesting.metrics import calculate_metrics
from app.backtesting.new_york_morning_momentum import (
    NewYorkMorningMomentumBacktester,
    NewYorkMorningMomentumParameters,
)
from app.services.supabase_repo import SupabaseRepository

logger = logging.getLogger(__name__)

STRATEGY_SLUG = "eve-fixed-ladder-v2-61"
STRATEGY_NAME = "EVE Twelve Data Fixed Ladder v2.61"
STRATEGY_VERSION = "2.61"
SOURCE_SHA256 = "f033bc756b8a066b8fdfe780ca36fe82363b3b70c2e4dd4a15e7d57546d02da9"
LIQUIDITY_STRATEGY_SLUG = "eve-liquidity-basket-v1"
LIQUIDITY_STRATEGY_NAME = "EVE Liquidity Basket v1"
LIQUIDITY_STRATEGY_VERSION = "1.0"
LIQUIDITY_CONTINUATION_STRATEGY_SLUG = "eve-liquidity-continuation-v1"
LIQUIDITY_CONTINUATION_STRATEGY_NAME = "EVE Liquidity Continuation v1"
LIQUIDITY_CONTINUATION_STRATEGY_VERSION = "1.0"
LIQUIDITY_SOURCE_SHA256 = "e05ab200478844a8822c564fba7775dea52a32869807e8704a5d18f9b743217a"
LONDON_STRATEGY_SLUG = "eve-london-opening-range-v1"
LONDON_STRATEGY_NAME = "EVE London Opening Range v1"
LONDON_STRATEGY_VERSION = "1.0"
LONDON_SOURCE_SHA256 = "28c65ec6f107790e74598dc04aed96f844c7758faba04a396c75450e8efd4681"
NEW_YORK_MOMENTUM_STRATEGY_SLUG = "eve-new-york-morning-momentum-v1"
NEW_YORK_MOMENTUM_STRATEGY_NAME = "EVE New York Morning Momentum v1"
NEW_YORK_MOMENTUM_STRATEGY_VERSION = "1.0"
NEW_YORK_MOMENTUM_SOURCE_SHA256 = "a2896828482bb3ff1fe8d8ef165d0038e9ff0e737ebdb02a2c20f14f2f641fc0"
COMEX_CLOSING_MOMENTUM_STRATEGY_SLUG = "eve-comex-closing-momentum-v1"
COMEX_CLOSING_MOMENTUM_STRATEGY_NAME = "EVE COMEX Closing Momentum v1"
COMEX_CLOSING_MOMENTUM_STRATEGY_VERSION = "1.0"
COMEX_CLOSING_MOMENTUM_SOURCE_SHA256 = "f2af0dd7564547996831b2db8525175290d881a03f4b8882b66cfac0be239281"
GOLD_OVERNIGHT_STRATEGY_SLUG = "eve-gold-overnight-long-v1"
GOLD_OVERNIGHT_STRATEGY_NAME = "EVE Gold Overnight Long v1"
COMEX_DAY_SHORT_STRATEGY_SLUG = "eve-comex-day-short-v1"
COMEX_DAY_SHORT_STRATEGY_NAME = "EVE COMEX Day Short v1"
ASIA_SESSION_LONG_STRATEGY_SLUG = "eve-asia-session-long-v1"
ASIA_SESSION_LONG_STRATEGY_NAME = "EVE Asia Session Long v1"
SHANGHAI_DAY_LONG_STRATEGY_SLUG = "eve-shanghai-day-long-v1"
SHANGHAI_DAY_LONG_STRATEGY_NAME = "EVE Shanghai Day Long v1"
GOLD_ABNORMAL_MOMENTUM_STRATEGY_SLUG = "eve-gold-abnormal-momentum-v1"
GOLD_ABNORMAL_MOMENTUM_STRATEGY_NAME = "EVE Gold Abnormal Momentum v1"
GOLD_INTRADAY_CLOSE_MOMENTUM_STRATEGY_SLUG = "eve-gold-intraday-close-momentum-v1"
GOLD_INTRADAY_CLOSE_MOMENTUM_STRATEGY_NAME = "EVE Gold Intraday Close Momentum v1"
GOLD_HIGH_VOL_CLOSE_MOMENTUM_STRATEGY_SLUG = "eve-gold-high-vol-close-momentum-v1"
GOLD_HIGH_VOL_CLOSE_MOMENTUM_STRATEGY_NAME = "EVE Gold High-Volatility Close Momentum v1"
GOLD_REST_OF_DAY_CLOSE_MOMENTUM_STRATEGY_SLUG = "eve-gold-rest-of-day-close-momentum-v1"
GOLD_REST_OF_DAY_CLOSE_MOMENTUM_STRATEGY_NAME = "EVE Gold Rest-of-Day Close Momentum v1"
GOLD_ETF_INTRADAY_SHORT_STRATEGY_SLUG = "eve-gold-etf-hours-intraday-short-v1"
GOLD_ETF_INTRADAY_SHORT_STRATEGY_NAME = "EVE Gold ETF-Hours Intraday Short v1"
GOLD_ETF_OVERNIGHT_LONG_STRATEGY_SLUG = "eve-gold-etf-hours-overnight-long-v1"
GOLD_ETF_OVERNIGHT_LONG_STRATEGY_NAME = "EVE Gold ETF-Hours Overnight Long v1"
GOLD_SESSION_ANOMALY_STRATEGY_VERSION = "1.0"
GOLD_SESSION_ANOMALY_SOURCE_SHA256 = "b36df1f2d6593eedfca8374353a58834ccddf6cc31d27c972e30ea7ad1ef355f"
GOLD_H4_STRATEGY_SLUG = "eve-gold-h4-trend-55-20-v1"
GOLD_H4_STRATEGY_NAME = "EVE Gold H4 Trend 55/20 v1"
GOLD_H4_STRATEGY_VERSION = "1.0"
GOLD_H4_SOURCE_SHA256 = "db0f8e56d4ea447590046cfb20799c1e0b8e9df1ce22320af612e051f735f608"
GOLD_H1_STRATEGY_SLUG = "eve-gold-h1-trend-55-20-v1"
GOLD_H1_STRATEGY_NAME = "EVE Gold H1 Trend 55/20 v1"
GOLD_H1_STRATEGY_VERSION = "1.0"
GOLD_H1_SOURCE_SHA256 = "2ef21bb380425a83c7991701cc731519623429bfdcb661cc5577f0320b2d1c02"
LIQUIDITY_LOCKED_SETTING_KEYS = (
    "strategy",
    "entry_model",
    "symbol",
    "starting_balance",
    "positions_per_basket",
    "fixed_lot",
    "lookback_candles",
    "trend_period",
    "use_trend_filter",
    "minimum_sweep_price",
    "profit_target_money",
    "basket_stop_money",
    "maximum_hold_minutes",
    "cooldown_candles",
    "spread_price",
    "commission_per_001_lot",
    "slippage_price",
    "money_per_price_per_001_lot",
    "path_mode",
)
LONDON_LOCKED_SETTING_KEYS = (
    "strategy",
    "symbol",
    "starting_balance",
    "risk_percent",
    "breakout_buffer_fraction",
    "reward_risk",
    "minimum_lot",
    "lot_step",
    "maximum_lot",
    "timezone_name",
    "range_start_hour",
    "range_start_minute",
    "range_minutes",
    "entry_cutoff_hour",
    "entry_cutoff_minute",
    "force_exit_hour",
    "force_exit_minute",
    "spread_price",
    "commission_per_001_lot",
    "slippage_price",
    "money_per_price_per_001_lot",
    "path_mode",
)
NEW_YORK_MOMENTUM_LOCKED_SETTING_KEYS = (
    "strategy",
    "symbol",
    "starting_balance",
    "risk_percent",
    "minimum_lot",
    "lot_step",
    "maximum_lot",
    "timezone_name",
    "signal_start_hour",
    "signal_start_minute",
    "signal_minutes",
    "entry_hour",
    "entry_minute",
    "force_exit_hour",
    "force_exit_minute",
    "spread_price",
    "commission_per_001_lot",
    "slippage_price",
    "money_per_price_per_001_lot",
    "path_mode",
)
COMEX_CLOSING_MOMENTUM_LOCKED_SETTING_KEYS = (
    "strategy",
    "symbol",
    "starting_balance",
    "fixed_lot",
    "maximum_loss_percent",
    "timezone_name",
    "reference_hour",
    "reference_minute",
    "entry_hour",
    "entry_minute",
    "exit_hour",
    "exit_minute",
    "spread_price",
    "commission_per_001_lot",
    "slippage_price",
    "money_per_price_per_001_lot",
    "path_mode",
)
GOLD_SESSION_ANOMALY_LOCKED_SETTING_KEYS = (
    "strategy",
    "session_leg",
    "symbol",
    "starting_balance",
    "fixed_lot",
    "maximum_loss_percent",
    "timezone_name",
    "day_open_hour",
    "day_open_minute",
    "settlement_hour",
    "settlement_minute",
    "asia_entry_hour",
    "asia_entry_minute",
    "asia_exit_timezone_name",
    "shanghai_entry_hour",
    "shanghai_entry_minute",
    "asia_exit_hour",
    "asia_exit_minute",
    "abnormal_timezone_name",
    "abnormal_lookback_days",
    "abnormal_sigma",
    "abnormal_negative_entry_hour",
    "abnormal_negative_entry_minute",
    "abnormal_positive_entry_hour",
    "abnormal_positive_entry_minute",
    "abnormal_exit_hour",
    "abnormal_exit_minute",
    "intraday_predictor_start_hour",
    "intraday_predictor_start_minute",
    "intraday_predictor_end_hour",
    "intraday_predictor_end_minute",
    "intraday_volatility_lookback_days",
    "intraday_entry_hour",
    "intraday_entry_minute",
    "intraday_exit_hour",
    "intraday_exit_minute",
    "etf_market_open_hour",
    "etf_market_open_minute",
    "etf_market_close_hour",
    "etf_market_close_minute",
    "long_overnight_cost_per_001_lot",
    "triple_swap_weekday",
    "spread_price",
    "commission_per_001_lot",
    "slippage_price",
    "money_per_price_per_001_lot",
    "path_mode",
)
GOLD_H4_LOCKED_SETTING_KEYS = (
    "strategy",
    "symbol",
    "starting_balance",
    "entry_lookback_h4",
    "exit_lookback_h4",
    "daily_trend_lookback",
    "atr_period_h4",
    "atr_multiplier",
    "risk_percent",
    "minimum_lot",
    "lot_step",
    "maximum_lot",
    "spread_price",
    "commission_per_001_lot",
    "slippage_price",
    "money_per_price_per_001_lot",
    "overnight_long_cost_per_001_lot",
    "overnight_short_cost_per_001_lot",
    "triple_swap_weekday",
    "path_mode",
)
GOLD_H1_LOCKED_SETTING_KEYS = (
    "strategy",
    "symbol",
    "starting_balance",
    "entry_lookback_h1",
    "exit_lookback_h1",
    "daily_trend_lookback",
    "atr_period_h1",
    "atr_multiplier",
    "risk_percent",
    "minimum_lot",
    "lot_step",
    "maximum_lot",
    "spread_price",
    "commission_per_001_lot",
    "slippage_price",
    "money_per_price_per_001_lot",
    "overnight_long_cost_per_001_lot",
    "overnight_short_cost_per_001_lot",
    "triple_swap_weekday",
    "path_mode",
)


def liquidity_identity(entry_model: str) -> dict[str, str]:
    if entry_model == "breakout_continuation":
        return {
            "code": "liquidity_continuation",
            "name": LIQUIDITY_CONTINUATION_STRATEGY_NAME,
            "slug": LIQUIDITY_CONTINUATION_STRATEGY_SLUG,
            "version": LIQUIDITY_CONTINUATION_STRATEGY_VERSION,
            "description": "Four equal XAU/USD M1 positions after a confirmed close beyond liquidity in the breakout direction.",
            "signal": "close beyond the previous N-candle high/low with a directional candle and EMA alignment",
            "note": "Second measurable liquidity hypothesis. It follows confirmed breakout direction after the sweep-reversal version failed development testing.",
        }
    return {
        "code": "liquidity_basket",
        "name": LIQUIDITY_STRATEGY_NAME,
        "slug": LIQUIDITY_STRATEGY_SLUG,
        "version": LIQUIDITY_STRATEGY_VERSION,
        "description": "Four equal XAU/USD M1 positions after a confirmed liquidity sweep, managed as one money basket.",
        "signal": "sweep previous N-candle high/low and close back inside with rejection candle",
        "note": "Initial measurable reconstruction of the four-position liquidity basket idea. Research only; no MT5 EA exists yet.",
    }


def liquidity_settings_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Compare every rule, cost and risk input that can change a result."""

    return all(first.get(key) == second.get(key) for key in LIQUIDITY_LOCKED_SETTING_KEYS)


def london_settings_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Require an untouched run to reuse every London rule and cost input."""

    return all(first.get(key) == second.get(key) for key in LONDON_LOCKED_SETTING_KEYS)


def new_york_momentum_settings_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Require the untouched daily-momentum run to reuse every rule and cost."""

    return all(first.get(key) == second.get(key) for key in NEW_YORK_MOMENTUM_LOCKED_SETTING_KEYS)


def comex_closing_momentum_settings_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Require the untouched COMEX run to reuse every frozen rule and cost."""

    return all(first.get(key) == second.get(key) for key in COMEX_CLOSING_MOMENTUM_LOCKED_SETTING_KEYS)


def gold_session_anomaly_identity(session_leg: str) -> dict[str, str]:
    if session_leg == "gld_high_vol_fifth_half_hour_momentum":
        return {
            "code": "gold_high_vol_close_momentum",
            "name": GOLD_HIGH_VOL_CLOSE_MOMENTUM_STRATEGY_NAME,
            "slug": GOLD_HIGH_VOL_CLOSE_MOMENTUM_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD closing-half-hour trade only when the complete 11:30-12:00 New York window is more volatile than the median of its previous 60 complete windows.",
            "entry": "at 15:30 New York, follow the 11:30-12:00 return only when that window's realized volatility exceeds the causal 60-window median",
            "exit": "close at the exact 16:00 New York M1 open",
        }
    if session_leg == "etf_intraday_short":
        return {
            "code": "gold_etf_intraday_short",
            "name": GOLD_ETF_INTRADAY_SHORT_STRATEGY_NAME,
            "slug": GOLD_ETF_INTRADAY_SHORT_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD short from the New York ETF market open to its close on every complete weekday.",
            "entry": "sell the exact 09:30 New York M1 open on Monday through Friday",
            "exit": "close at the exact 16:00 New York M1 open",
        }
    if session_leg == "etf_overnight_long":
        return {
            "code": "gold_etf_overnight_long",
            "name": GOLD_ETF_OVERNIGHT_LONG_STRATEGY_NAME,
            "slug": GOLD_ETF_OVERNIGHT_LONG_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD long from the New York ETF market close to the next eligible market open.",
            "entry": "buy the exact 16:00 New York M1 open on Monday through Friday",
            "exit": "close at the next eligible weekday's exact 09:30 New York M1 open",
        }
    if session_leg == "rest_of_day_close_momentum":
        return {
            "code": "gold_rest_of_day_close_momentum",
            "name": GOLD_REST_OF_DAY_CLOSE_MOMENTUM_STRATEGY_NAME,
            "slug": GOLD_REST_OF_DAY_CLOSE_MOMENTUM_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD closing-half-hour trade each complete New York weekday, directed by the move since the previous 16:00 close.",
            "entry": "at 15:30 New York, buy when price is above the previous eligible 16:00 close; otherwise sell",
            "exit": "close at the exact 16:00 New York M1 open",
        }
    if session_leg == "gld_fifth_half_hour_momentum":
        return {
            "code": "gold_intraday_close_momentum",
            "name": GOLD_INTRADAY_CLOSE_MOMENTUM_STRATEGY_NAME,
            "slug": GOLD_INTRADAY_CLOSE_MOMENTUM_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD closing-half-hour trade each complete New York weekday, directed by the 11:30-12:00 return.",
            "entry": "at 15:30 New York, buy after a positive 11:30-12:00 return; otherwise sell",
            "exit": "close at the exact 16:00 New York M1 open",
        }
    if session_leg == "abnormal_momentum":
        return {
            "code": "gold_abnormal_momentum",
            "name": GOLD_ABNORMAL_MOMENTUM_STRATEGY_NAME,
            "slug": GOLD_ABNORMAL_MOMENTUM_STRATEGY_SLUG,
            "description": "At most one fixed-size XAU/USD trade when the current GMT+3 day exceeds a causal two-sigma return threshold.",
            "entry": "short a negative abnormal return at 17:00 GMT+3, otherwise buy a positive abnormal return at 19:00 GMT+3",
            "exit": "close at the 23:59 GMT+3 M1 close",
        }
    if session_leg == "shanghai_day_long":
        return {
            "code": "shanghai_day_long",
            "name": SHANGHAI_DAY_LONG_STRATEGY_NAME,
            "slug": SHANGHAI_DAY_LONG_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD long during the official Shanghai Gold Exchange day session.",
            "entry": "buy the exact 09:00 Asia/Shanghai M1 open on Monday through Friday",
            "exit": "close at the exact 15:30 Asia/Shanghai M1 open",
        }
    if session_leg == "asia_long":
        return {
            "code": "asia_session_long",
            "name": ASIA_SESSION_LONG_STRATEGY_NAME,
            "slug": ASIA_SESSION_LONG_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD long from the New York post-rollover reopen through the Shanghai gold close.",
            "entry": "buy the exact 18:00 New York M1 open on Sunday through Thursday",
            "exit": "close at the exact 15:30 Asia/Shanghai M1 open for the associated Monday-through-Friday session",
        }
    if session_leg == "day_short":
        return {
            "code": "comex_day_short",
            "name": COMEX_DAY_SHORT_STRATEGY_NAME,
            "slug": COMEX_DAY_SHORT_STRATEGY_SLUG,
            "description": "One fixed-size XAU/USD short at the COMEX day-session open, closed at settlement.",
            "entry": "sell the exact 08:20 New York M1 open",
            "exit": "close at the exact 13:30 New York M1 open",
        }
    return {
        "code": "gold_overnight_long",
        "name": GOLD_OVERNIGHT_STRATEGY_NAME,
        "slug": GOLD_OVERNIGHT_STRATEGY_SLUG,
        "description": "One fixed-size XAU/USD long from COMEX settlement to the next eligible day-session open.",
        "entry": "buy the exact 13:30 New York M1 open",
        "exit": "close at the next eligible weekday's exact 08:20 New York M1 open",
    }


def gold_session_anomaly_settings_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Require untouched replay to reuse every frozen session rule, cost and risk input."""

    return all(first.get(key) == second.get(key) for key in GOLD_SESSION_ANOMALY_LOCKED_SETTING_KEYS)


def gold_h4_settings_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Require the untouched H4 trend run to reuse every rule and cost."""

    return all(first.get(key) == second.get(key) for key in GOLD_H4_LOCKED_SETTING_KEYS)


def gold_h1_settings_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Require the untouched H1 trend run to reuse every rule and cost."""

    return all(first.get(key) == second.get(key) for key in GOLD_H1_LOCKED_SETTING_KEYS)


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


def _liquidity_verdict(
    *,
    net_profit: float,
    profit_factor: float | None,
    expectancy: float,
    max_drawdown_percent: float,
    total_baskets: int,
    test_segment: str,
    locked_development_run_id: str | None = None,
    account_ruined: bool = False,
    unit_label: str = "baskets",
) -> dict[str, Any]:
    pf = float(profit_factor or 0.0)
    enough_evidence = total_baskets >= 100
    profitable = net_profit > 0 and expectancy > 0 and pf >= 1.20
    controlled_drawdown = max_drawdown_percent <= 20.0
    passed = enough_evidence and profitable and controlled_drawdown
    if account_ruined:
        return {
            "code": "account_ruined",
            "label": "ACCOUNT BLOWN — FAILED",
            "tone": "failed",
            "summary": "The strategy exhausted the test account. EVE stopped the replay at zero instead of reporting an impossible negative balance.",
            "next_action": "Reject this strategy. Do not build an EA or run the untouched period.",
        }
    if test_segment == "untouched" and not locked_development_run_id:
        return {
            "code": "unlocked_untouched",
            "label": "INVALID UNTOUCHED TEST — NO PASS",
            "tone": "failed",
            "summary": "No completed development run with identical settings was linked to this result.",
            "next_action": "Run the development first-two-thirds test, freeze every setting, then run untouched again.",
        }
    if passed and test_segment == "untouched":
        return {
            "code": "untouched_pass",
            "label": "UNTOUCHED PASS — VERIFY IN MT5",
            "tone": "promising",
            "summary": "The locked settings stayed profitable on the untouched final third with controlled drawdown.",
            "next_action": "Recreate the frozen rules as an EA and verify them with MT5 real ticks, then demo forward-test.",
        }
    if passed and test_segment == "development":
        return {
            "code": "promising",
            "label": "PROMISING — RUN UNTOUCHED TEST",
            "tone": "promising",
            "summary": "The strategy rules cleared EVE's minimum profit, evidence and drawdown gates.",
            "next_action": "Lock these settings and run the untouched final-third test without changing them.",
        }
    if passed:
        return {
            "code": "exploratory_pass",
            "label": "EXPLORATORY PASS — NOT PROOF",
            "tone": "warning",
            "summary": "The selected period cleared the numeric gates, but it was not the locked development-to-untouched sequence.",
            "next_action": "Run the development first two-thirds, then the untouched final third with identical settings.",
        }
    if total_baskets < 100:
        return {
            "code": "insufficient_evidence",
            "label": "NOT ENOUGH TRADES — NO VERDICT",
            "tone": "waiting",
            "summary": f"Only {total_baskets} completed {unit_label} were found; EVE requires at least 100 before judging the idea.",
            "next_action": "Use a longer date range. Do not build the EA from this result.",
        }
    if net_profit > 0 and pf >= 1.0:
        return {
            "code": "mixed",
            "label": "MIXED — DO NOT BUILD YET",
            "tone": "warning",
            "summary": "The test made money, but profit factor, expectancy or drawdown failed EVE's safety gate.",
            "next_action": f"Inspect the losing {unit_label} and test one controlled rule change at a time.",
        }
    return {
        "code": "failed",
        "label": "FAILED — DO NOT BUILD EA",
        "tone": "failed",
        "summary": "The complete historical sequence did not show a usable edge after costs.",
        "next_action": "Reject these settings. Change the entry hypothesis before testing again.",
    }


def _daily_momentum_verdict(
    *,
    net_profit: float,
    profit_factor: float | None,
    expectancy: float,
    max_drawdown_percent: float,
    total_trades: int,
    yearly_net: dict[str, float],
    test_segment: str,
    locked_development_run_id: str | None = None,
    account_ruined: bool = False,
) -> dict[str, Any]:
    """Pre-declared proof gate for the once-per-day New York hypothesis."""

    pf = float(profit_factor or 0.0)
    profitable_years = sum(float(value) > 0 for value in yearly_net.values())
    enough_evidence = total_trades >= 500
    repeatable = profitable_years >= 3
    profitable = net_profit > 0 and expectancy > 0 and pf >= 1.20
    controlled_drawdown = max_drawdown_percent <= 15.0
    passed = enough_evidence and repeatable and profitable and controlled_drawdown
    if account_ruined:
        return {
            "code": "account_ruined",
            "label": "ACCOUNT BLOWN — FAILED",
            "tone": "failed",
            "summary": "The once-a-day strategy exhausted the test account. EVE stopped at zero.",
            "next_action": "Reject it. Do not open the untouched period or build an EA.",
        }
    if test_segment == "untouched" and not locked_development_run_id:
        return {
            "code": "unlocked_untouched",
            "label": "INVALID UNTOUCHED TEST — NO PASS",
            "tone": "failed",
            "summary": "No completed development run with identical frozen rules was linked.",
            "next_action": "Run Development first, then reuse its exact settings.",
        }
    if passed and test_segment == "untouched":
        return {
            "code": "untouched_pass",
            "label": "UNTOUCHED PASS — STRESS TEST NEXT",
            "tone": "promising",
            "summary": "The frozen once-a-day rules stayed profitable on unseen history with controlled drawdown.",
            "next_action": "Verify with MT5 real ticks, adverse-cost tests and a demo forward test before considering live use.",
        }
    if passed and test_segment == "development":
        return {
            "code": "promising",
            "label": "PROMISING — RUN UNTOUCHED TEST",
            "tone": "promising",
            "summary": "Development cleared 500 trades, PF 1.20, positive expectancy, three profitable years and 15% drawdown.",
            "next_action": "Freeze every setting and run the untouched final third.",
        }
    if passed:
        return {
            "code": "exploratory_pass",
            "label": "EXPLORATORY PASS — NOT PROOF",
            "tone": "warning",
            "summary": "This period cleared the numbers but not the locked development-to-untouched sequence.",
            "next_action": "Run Development first, then the untouched final third unchanged.",
        }
    failed_gates: list[str] = []
    if total_trades < 500:
        failed_gates.append(f"only {total_trades} of 500 required trades")
    if pf < 1.20:
        failed_gates.append(f"profit factor {pf:.3f} below 1.20")
    if net_profit <= 0 or expectancy <= 0:
        failed_gates.append("profit or expectancy not positive")
    if max_drawdown_percent > 15.0:
        failed_gates.append(f"drawdown {max_drawdown_percent:.2f}% above 15%")
    if profitable_years < 3:
        failed_gates.append(f"only {profitable_years} profitable calendar years")
    evidence_only = total_trades < 500 and net_profit > 0 and expectancy > 0 and pf >= 1.20 and controlled_drawdown
    if evidence_only:
        return {
            "code": "insufficient_evidence",
            "label": "NOT ENOUGH TRADES — NO VERDICT",
            "tone": "waiting",
            "summary": f"Only {total_trades} completed trades were found; EVE locked the minimum at 500 before this run.",
            "next_action": "Do not build an EA from this sample.",
        }
    return {
        "code": "failed",
        "label": "FAILED — DO NOT BUILD EA",
        "tone": "failed",
        "summary": "The locked daily strategy failed: " + "; ".join(failed_gates) + ".",
        "next_action": "Reject v1. Do not tune it on the same development result.",
    }


def _high_vol_close_momentum_verdict(
    *,
    net_profit: float,
    profit_factor: float | None,
    expectancy: float,
    max_drawdown_percent: float,
    total_trades: int,
    yearly_net: dict[str, float],
    test_segment: str,
    locked_development_run_id: str | None = None,
    account_ruined: bool = False,
) -> dict[str, Any]:
    """Frozen gate sized for the predeclared above-median volatility subset."""

    pf = float(profit_factor or 0.0)
    profitable_years = sum(float(value) > 0 for value in yearly_net.values())
    untouched = test_segment == "untouched"
    required_trades = 200 if untouched else 400
    required_years = 2 if untouched else 3
    passed = (
        not account_ruined
        and total_trades >= required_trades
        and profitable_years >= required_years
        and net_profit > 0
        and expectancy > 0
        and pf >= 1.20
        and max_drawdown_percent <= 15.0
    )
    if account_ruined:
        return {
            "code": "account_ruined",
            "label": "ACCOUNT BLOWN — FAILED",
            "tone": "failed",
            "summary": "The high-volatility close-momentum strategy exhausted the test account.",
            "next_action": "Reject it. Do not open untouched data or build an EA.",
        }
    if untouched and not locked_development_run_id:
        return {
            "code": "unlocked_untouched",
            "label": "INVALID UNTOUCHED TEST — NO PASS",
            "tone": "failed",
            "summary": "No passing development run with identical frozen rules was linked.",
            "next_action": "Run Development first, then reuse every setting unchanged.",
        }
    if passed and untouched:
        return {
            "code": "untouched_pass",
            "label": "UNTOUCHED PASS — VERIFY IN MT5",
            "tone": "promising",
            "summary": "The unchanged high-volatility rule remained profitable on unseen history after costs.",
            "next_action": "Verify with broker-specific MT5 real ticks, adverse costs and a demo forward test.",
        }
    if passed and test_segment == "development":
        return {
            "code": "promising",
            "label": "PROMISING — RUN UNTOUCHED TEST",
            "tone": "promising",
            "summary": "Development cleared the predeclared 400-trade, repeatability, PF 1.20 and drawdown gates.",
            "next_action": "Freeze every setting and run the untouched final third.",
        }
    if passed:
        return {
            "code": "exploratory_pass",
            "label": "EXPLORATORY PASS — NOT PROOF",
            "tone": "warning",
            "summary": "This period cleared the numbers outside the locked development-to-untouched sequence.",
            "next_action": "Run Development first, then the untouched final third unchanged.",
        }

    failed_gates: list[str] = []
    if total_trades < required_trades:
        failed_gates.append(f"only {total_trades} of {required_trades} required trades")
    if profitable_years < required_years:
        failed_gates.append(f"only {profitable_years} of {required_years} required profitable years")
    if pf < 1.20:
        failed_gates.append(f"profit factor {pf:.3f} below 1.20")
    if net_profit <= 0 or expectancy <= 0:
        failed_gates.append("profit or expectancy not positive")
    if max_drawdown_percent > 15.0:
        failed_gates.append(f"drawdown {max_drawdown_percent:.2f}% above 15%")
    evidence_only = (
        total_trades < required_trades
        and profitable_years >= required_years
        and net_profit > 0
        and expectancy > 0
        and pf >= 1.20
        and max_drawdown_percent <= 15.0
    )
    if evidence_only:
        return {
            "code": "insufficient_evidence",
            "label": "NOT ENOUGH TRADES — NO VERDICT",
            "tone": "waiting",
            "summary": f"Only {total_trades} completed high-volatility trades were found; EVE locked the minimum at {required_trades} before this run.",
            "next_action": "Do not build an EA from this sample.",
        }
    return {
        "code": "failed",
        "label": "FAILED — DO NOT BUILD EA",
        "tone": "failed",
        "summary": "The locked high-volatility strategy failed: " + "; ".join(failed_gates) + ".",
        "next_action": "Reject v1. Do not tune the volatility cutoff on this result.",
    }


def _abnormal_momentum_verdict(
    *,
    net_profit: float,
    profit_factor: float | None,
    expectancy: float,
    max_drawdown_percent: float,
    total_trades: int,
    yearly_net: dict[str, float],
    test_segment: str,
    locked_development_run_id: str | None = None,
    account_ruined: bool = False,
) -> dict[str, Any]:
    """Frozen evidence gate for the published abnormal-return hypothesis."""

    pf = float(profit_factor or 0.0)
    profitable_years = sum(float(value) > 0 for value in yearly_net.values())
    untouched = test_segment == "untouched"
    required_trades = 15 if untouched else 30
    required_years = 2 if untouched else 3
    required_pf = 1.20 if untouched else 1.35
    passed = (
        not account_ruined
        and total_trades >= required_trades
        and profitable_years >= required_years
        and net_profit > 0
        and expectancy > 0
        and pf >= required_pf
        and max_drawdown_percent <= 5.0
    )
    if account_ruined:
        return {
            "code": "account_ruined",
            "label": "ACCOUNT BLOWN — FAILED",
            "tone": "failed",
            "summary": "The abnormal-return strategy exhausted the test account.",
            "next_action": "Reject it. Do not open untouched data or build an EA.",
        }
    if untouched and not locked_development_run_id:
        return {
            "code": "unlocked_untouched",
            "label": "INVALID UNTOUCHED TEST — NO PASS",
            "tone": "failed",
            "summary": "No passing development run with identical frozen rules was linked.",
            "next_action": "Run Development first, then reuse every setting unchanged.",
        }
    if passed and untouched:
        return {
            "code": "untouched_pass",
            "label": "UNTOUCHED PASS — VERIFY IN MT5",
            "tone": "promising",
            "summary": "The same abnormal-return rules remained profitable on unseen history after costs.",
            "next_action": "Verify the frozen implementation with broker-specific MT5 real ticks and a demo forward test.",
        }
    if passed and test_segment == "development":
        return {
            "code": "promising",
            "label": "PROMISING — RUN UNTOUCHED TEST",
            "tone": "promising",
            "summary": "Development cleared the predeclared trade-count, repeatability, profit-factor and drawdown gates.",
            "next_action": "Freeze every setting and run the untouched final third.",
        }
    if passed:
        return {
            "code": "exploratory_pass",
            "label": "EXPLORATORY PASS — NOT PROOF",
            "tone": "warning",
            "summary": "This period cleared the numbers outside the locked development-to-untouched sequence.",
            "next_action": "Run Development first, then the untouched final third unchanged.",
        }

    failed_gates: list[str] = []
    if total_trades < required_trades:
        failed_gates.append(f"only {total_trades} of {required_trades} required trades")
    if profitable_years < required_years:
        failed_gates.append(f"only {profitable_years} of {required_years} required profitable years")
    if pf < required_pf:
        failed_gates.append(f"profit factor {pf:.3f} below {required_pf:.2f}")
    if net_profit <= 0 or expectancy <= 0:
        failed_gates.append("profit or expectancy not positive")
    if max_drawdown_percent > 5.0:
        failed_gates.append(f"drawdown {max_drawdown_percent:.2f}% above 5%")
    return {
        "code": "failed",
        "label": "FAILED — DO NOT BUILD EA",
        "tone": "failed",
        "summary": "The locked abnormal-return strategy failed: " + "; ".join(failed_gates) + ".",
        "next_action": "Reject v1. Do not tune these thresholds on the same result.",
    }


def _trend_verdict(
    *,
    net_profit: float,
    profit_factor: float | None,
    expectancy: float,
    max_drawdown_percent: float,
    total_trades: int,
    test_segment: str,
    locked_development_run_id: str | None = None,
    account_ruined: bool = False,
    signal_label: str = "H4",
) -> dict[str, Any]:
    """Strict proof gate shared by the pre-declared Gold trend tests."""

    pf = float(profit_factor or 0.0)
    enough_evidence = total_trades >= 100
    profitable = net_profit > 0 and expectancy > 0 and pf >= 1.25
    controlled_drawdown = max_drawdown_percent <= 15.0
    passed = enough_evidence and profitable and controlled_drawdown
    if account_ruined:
        return {
            "code": "account_ruined",
            "label": "ACCOUNT BLOWN — FAILED",
            "tone": "failed",
            "summary": "The trend strategy exhausted the test account. EVE stopped at zero.",
            "next_action": "Reject it. Do not open the untouched period or build an EA.",
        }
    if test_segment == "untouched" and not locked_development_run_id:
        return {
            "code": "unlocked_untouched",
            "label": "INVALID UNTOUCHED TEST — NO PASS",
            "tone": "failed",
            "summary": "No completed development run with identical frozen settings was linked.",
            "next_action": "Run Development first, then reuse its exact settings.",
        }
    if passed and test_segment == "untouched":
        return {
            "code": "untouched_pass",
            "label": "UNTOUCHED PASS — STRESS TEST NEXT",
            "tone": "promising",
            "summary": f"The frozen {signal_label} trend rules stayed profitable with controlled drawdown on unseen history.",
            "next_action": "Challenge the neighbouring 45/15 and 65/25 channels, then verify with MT5 real ticks and demo trading.",
        }
    if passed and test_segment == "development":
        return {
            "code": "promising",
            "label": "PROMISING — RUN UNTOUCHED TEST",
            "tone": "promising",
            "summary": "The development period cleared PF 1.25, positive expectancy, 100 trades and 15% drawdown.",
            "next_action": "Freeze every setting and run the untouched final third.",
        }
    if passed:
        return {
            "code": "exploratory_pass",
            "label": "EXPLORATORY PASS — NOT PROOF",
            "tone": "warning",
            "summary": "This period cleared the numbers but not the locked development-to-untouched sequence.",
            "next_action": "Run Development first, then the untouched final third unchanged.",
        }
    if total_trades < 100:
        return {
            "code": "insufficient_evidence",
            "label": "NOT ENOUGH TRADES — NO VERDICT",
            "tone": "waiting",
            "summary": f"Only {total_trades} completed trades were found; EVE requires 100 before judging this idea.",
            "next_action": "Do not build an EA from this result.",
        }
    if net_profit > 0 and pf >= 1.0:
        return {
            "code": "mixed",
            "label": "MIXED — DO NOT BUILD YET",
            "tone": "warning",
            "summary": "It made money, but failed PF 1.25, positive expectancy or the 15% drawdown ceiling.",
            "next_action": "Reject v1 unless one pre-declared robustness test explains the weakness.",
        }
    return {
        "code": "failed",
        "label": "FAILED — DO NOT BUILD EA",
        "tone": "failed",
        "summary": f"The complete historical sequence did not show a usable {signal_label} trend edge after all modelled costs.",
        "next_action": "Reject these rules and research a different hypothesis.",
    }


class BacktestService:
    def __init__(self, repo: SupabaseRepository) -> None:
        self.repo = repo
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    async def ensure_strategy_version(self) -> str:
        strategy = await self.repo.get_strategy_by_slug(STRATEGY_SLUG)
        if strategy is None:
            strategy = await self.repo.create_strategy(
                STRATEGY_NAME,
                STRATEGY_SLUG,
                "Exact imported MT5 fixed two-sided ladder strategy with v2.61 basket peak protection.",
            )
        version = await self.repo.get_strategy_version(str(strategy["id"]), STRATEGY_VERSION)
        if version is None:
            rules = {
                "levels_per_side": 8,
                "grid_spacing_price": 3.0,
                "fixed_lot": 0.01,
                "fallback_price": 2.0,
                "first_bullet_quick_cut_price": 0.75,
                "break_even_trigger_price": 1.5,
                "break_even_buffer_price": 0.15,
                "profit_target_money": 5.0,
                "basket_peak_activation_money": 4.0,
                "basket_peak_giveback_money": 1.0,
                "opposite_ladder_remains": True,
                "immediate_rearm": True,
                "source": "imported-strategies/EVE_Twelve_Data_Fixed_Ladder_v2.61.mq5",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                STRATEGY_VERSION,
                rules,
                SOURCE_SHA256,
                "Imported from the user's current eve-twelve-data-momentum-trader main branch.",
            )
        return str(version["id"])

    async def ensure_liquidity_strategy_version(self, entry_model: str = "sweep_reversal") -> str:
        identity = liquidity_identity(entry_model)
        strategy = await self.repo.get_strategy_by_slug(identity["slug"])
        if strategy is None:
            strategy = await self.repo.create_strategy(
                identity["name"],
                identity["slug"],
                identity["description"],
            )
        version = await self.repo.get_strategy_version(str(strategy["id"]), identity["version"])
        if version is None:
            rules = {
                "entry_model": entry_model,
                "signal": identity["signal"],
                "entry": "next M1 candle open only",
                "positions_per_basket": 4,
                "fixed_lot": 0.02,
                "lookback_candles": 20,
                "trend_filter": "EMA 50 aligned with direction",
                "profit_target_money": 4.0,
                "basket_stop_money": 8.0,
                "one_basket_at_a_time": True,
                "martingale": False,
                "costs_included": True,
                "source": "railway/app/backtesting/liquidity_basket.py",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                identity["version"],
                rules,
                LIQUIDITY_SOURCE_SHA256,
                identity["note"],
            )
        return str(version["id"])

    async def ensure_london_strategy_version(self) -> str:
        strategy = await self.repo.get_strategy_by_slug(LONDON_STRATEGY_SLUG)
        if strategy is None:
            strategy = await self.repo.create_strategy(
                LONDON_STRATEGY_NAME,
                LONDON_STRATEGY_SLUG,
                "One risk-sized XAU/USD position after a confirmed M5 breakout from the 08:00-08:30 London opening range.",
            )
        version = await self.repo.get_strategy_version(str(strategy["id"]), LONDON_STRATEGY_VERSION)
        if version is None:
            rules = {
                "signal_timeframe": "M5 reconstructed from verified M1 candles",
                "execution_timeframe": "M1 replay",
                "timezone": "Europe/London",
                "opening_range": "08:00-08:30 London",
                "signal": "first directional M5 close at least 10% of range width beyond the range",
                "entry": "next M5 open",
                "stop": "opening-range midpoint",
                "target": "2R after costs",
                "entry_cutoff": "11:30 London",
                "force_exit": "16:00 London",
                "maximum_trades_per_day": 1,
                "risk_percent": 0.25,
                "martingale": False,
                "costs_included": True,
                "source": "railway/app/backtesting/london_opening_range.py",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                LONDON_STRATEGY_VERSION,
                rules,
                LONDON_SOURCE_SHA256,
                "Independent session-breakout hypothesis. Research only; no MT5 EA exists unless development and untouched tests both pass.",
            )
        return str(version["id"])

    async def ensure_new_york_momentum_strategy_version(self) -> str:
        strategy = await self.repo.get_strategy_by_slug(NEW_YORK_MOMENTUM_STRATEGY_SLUG)
        if strategy is None:
            strategy = await self.repo.create_strategy(
                NEW_YORK_MOMENTUM_STRATEGY_NAME,
                NEW_YORK_MOMENTUM_STRATEGY_SLUG,
                "At most one risk-sized XAU/USD trade per New York weekday, following the 08:30-09:00 morning impulse.",
            )
        version = await self.repo.get_strategy_version(str(strategy["id"]), NEW_YORK_MOMENTUM_STRATEGY_VERSION)
        if version is None:
            rules = {
                "signal_timeframe": "verified M1 candles",
                "execution_timeframe": "M1 replay",
                "timezone": "America/New_York with DST",
                "signal_window": "08:30-09:00 New York",
                "direction": "buy when window close exceeds open; sell when close is below open",
                "entry": "09:00 M1 open only; no late entry",
                "stop": "opposite edge of the complete 30-minute signal range",
                "target": None,
                "force_exit": "15:55 New York",
                "maximum_trades_per_day": 1,
                "risk_percent": 0.25,
                "martingale": False,
                "averaging": False,
                "spread_commission_slippage": True,
                "missing_minutes": "skip the day",
                "source": "railway/app/backtesting/new_york_morning_momentum.py",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                NEW_YORK_MOMENTUM_STRATEGY_VERSION,
                rules,
                NEW_YORK_MOMENTUM_SOURCE_SHA256,
                "Pre-declared once-per-day intraday momentum hypothesis. No EA exists unless locked development and untouched tests pass.",
            )
        return str(version["id"])

    async def ensure_comex_closing_momentum_strategy_version(self) -> str:
        strategy = await self.repo.get_strategy_by_slug(COMEX_CLOSING_MOMENTUM_STRATEGY_SLUG)
        if strategy is None:
            strategy = await self.repo.create_strategy(
                COMEX_CLOSING_MOMENTUM_STRATEGY_NAME,
                COMEX_CLOSING_MOMENTUM_STRATEGY_SLUG,
                "At most one fixed-size XAU/USD trade per New York weekday, following the move into the COMEX gold settlement.",
            )
        version = await self.repo.get_strategy_version(
            str(strategy["id"]),
            COMEX_CLOSING_MOMENTUM_STRATEGY_VERSION,
        )
        if version is None:
            rules = {
                "signal_timeframe": "verified M1 candles",
                "execution_timeframe": "M1 replay",
                "timezone": "America/New_York with DST",
                "reference": "previous valid 13:29 M1 close as the spot proxy for the 13:30 COMEX settlement",
                "direction": "buy when the 13:00 open is above the prior reference; sell when below",
                "entry": "13:00 New York M1 open only; no late entry",
                "stop": "hard money stop at 0.25% of current balance",
                "force_exit": "13:30 New York M1 open",
                "maximum_trades_per_day": 1,
                "fixed_lot": 0.01,
                "martingale": False,
                "averaging": False,
                "spread_commission_slippage": True,
                "missing_reference": "skip the day",
                "source": "railway/app/backtesting/comex_closing_momentum.py",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                COMEX_CLOSING_MOMENTUM_STRATEGY_VERSION,
                rules,
                COMEX_CLOSING_MOMENTUM_SOURCE_SHA256,
                "Pre-declared closing-momentum hypothesis grounded in published futures evidence. No EA exists unless locked development and untouched tests pass.",
            )
        return str(version["id"])

    async def ensure_gold_session_anomaly_strategy_version(self, session_leg: str) -> str:
        identity = gold_session_anomaly_identity(session_leg)
        strategy = await self.repo.get_strategy_by_slug(identity["slug"])
        if strategy is None:
            strategy = await self.repo.create_strategy(
                identity["name"],
                identity["slug"],
                identity["description"],
            )
        version = await self.repo.get_strategy_version(
            str(strategy["id"]),
            GOLD_SESSION_ANOMALY_STRATEGY_VERSION,
        )
        if version is None:
            rules = {
                "signal_timeframe": "verified M1 candles",
                "execution_timeframe": "M1 replay",
                "timezone": (
                    "fixed GMT+3"
                    if session_leg == "abnormal_momentum"
                    else "America/New_York with DST"
                ),
                "session_leg": session_leg,
                "entry": identity["entry"],
                "exit": identity["exit"],
                "abnormal_return_baseline": (
                    "mean plus/minus two sample standard deviations of only the previous 60 completed GMT+3 daily returns"
                    if session_leg == "abnormal_momentum"
                    else None
                ),
                "abnormal_daily_bar": (
                    "first tradable M1 quote from 00:00 through 02:00 GMT+3 to the last quote before the next GMT+3 date"
                    if session_leg == "abnormal_momentum"
                    else None
                ),
                "intraday_volatility_filter": (
                    "sum of 30 squared one-minute log returns from the complete 11:30-12:00 New York window must exceed the median of the previous 60 complete weekday windows"
                    if session_leg == "gld_high_vol_fifth_half_hour_momentum"
                    else None
                ),
                "stop": "hard money stop at 0.25% of current balance, including costs already charged",
                "maximum_trades_per_day": 1,
                "fixed_lot": 0.01,
                "martingale": False,
                "averaging": False,
                "reentry": False,
                "spread_commission_slippage": True,
                "overnight_financing": (
                    "$0.70 per 0.01 lot at 17:00 New York with Wednesday triple"
                    if session_leg in {"overnight_long", "etf_overnight_long"}
                    else (
                        "not applicable because the trade opens after rollover and exits before the next rollover"
                        if session_leg in {"asia_long", "abnormal_momentum"}
                        else (
                            "not applicable to the same-day Shanghai long"
                            if session_leg == "shanghai_day_long"
                            else "not applicable to the same-day trade"
                        )
                    )
                ),
                "missing_entry": "skip the day; never enter late",
                "causality": (
                    "rolling baseline uses completed prior days only; chronological split day is skipped"
                    if session_leg == "abnormal_momentum"
                    else (
                        "the volatility threshold uses only the previous 60 complete windows; today's complete 11:30-12:00 direction and volatility are known before the 15:30 entry"
                        if session_leg == "gld_high_vol_fifth_half_hour_momentum"
                        else (
                            "the 11:30-12:00 predictor is complete three and a half hours before the 15:30 entry"
                            if session_leg == "gld_fifth_half_hour_momentum"
                            else (
                                "the previous 16:00 close is known before the current 15:30 entry; missing references skip the day"
                                if session_leg == "rest_of_day_close_momentum"
                                else None
                            )
                        )
                    )
                ),
                "research_source": (
                    "Liu, Zhang and Zhang (2026), Journal of Banking & Finance 185, DOI 10.1016/j.jbankfin.2025.107621"
                    if session_leg in {"etf_intraday_short", "etf_overnight_long"}
                    else (
                        "Caporale and Plastun (2021), Financial Markets and Portfolio Management, DOI 10.1007/s11408-021-00380-w"
                        if session_leg == "abnormal_momentum"
                        else (
                            "Xu, Bouri, Saeed and Wen (2020), Resources Policy 69, DOI 10.1016/j.resourpol.2020.101830"
                            if session_leg in {
                                "gld_fifth_half_hour_momentum",
                                "gld_high_vol_fifth_half_hour_momentum",
                            }
                            else (
                                "Baltussen, Da, Lammers and Martens (2021), Journal of Financial Economics 142, DOI 10.1016/j.jfineco.2021.04.029"
                                if session_leg == "rest_of_day_close_momentum"
                                else None
                            )
                        )
                    )
                ),
                "source": "railway/app/backtesting/gold_session_anomaly.py",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                GOLD_SESSION_ANOMALY_STRATEGY_VERSION,
                rules,
                GOLD_SESSION_ANOMALY_SOURCE_SHA256,
                (
                    "Published ETF overnight-positive/intraday-negative effect translated once into XAU/USD market-hour legs and frozen together before either EVE result was seen. No EA exists unless locked development and untouched tests both pass."
                    if session_leg in {"etf_intraday_short", "etf_overnight_long"}
                    else (
                        "Published same-day abnormal-return momentum hypothesis translated into a causal rolling rule and frozen before its EVE result was seen. No EA exists unless locked development and untouched tests both pass."
                        if session_leg == "abnormal_momentum"
                        else (
                            "Published GLD high-volatility subgroup rule translated into a causal 60-window XAU/USD filter and frozen before its EVE result was seen. No EA exists unless locked development and untouched tests both pass."
                            if session_leg == "gld_high_vol_fifth_half_hour_momentum"
                            else (
                                "Published GLD intraday-predictability rule translated once into XAU/USD and frozen before its EVE result was seen. No EA exists unless locked development and untouched tests both pass."
                                if session_leg == "gld_fifth_half_hour_momentum"
                                else (
                                    "Published futures rest-of-day momentum rule translated once into XAU/USD and frozen before its EVE result was seen. No EA exists unless locked development and untouched tests both pass."
                                    if session_leg == "rest_of_day_close_momentum"
                                    else (
                                        "Two eastern-session hypotheses frozen together after both COMEX session legs failed, before either eastern result was seen. No EA exists unless locked development and untouched tests both pass."
                                        if session_leg in {"asia_long", "shanghai_day_long"}
                                        else "Pre-declared together with the opposite session leg before either result was seen. No EA exists unless locked development and untouched tests both pass."
                                    )
                                )
                            )
                        )
                    )
                ),
            )
        return str(version["id"])

    async def ensure_gold_h4_strategy_version(self) -> str:
        strategy = await self.repo.get_strategy_by_slug(GOLD_H4_STRATEGY_SLUG)
        if strategy is None:
            strategy = await self.repo.create_strategy(
                GOLD_H4_STRATEGY_NAME,
                GOLD_H4_STRATEGY_SLUG,
                "One volatility-sized XAU/USD position following completed H4 breakouts in the 60-day daily direction.",
            )
        version = await self.repo.get_strategy_version(str(strategy["id"]), GOLD_H4_STRATEGY_VERSION)
        if version is None:
            rules = {
                "signal_timeframe": "stored completed H4 candles",
                "execution_timeframe": "verified M1 replay",
                "direction_filter": "latest completed D1 close versus 60 trading-day prior close",
                "entry": "completed H4 close beyond the previous 55-H4 high or low, then first available M1 open",
                "initial_stop": "2.0 times simple H4 ATR(20)",
                "exit": "completed H4 close through the opposite previous 20-H4 channel",
                "take_profit": None,
                "maximum_positions": 1,
                "risk_percent": 0.25,
                "martingale": False,
                "averaging": False,
                "spread_commission_slippage": True,
                "overnight_financing": "fixed long/short costs per 0.01 lot with Wednesday triple charge",
                "weekend_gaps": "filled at first available M1 open",
                "source": "railway/app/backtesting/gold_h4_trend.py",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                GOLD_H4_STRATEGY_VERSION,
                rules,
                GOLD_H4_SOURCE_SHA256,
                "Research-led multi-day trend hypothesis. No MT5 EA exists unless locked development, untouched and robustness tests pass.",
            )
        return str(version["id"])

    async def ensure_gold_h1_strategy_version(self) -> str:
        strategy = await self.repo.get_strategy_by_slug(GOLD_H1_STRATEGY_SLUG)
        if strategy is None:
            strategy = await self.repo.create_strategy(
                GOLD_H1_STRATEGY_NAME,
                GOLD_H1_STRATEGY_SLUG,
                "One volatility-sized XAU/USD position following completed H1 breakouts in the 60-day daily direction.",
            )
        version = await self.repo.get_strategy_version(str(strategy["id"]), GOLD_H1_STRATEGY_VERSION)
        if version is None:
            rules = {
                "signal_timeframe": "stored completed H1 candles",
                "execution_timeframe": "verified M1 replay",
                "direction_filter": "latest completed D1 close versus 60 trading-day prior close",
                "entry": "completed H1 close beyond the previous 55-H1 high or low, then first available M1 open",
                "initial_stop": "2.0 times simple H1 ATR(20)",
                "exit": "completed H1 close through the opposite previous 20-H1 channel",
                "take_profit": None,
                "maximum_positions": 1,
                "risk_percent": 0.25,
                "martingale": False,
                "averaging": False,
                "spread_commission_slippage": True,
                "overnight_financing": "fixed long/short costs per 0.01 lot with Wednesday triple charge",
                "weekend_gaps": "filled at first available M1 open",
                "source": "railway/app/backtesting/gold_h1_trend.py",
            }
            version = await self.repo.create_strategy_version(
                str(strategy["id"]),
                GOLD_H1_STRATEGY_VERSION,
                rules,
                GOLD_H1_SOURCE_SHA256,
                "Pre-declared higher-frequency follow-up to the inconclusive H4 sample. No MT5 EA exists unless locked development, untouched and robustness tests pass.",
            )
        return str(version["id"])

    async def start(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(self._run(run_id, request), name=f"backtest-{run_id}")
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def start_liquidity(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(self._run_liquidity(run_id, request), name=f"liquidity-backtest-{run_id}")
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def start_london(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(self._run_london(run_id, request), name=f"london-backtest-{run_id}")
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def start_new_york_momentum(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(
                self._run_new_york_momentum(run_id, request),
                name=f"new-york-momentum-backtest-{run_id}",
            )
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def start_comex_closing_momentum(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(
                self._run_comex_closing_momentum(run_id, request),
                name=f"comex-closing-momentum-backtest-{run_id}",
            )
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def start_gold_session_anomaly(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(
                self._run_gold_session_anomaly(run_id, request),
                name=f"gold-session-anomaly-backtest-{run_id}",
            )
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def start_gold_h4(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(self._run_gold_h4(run_id, request), name=f"gold-h4-backtest-{run_id}")
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def start_gold_h1(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(self._run_gold_h1(run_id, request), name=f"gold-h1-backtest-{run_id}")
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def cancel(self, run_id: str) -> None:
        await self.repo.update_backtest_run(run_id, status="cancelled", finished_at=datetime.now(timezone.utc).isoformat())

    @staticmethod
    def _resolution_details(request: dict[str, Any]) -> tuple[str, str, str, str]:
        resolution = str(request.get("resolution", "candle"))
        if resolution == "m1_replay":
            return (
                "1min",
                "M1 high-resolution candle replay",
                "M1 bars greatly reduce intrabar ordering uncertainty, but a one-minute bar can still contain multiple events. Tick replay is required for exact execution proof.",
                "M1",
            )
        return (
            "5min",
            "M5 candle-path approximation",
            "M5 bars cannot prove the exact order of every pending-order, break-even and stop event inside a candle. Use M1 or tick replay before live approval.",
            "M5",
        )

    async def _run(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval, accuracy, warning, interval_label = self._resolution_details(request)
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": f"Loading verified XAU/USD {interval_label} candles from Market Memory",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "source_sha256": SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"Fixed Ladder v2.61 {interval_label} backtest started",
                {"run_id": run_id, "resolution": request.get("resolution", "candle")},
            )

            params = FixedLadderParameters(
                fixed_lot=float(request.get("fixed_lot", 0.01)),
                levels_per_side=int(request.get("levels_per_side", 8)),
                spacing_price=float(request.get("spacing_price", 3.0)),
                fallback_price=float(request.get("fallback_price", 2.0)),
                first_bullet_quick_cut_price=float(request.get("first_bullet_quick_cut_price", 0.75)),
                break_even_trigger_price=float(request.get("break_even_trigger_price", 1.5)),
                break_even_buffer_price=float(request.get("break_even_buffer_price", 0.15)),
                profit_target_money=float(request.get("profit_target_money", 5.0)),
                peak_protection_activation_money=float(request.get("peak_protection_activation_money", 4.0)),
                peak_protection_giveback_money=float(request.get("peak_protection_giveback_money", 1.0)),
                emergency_loss_money=float(request.get("emergency_loss_money", 5.0)),
                emergency_loss_percent=float(request.get("emergency_loss_percent", 1.0)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            simulator = FixedLadderV261Backtester(float(request.get("starting_balance", 1000.0)), params)

            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError(f"No {interval_label} candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0

            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event("warning", "backtester", "Backtest cancelled", {"run_id": run_id})
                        return

                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1

                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                processed += len(page)
                cursor = str(page[-1]["candle_time"])

                for trade in simulator.drain_trades():
                    trade_buffer.append(trade.to_row(run_id))
                for basket in simulator.drain_baskets():
                    basket_buffer.append(basket.to_row(run_id))

                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                update_every = 10_000 if data_interval == "1min" else 5_000
                if processed - last_progress_update >= update_every or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified {interval_label} candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "ambiguous_candles": simulator.ambiguous_candles,
                            "source_sha256": SOURCE_SHA256,
                        },
                    )

                if len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_row(run_id) for trade in final_trades)
            basket_buffer.extend(basket.to_row(run_id) for basket in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.position_pnls:
                raise RuntimeError("The strategy did not complete any positions in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            basket_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance) if summary.basket_pnls else None

            reliability = {
                "progress_percent": 100,
                "message": "Backtest complete",
                "accuracy": accuracy,
                "warning": warning,
                "input_interval": data_interval,
                "candles_processed": summary.candles_processed,
                "ambiguous_candles": summary.ambiguous_candles,
                "ambiguous_percent": round(summary.ambiguous_candles / summary.candles_processed * 100, 5) if summary.candles_processed else 0,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": basket_metrics.as_dict() if basket_metrics else None,
                "source_sha256": SOURCE_SHA256,
            }
            primary_metrics = basket_metrics or position_metrics
            profit_factor = primary_metrics.profit_factor if primary_metrics.profit_factor is not None and math.isfinite(primary_metrics.profit_factor) else None
            recovery_factor = primary_metrics.recovery_factor if primary_metrics.recovery_factor is not None and math.isfinite(primary_metrics.recovery_factor) else None
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=primary_metrics.net_profit,
                gross_profit=primary_metrics.gross_profit,
                gross_loss=primary_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=primary_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=max(primary_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent),
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=primary_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"Fixed Ladder v2.61 {interval_label} backtest completed",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "positions": summary.total_positions,
                    "baskets": summary.total_baskets,
                    "net_profit": primary_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "resolution": request.get("resolution", "candle"),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event("error", "backtester", "Backtest failed", {"run_id": run_id, "error": str(exc)})

    async def _run_liquidity(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval = "1min"
        test_segment = str(request.get("test_segment", "full"))
        entry_model = str(request.get("entry_model", "sweep_reversal"))
        identity = liquidity_identity(entry_model)
        strategy_code = identity["code"]
        strategy_name = identity["name"]
        accuracy = "M1 high-resolution candle replay"
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": "Loading verified XAU/USD M1 candles from Market Memory",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "strategy": strategy_code,
                    "entry_model": entry_model,
                    "test_segment": test_segment,
                    "locked_development_run_id": request.get("locked_development_run_id"),
                    "source_sha256": LIQUIDITY_SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"{strategy_name} M1 backtest started",
                {"run_id": run_id, "test_segment": test_segment, "entry_model": entry_model},
            )

            params = LiquidityBasketParameters(
                entry_model=entry_model,
                positions_per_basket=int(request.get("positions_per_basket", 4)),
                fixed_lot=float(request.get("fixed_lot", 0.02)),
                lookback_candles=int(request.get("lookback_candles", 20)),
                trend_period=int(request.get("trend_period", 50)),
                use_trend_filter=bool(request.get("use_trend_filter", True)),
                minimum_sweep_price=float(request.get("minimum_sweep_price", 0.05)),
                profit_target_money=float(request.get("profit_target_money", 4.0)),
                basket_stop_money=float(request.get("basket_stop_money", 8.0)),
                maximum_hold_minutes=int(request.get("maximum_hold_minutes", 180)),
                cooldown_candles=int(request.get("cooldown_candles", 5)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            simulator = LiquidityBasketBacktester(float(request.get("starting_balance", 1000.0)), params)

            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError("No M1 candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0

            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event("warning", "backtester", "Liquidity backtest cancelled", {"run_id": run_id})
                        return
                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1
                page_processed = 0
                last_processed_row: dict[str, Any] | None = None
                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                    page_processed += 1
                    last_processed_row = row
                    if simulator.account_ruined:
                        break
                processed += page_processed
                if last_processed_row is not None:
                    cursor = str(last_processed_row["candle_time"])

                trade_buffer.extend(trade.to_row(run_id) for trade in simulator.drain_trades())
                basket_buffer.extend(basket.to_row(run_id) for basket in simulator.drain_baskets())
                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                if processed - last_progress_update >= 10_000 or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified M1 candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "strategy": strategy_code,
                            "entry_model": entry_model,
                            "test_segment": test_segment,
                            "locked_development_run_id": request.get("locked_development_run_id"),
                            "ambiguous_candles": simulator.ambiguous_candles,
                            "signals_detected": simulator.signals_detected,
                            "source_sha256": LIQUIDITY_SOURCE_SHA256,
                        },
                    )
                if simulator.account_ruined or len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_row(run_id) for trade in final_trades)
            basket_buffer.extend(basket.to_row(run_id) for basket in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.basket_pnls:
                raise RuntimeError("No complete liquidity baskets were found in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            basket_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance)
            profit_factor = (
                basket_metrics.profit_factor
                if basket_metrics.profit_factor is not None and math.isfinite(basket_metrics.profit_factor)
                else None
            )
            recovery_factor = (
                basket_metrics.recovery_factor
                if basket_metrics.recovery_factor is not None and math.isfinite(basket_metrics.recovery_factor)
                else None
            )
            first = datetime.fromisoformat(summary.first_candle) if summary.first_candle else None
            last = datetime.fromisoformat(summary.last_candle) if summary.last_candle else None
            weeks = max(1.0 / 7.0, ((last - first).total_seconds() / 604800.0) if first and last else 0.0)
            drawdown_percent = max(basket_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent)
            verdict = _liquidity_verdict(
                net_profit=basket_metrics.net_profit,
                # Keep mathematical infinity for the gate when the sample has
                # no losing basket. The stored/API value remains null because
                # JSON has no portable Infinity representation.
                profit_factor=basket_metrics.profit_factor,
                expectancy=basket_metrics.expectancy,
                max_drawdown_percent=drawdown_percent,
                total_baskets=summary.total_baskets,
                test_segment=test_segment,
                locked_development_run_id=request.get("locked_development_run_id"),
                account_ruined=summary.account_ruined,
            )
            reliability = {
                "progress_percent": 100,
                "message": (
                    f"{strategy_name} stopped when the account reached $0"
                    if summary.account_ruined
                    else f"{strategy_name} backtest complete"
                ),
                "accuracy": accuracy,
                "warning": "The account is capped at zero. M1 bars still cannot prove the tick order when target and loss limit occur in the same minute. Verify any survivor in MT5 using real ticks.",
                "input_interval": data_interval,
                "strategy": strategy_code,
                "entry_model": entry_model,
                "test_segment": test_segment,
                "locked_development_run_id": request.get("locked_development_run_id"),
                "candles_processed": summary.candles_processed,
                "candles_available": expected_rows,
                "terminated_early": summary.account_ruined and summary.candles_processed < expected_rows,
                "account_ruined": summary.account_ruined,
                "ruin_time": summary.ruin_time,
                "ambiguous_candles": summary.ambiguous_candles,
                "ambiguous_percent": round(summary.ambiguous_candles / summary.candles_processed * 100, 5) if summary.candles_processed else 0,
                "signals_detected": summary.signals_detected,
                "signals_filtered": summary.signals_filtered,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": basket_metrics.as_dict(),
                "worst_basket": round(min(summary.basket_pnls), 2),
                "longest_losing_streak": _longest_losing_streak(summary.basket_pnls),
                "baskets_per_week": round(summary.total_baskets / weeks, 3),
                "verdict": verdict,
                "source_sha256": LIQUIDITY_SOURCE_SHA256,
            }
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=basket_metrics.net_profit,
                gross_profit=basket_metrics.gross_profit,
                gross_loss=basket_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=basket_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=drawdown_percent,
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=basket_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"{strategy_name} completed: {verdict['label']}",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "baskets": summary.total_baskets,
                    "net_profit": basket_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "verdict": verdict["code"],
                    "test_segment": test_segment,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Liquidity backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "strategy": strategy_code,
                    "entry_model": entry_model,
                    "test_segment": test_segment,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "error",
                "backtester",
                f"{strategy_name} backtest failed",
                {"run_id": run_id, "error": str(exc), "entry_model": entry_model},
            )

    async def _load_signal_candles(self, symbol: str, interval: str, date_to: str | None) -> list[Candle]:
        rows: list[Candle] = []
        cursor: str | None = None
        while True:
            page = await self.repo.fetch_candles_page(
                symbol=symbol,
                interval=interval,
                after=cursor,
                date_from=None,
                date_to=date_to,
                limit=1000,
            )
            if not page:
                break
            rows.extend(Candle.from_row(item) for item in page)
            cursor = str(page[-1]["candle_time"])
            if len(page) < 1000:
                break
        return rows

    async def _run_gold_h4(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval = "1min"
        test_segment = str(request.get("test_segment", "full"))
        strategy_code = "gold_h4_trend"
        accuracy = "Stored completed H4 and D1 signals with verified M1 execution, stop and gap replay"
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": "Loading stored H4 and daily candles before the M1 execution replay",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "4h",
                    "context_interval": "1day",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                    "locked_development_run_id": request.get("locked_development_run_id"),
                    "source_sha256": GOLD_H4_SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"{GOLD_H4_STRATEGY_NAME} M1 replay started",
                {"run_id": run_id, "test_segment": test_segment},
            )

            params = GoldH4TrendParameters(
                entry_lookback_h4=int(request.get("entry_lookback_h4", 55)),
                exit_lookback_h4=int(request.get("exit_lookback_h4", 20)),
                daily_trend_lookback=int(request.get("daily_trend_lookback", 60)),
                atr_period_h4=int(request.get("atr_period_h4", 20)),
                atr_multiplier=float(request.get("atr_multiplier", 2.0)),
                risk_percent=float(request.get("risk_percent", 0.25)),
                minimum_lot=float(request.get("minimum_lot", 0.01)),
                lot_step=float(request.get("lot_step", 0.01)),
                maximum_lot=float(request.get("maximum_lot", 1.0)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                overnight_long_cost_per_001_lot=float(request.get("overnight_long_cost_per_001_lot", 0.70)),
                overnight_short_cost_per_001_lot=float(request.get("overnight_short_cost_per_001_lot", 0.70)),
                triple_swap_weekday=int(request.get("triple_swap_weekday", 2)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            start_dt = datetime.fromisoformat(str(date_from).replace("Z", "+00:00")) if date_from else None
            end_dt = datetime.fromisoformat(str(date_to).replace("Z", "+00:00")) if date_to else None

            h4_candles = await self._load_signal_candles(symbol, "4h", date_to)
            daily_candles = await self._load_signal_candles(symbol, "1day", date_to)
            if not h4_candles or not daily_candles:
                raise RuntimeError("Complete H4 and D1 Market Memory are required for this strategy")
            events = build_trend_events(h4_candles, daily_candles, params, date_from=start_dt, date_to=end_dt)
            if not events:
                raise RuntimeError("No completed H4 events remained after the 55-H4 and 60-day warm-up")
            simulator = GoldH4TrendBacktester(float(request.get("starting_balance", 10_000.0)), params, events)

            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError("No M1 candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0
            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event(
                            "warning",
                            "backtester",
                            "Gold H4 Trend backtest cancelled",
                            {"run_id": run_id},
                        )
                        return
                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1
                page_processed = 0
                last_processed_row: dict[str, Any] | None = None
                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                    page_processed += 1
                    last_processed_row = row
                    if simulator.account_ruined:
                        break
                processed += page_processed
                if last_processed_row is not None:
                    cursor = str(last_processed_row["candle_time"])

                trade_buffer.extend(trade.to_trade_row(run_id) for trade in simulator.drain_trades())
                basket_buffer.extend(basket.to_basket_row(run_id) for basket in simulator.drain_baskets())
                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                if processed - last_progress_update >= 10_000 or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified M1 candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "signal_interval": "4h",
                            "context_interval": "1day",
                            "strategy": strategy_code,
                            "test_segment": test_segment,
                            "locked_development_run_id": request.get("locked_development_run_id"),
                            "h4_events": len(events),
                            "h4_events_processed": simulator.h4_events_processed,
                            "signals_detected": simulator.signals_detected,
                            "source_sha256": GOLD_H4_SOURCE_SHA256,
                        },
                    )
                if simulator.account_ruined or len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_trade_row(run_id) for trade in final_trades)
            basket_buffer.extend(basket.to_basket_row(run_id) for basket in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.basket_pnls:
                raise RuntimeError("No complete Gold H4 Trend trades were found in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            trade_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance)
            profit_factor = (
                trade_metrics.profit_factor
                if trade_metrics.profit_factor is not None and math.isfinite(trade_metrics.profit_factor)
                else None
            )
            recovery_factor = (
                trade_metrics.recovery_factor
                if trade_metrics.recovery_factor is not None and math.isfinite(trade_metrics.recovery_factor)
                else None
            )
            first = datetime.fromisoformat(summary.first_candle) if summary.first_candle else None
            last = datetime.fromisoformat(summary.last_candle) if summary.last_candle else None
            weeks = max(1.0 / 7.0, ((last - first).total_seconds() / 604800.0) if first and last else 0.0)
            drawdown_percent = max(trade_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent)
            verdict = _trend_verdict(
                net_profit=trade_metrics.net_profit,
                profit_factor=trade_metrics.profit_factor,
                expectancy=trade_metrics.expectancy,
                max_drawdown_percent=drawdown_percent,
                total_trades=summary.total_baskets,
                test_segment=test_segment,
                locked_development_run_id=request.get("locked_development_run_id"),
                account_ruined=summary.account_ruined,
            )
            reliability = {
                "progress_percent": 100,
                "message": (
                    f"{GOLD_H4_STRATEGY_NAME} stopped when the account reached $0"
                    if summary.account_ruined
                    else f"{GOLD_H4_STRATEGY_NAME} backtest complete"
                ),
                "accuracy": accuracy,
                "warning": "H4 and D1 decisions use completed stored candles only. M1 replays stops and gaps, but any survivor still requires MT5 real-tick verification with the broker's live swap values.",
                "input_interval": data_interval,
                "signal_interval": "4h",
                "context_interval": "1day",
                "strategy": strategy_code,
                "test_segment": test_segment,
                "locked_development_run_id": request.get("locked_development_run_id"),
                "candles_processed": summary.candles_processed,
                "candles_available": expected_rows,
                "h4_candles_loaded": len(h4_candles),
                "daily_candles_loaded": len(daily_candles),
                "h4_events": len(events),
                "h4_events_processed": summary.h4_events_processed,
                "terminated_early": summary.account_ruined and summary.candles_processed < expected_rows,
                "account_ruined": summary.account_ruined,
                "ruin_time": summary.ruin_time,
                "ambiguous_candles": 0,
                "ambiguous_percent": 0,
                "raw_breakouts": summary.raw_breakouts,
                "daily_filter_rejections": summary.daily_filter_rejections,
                "signals_detected": summary.signals_detected,
                "signals_filtered": summary.signals_filtered,
                "risk_size_skips": summary.risk_size_skips,
                "channel_exits": summary.channel_exits,
                "gap_stop_fills": summary.gap_stop_fills,
                "overnight_rollovers": summary.overnight_rollovers,
                "financing_costs": summary.financing_costs,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": trade_metrics.as_dict(),
                "trade_metrics": trade_metrics.as_dict(),
                "worst_basket": round(min(summary.basket_pnls), 2),
                "worst_trade": round(min(summary.basket_pnls), 2),
                "longest_losing_streak": _longest_losing_streak(summary.basket_pnls),
                "baskets_per_week": round(summary.total_baskets / weeks, 3),
                "trades_per_week": round(summary.total_baskets / weeks, 3),
                "risk_model": "0.25% of current balance to the 2x H4 ATR stop, rounded down to broker lot step",
                "verdict": verdict,
                "source_sha256": GOLD_H4_SOURCE_SHA256,
            }
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=trade_metrics.net_profit,
                gross_profit=trade_metrics.gross_profit,
                gross_loss=trade_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=trade_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=drawdown_percent,
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=trade_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"{GOLD_H4_STRATEGY_NAME} completed: {verdict['label']}",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "trades": summary.total_baskets,
                    "net_profit": trade_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "verdict": verdict["code"],
                    "test_segment": test_segment,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Gold H4 Trend backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "4h",
                    "context_interval": "1day",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "error",
                "backtester",
                f"{GOLD_H4_STRATEGY_NAME} backtest failed",
                {"run_id": run_id, "error": str(exc)},
            )

    async def _run_gold_h1(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval = "1min"
        test_segment = str(request.get("test_segment", "full"))
        strategy_code = "gold_h1_trend"
        accuracy = "Stored completed H1 and D1 signals with verified M1 execution, stop and gap replay"
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": "Loading stored H1 and daily candles before the M1 execution replay",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1h",
                    "context_interval": "1day",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                    "locked_development_run_id": request.get("locked_development_run_id"),
                    "source_sha256": GOLD_H1_SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"{GOLD_H1_STRATEGY_NAME} M1 replay started",
                {"run_id": run_id, "test_segment": test_segment},
            )

            params = GoldH1TrendParameters(
                entry_lookback_h1=int(request.get("entry_lookback_h1", 55)),
                exit_lookback_h1=int(request.get("exit_lookback_h1", 20)),
                daily_trend_lookback=int(request.get("daily_trend_lookback", 60)),
                atr_period_h1=int(request.get("atr_period_h1", 20)),
                atr_multiplier=float(request.get("atr_multiplier", 2.0)),
                risk_percent=float(request.get("risk_percent", 0.25)),
                minimum_lot=float(request.get("minimum_lot", 0.01)),
                lot_step=float(request.get("lot_step", 0.01)),
                maximum_lot=float(request.get("maximum_lot", 1.0)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                overnight_long_cost_per_001_lot=float(request.get("overnight_long_cost_per_001_lot", 0.70)),
                overnight_short_cost_per_001_lot=float(request.get("overnight_short_cost_per_001_lot", 0.70)),
                triple_swap_weekday=int(request.get("triple_swap_weekday", 2)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            start_dt = datetime.fromisoformat(str(date_from).replace("Z", "+00:00")) if date_from else None
            end_dt = datetime.fromisoformat(str(date_to).replace("Z", "+00:00")) if date_to else None

            h1_candles = await self._load_signal_candles(symbol, "1h", date_to)
            daily_candles = await self._load_signal_candles(symbol, "1day", date_to)
            if not h1_candles or not daily_candles:
                raise RuntimeError("Complete H1 and D1 Market Memory are required for this strategy")
            events = build_h1_trend_events(h1_candles, daily_candles, params, date_from=start_dt, date_to=end_dt)
            if not events:
                raise RuntimeError("No completed H1 events remained after the 55-H1 and 60-day warm-up")
            simulator = GoldH1TrendBacktester(float(request.get("starting_balance", 10_000.0)), params, events)

            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError("No M1 candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0
            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event(
                            "warning",
                            "backtester",
                            "Gold H1 Trend backtest cancelled",
                            {"run_id": run_id},
                        )
                        return
                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1
                page_processed = 0
                last_processed_row: dict[str, Any] | None = None
                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                    page_processed += 1
                    last_processed_row = row
                    if simulator.account_ruined:
                        break
                processed += page_processed
                if last_processed_row is not None:
                    cursor = str(last_processed_row["candle_time"])

                trade_buffer.extend(trade.to_trade_row(run_id) for trade in simulator.drain_trades())
                basket_buffer.extend(basket.to_basket_row(run_id) for basket in simulator.drain_baskets())
                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                if processed - last_progress_update >= 10_000 or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified M1 candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "signal_interval": "1h",
                            "context_interval": "1day",
                            "strategy": strategy_code,
                            "test_segment": test_segment,
                            "locked_development_run_id": request.get("locked_development_run_id"),
                            "h1_events": len(events),
                            "h1_events_processed": simulator.h1_events_processed,
                            "signals_detected": simulator.signals_detected,
                            "source_sha256": GOLD_H1_SOURCE_SHA256,
                        },
                    )
                if simulator.account_ruined or len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_trade_row(run_id) for trade in final_trades)
            basket_buffer.extend(basket.to_basket_row(run_id) for basket in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.basket_pnls:
                raise RuntimeError("No complete Gold H1 Trend trades were found in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            trade_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance)
            profit_factor = (
                trade_metrics.profit_factor
                if trade_metrics.profit_factor is not None and math.isfinite(trade_metrics.profit_factor)
                else None
            )
            recovery_factor = (
                trade_metrics.recovery_factor
                if trade_metrics.recovery_factor is not None and math.isfinite(trade_metrics.recovery_factor)
                else None
            )
            first = datetime.fromisoformat(summary.first_candle) if summary.first_candle else None
            last = datetime.fromisoformat(summary.last_candle) if summary.last_candle else None
            weeks = max(1.0 / 7.0, ((last - first).total_seconds() / 604800.0) if first and last else 0.0)
            drawdown_percent = max(trade_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent)
            verdict = _trend_verdict(
                net_profit=trade_metrics.net_profit,
                profit_factor=trade_metrics.profit_factor,
                expectancy=trade_metrics.expectancy,
                max_drawdown_percent=drawdown_percent,
                total_trades=summary.total_baskets,
                test_segment=test_segment,
                locked_development_run_id=request.get("locked_development_run_id"),
                account_ruined=summary.account_ruined,
                signal_label="H1",
            )
            reliability = {
                "progress_percent": 100,
                "message": (
                    f"{GOLD_H1_STRATEGY_NAME} stopped when the account reached $0"
                    if summary.account_ruined
                    else f"{GOLD_H1_STRATEGY_NAME} backtest complete"
                ),
                "accuracy": accuracy,
                "warning": "H1 and D1 decisions use completed stored candles only. M1 replays stops and gaps, but any survivor still requires MT5 real-tick verification with the broker's live swap values.",
                "input_interval": data_interval,
                "signal_interval": "1h",
                "context_interval": "1day",
                "strategy": strategy_code,
                "test_segment": test_segment,
                "locked_development_run_id": request.get("locked_development_run_id"),
                "candles_processed": summary.candles_processed,
                "candles_available": expected_rows,
                "h1_candles_loaded": len(h1_candles),
                "daily_candles_loaded": len(daily_candles),
                "h1_events": len(events),
                "h1_events_processed": summary.h1_events_processed,
                "terminated_early": summary.account_ruined and summary.candles_processed < expected_rows,
                "account_ruined": summary.account_ruined,
                "ruin_time": summary.ruin_time,
                "ambiguous_candles": 0,
                "ambiguous_percent": 0,
                "raw_breakouts": summary.raw_breakouts,
                "daily_filter_rejections": summary.daily_filter_rejections,
                "signals_detected": summary.signals_detected,
                "signals_filtered": summary.signals_filtered,
                "risk_size_skips": summary.risk_size_skips,
                "channel_exits": summary.channel_exits,
                "gap_stop_fills": summary.gap_stop_fills,
                "overnight_rollovers": summary.overnight_rollovers,
                "financing_costs": summary.financing_costs,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": trade_metrics.as_dict(),
                "trade_metrics": trade_metrics.as_dict(),
                "worst_basket": round(min(summary.basket_pnls), 2),
                "worst_trade": round(min(summary.basket_pnls), 2),
                "longest_losing_streak": _longest_losing_streak(summary.basket_pnls),
                "baskets_per_week": round(summary.total_baskets / weeks, 3),
                "trades_per_week": round(summary.total_baskets / weeks, 3),
                "risk_model": "0.25% of current balance to the 2x H1 ATR stop, rounded down to broker lot step",
                "verdict": verdict,
                "source_sha256": GOLD_H1_SOURCE_SHA256,
            }
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=trade_metrics.net_profit,
                gross_profit=trade_metrics.gross_profit,
                gross_loss=trade_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=trade_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=drawdown_percent,
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=trade_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"{GOLD_H1_STRATEGY_NAME} completed: {verdict['label']}",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "trades": summary.total_baskets,
                    "net_profit": trade_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "verdict": verdict["code"],
                    "test_segment": test_segment,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Gold H1 Trend backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1h",
                    "context_interval": "1day",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "error",
                "backtester",
                f"{GOLD_H1_STRATEGY_NAME} backtest failed",
                {"run_id": run_id, "error": str(exc)},
            )


    async def _run_london(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval = "1min"
        test_segment = str(request.get("test_segment", "full"))
        strategy_code = "london_opening_range"
        accuracy = "M5 signals reconstructed from verified M1 candles; M1 execution replay"
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": "Loading verified XAU/USD M1 candles for the London-session replay",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "5min",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                    "locked_development_run_id": request.get("locked_development_run_id"),
                    "source_sha256": LONDON_SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"{LONDON_STRATEGY_NAME} M1 replay started",
                {"run_id": run_id, "test_segment": test_segment},
            )

            params = LondonOpeningRangeParameters(
                timezone_name=str(request.get("timezone_name", "Europe/London")),
                range_start_hour=int(request.get("range_start_hour", 8)),
                range_start_minute=int(request.get("range_start_minute", 0)),
                range_minutes=int(request.get("range_minutes", 30)),
                entry_cutoff_hour=int(request.get("entry_cutoff_hour", 11)),
                entry_cutoff_minute=int(request.get("entry_cutoff_minute", 30)),
                force_exit_hour=int(request.get("force_exit_hour", 16)),
                force_exit_minute=int(request.get("force_exit_minute", 0)),
                breakout_buffer_fraction=float(request.get("breakout_buffer_fraction", 0.10)),
                reward_risk=float(request.get("reward_risk", 2.0)),
                risk_percent=float(request.get("risk_percent", 0.25)),
                minimum_lot=float(request.get("minimum_lot", 0.01)),
                lot_step=float(request.get("lot_step", 0.01)),
                maximum_lot=float(request.get("maximum_lot", 1.0)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            simulator = LondonOpeningRangeBacktester(float(request.get("starting_balance", 10_000.0)), params)

            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError("No M1 candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0

            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event(
                            "warning",
                            "backtester",
                            "London Opening Range backtest cancelled",
                            {"run_id": run_id},
                        )
                        return
                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1
                page_processed = 0
                last_processed_row: dict[str, Any] | None = None
                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                    page_processed += 1
                    last_processed_row = row
                    if simulator.account_ruined:
                        break
                processed += page_processed
                if last_processed_row is not None:
                    cursor = str(last_processed_row["candle_time"])

                trade_buffer.extend(trade.to_trade_row(run_id) for trade in simulator.drain_trades())
                basket_buffer.extend(basket.to_basket_row(run_id) for basket in simulator.drain_baskets())
                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                if processed - last_progress_update >= 10_000 or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified M1 candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "signal_interval": "5min",
                            "strategy": strategy_code,
                            "test_segment": test_segment,
                            "locked_development_run_id": request.get("locked_development_run_id"),
                            "ambiguous_candles": simulator.ambiguous_candles,
                            "signals_detected": simulator.signals_detected,
                            "sessions_traded": simulator.sessions_traded,
                            "source_sha256": LONDON_SOURCE_SHA256,
                        },
                    )
                if simulator.account_ruined or len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_trade_row(run_id) for trade in final_trades)
            basket_buffer.extend(basket.to_basket_row(run_id) for basket in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.basket_pnls:
                raise RuntimeError("No complete London Opening Range trades were found in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            trade_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance)
            profit_factor = (
                trade_metrics.profit_factor
                if trade_metrics.profit_factor is not None and math.isfinite(trade_metrics.profit_factor)
                else None
            )
            recovery_factor = (
                trade_metrics.recovery_factor
                if trade_metrics.recovery_factor is not None and math.isfinite(trade_metrics.recovery_factor)
                else None
            )
            first = datetime.fromisoformat(summary.first_candle) if summary.first_candle else None
            last = datetime.fromisoformat(summary.last_candle) if summary.last_candle else None
            weeks = max(1.0 / 7.0, ((last - first).total_seconds() / 604800.0) if first and last else 0.0)
            drawdown_percent = max(trade_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent)
            verdict = _liquidity_verdict(
                net_profit=trade_metrics.net_profit,
                profit_factor=trade_metrics.profit_factor,
                expectancy=trade_metrics.expectancy,
                max_drawdown_percent=drawdown_percent,
                total_baskets=summary.total_baskets,
                test_segment=test_segment,
                locked_development_run_id=request.get("locked_development_run_id"),
                account_ruined=summary.account_ruined,
                unit_label="trades",
            )
            reliability = {
                "progress_percent": 100,
                "message": (
                    f"{LONDON_STRATEGY_NAME} stopped when the account reached $0"
                    if summary.account_ruined
                    else f"{LONDON_STRATEGY_NAME} backtest complete"
                ),
                "accuracy": accuracy,
                "warning": "M5 signals are built only from completed M1-derived bars. M1 still cannot prove tick order when stop and target occur in the same minute; verify any survivor with MT5 real ticks.",
                "input_interval": data_interval,
                "signal_interval": "5min",
                "strategy": strategy_code,
                "test_segment": test_segment,
                "locked_development_run_id": request.get("locked_development_run_id"),
                "candles_processed": summary.candles_processed,
                "candles_available": expected_rows,
                "terminated_early": summary.account_ruined and summary.candles_processed < expected_rows,
                "account_ruined": summary.account_ruined,
                "ruin_time": summary.ruin_time,
                "ambiguous_candles": summary.ambiguous_candles,
                "ambiguous_percent": round(summary.ambiguous_candles / summary.candles_processed * 100, 5) if summary.candles_processed else 0,
                "signals_detected": summary.signals_detected,
                "signals_filtered": summary.signals_filtered,
                "sessions_seen": summary.sessions_seen,
                "sessions_with_complete_range": summary.sessions_with_complete_range,
                "sessions_traded": summary.sessions_traded,
                "risk_size_skips": summary.risk_size_skips,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": trade_metrics.as_dict(),
                "trade_metrics": trade_metrics.as_dict(),
                "worst_basket": round(min(summary.basket_pnls), 2),
                "worst_trade": round(min(summary.basket_pnls), 2),
                "longest_losing_streak": _longest_losing_streak(summary.basket_pnls),
                "baskets_per_week": round(summary.total_baskets / weeks, 3),
                "trades_per_week": round(summary.total_baskets / weeks, 3),
                "risk_model": "0.25% of current balance, rounded down to broker lot step",
                "verdict": verdict,
                "source_sha256": LONDON_SOURCE_SHA256,
            }
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=trade_metrics.net_profit,
                gross_profit=trade_metrics.gross_profit,
                gross_loss=trade_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=trade_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=drawdown_percent,
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=trade_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"{LONDON_STRATEGY_NAME} completed: {verdict['label']}",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "trades": summary.total_baskets,
                    "net_profit": trade_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "verdict": verdict["code"],
                    "test_segment": test_segment,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("London Opening Range backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "5min",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "error",
                "backtester",
                f"{LONDON_STRATEGY_NAME} backtest failed",
                {"run_id": run_id, "error": str(exc)},
            )

    async def _run_new_york_momentum(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval = "1min"
        test_segment = str(request.get("test_segment", "full"))
        strategy_code = "new_york_morning_momentum"
        accuracy = "Complete M1 signal window with M1 entry, stop, gap and forced-exit replay"
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": "Loading verified XAU/USD M1 candles for the once-a-day New York replay",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1min",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                    "locked_development_run_id": request.get("locked_development_run_id"),
                    "source_sha256": NEW_YORK_MOMENTUM_SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"{NEW_YORK_MOMENTUM_STRATEGY_NAME} M1 replay started",
                {"run_id": run_id, "test_segment": test_segment},
            )

            params = NewYorkMorningMomentumParameters(
                timezone_name=str(request.get("timezone_name", "America/New_York")),
                signal_start_hour=int(request.get("signal_start_hour", 8)),
                signal_start_minute=int(request.get("signal_start_minute", 30)),
                signal_minutes=int(request.get("signal_minutes", 30)),
                entry_hour=int(request.get("entry_hour", 9)),
                entry_minute=int(request.get("entry_minute", 0)),
                force_exit_hour=int(request.get("force_exit_hour", 15)),
                force_exit_minute=int(request.get("force_exit_minute", 55)),
                risk_percent=float(request.get("risk_percent", 0.25)),
                minimum_lot=float(request.get("minimum_lot", 0.01)),
                lot_step=float(request.get("lot_step", 0.01)),
                maximum_lot=float(request.get("maximum_lot", 1.0)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            simulator = NewYorkMorningMomentumBacktester(
                float(request.get("starting_balance", 10_000.0)),
                params,
            )

            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError("No M1 candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0

            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event(
                            "warning",
                            "backtester",
                            "New York Morning Momentum backtest cancelled",
                            {"run_id": run_id},
                        )
                        return
                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1
                page_processed = 0
                last_processed_row: dict[str, Any] | None = None
                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                    page_processed += 1
                    last_processed_row = row
                    if simulator.account_ruined:
                        break
                processed += page_processed
                if last_processed_row is not None:
                    cursor = str(last_processed_row["candle_time"])

                trade_buffer.extend(trade.to_trade_row(run_id) for trade in simulator.drain_trades())
                basket_buffer.extend(trade.to_basket_row(run_id) for trade in simulator.drain_baskets())
                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                if processed - last_progress_update >= 10_000 or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified M1 candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "signal_interval": "1min",
                            "strategy": strategy_code,
                            "test_segment": test_segment,
                            "locked_development_run_id": request.get("locked_development_run_id"),
                            "sessions_traded": simulator.sessions_traded,
                            "maximum_trades_per_day": 1,
                            "source_sha256": NEW_YORK_MOMENTUM_SOURCE_SHA256,
                        },
                    )
                if simulator.account_ruined or len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_trade_row(run_id) for trade in final_trades)
            basket_buffer.extend(trade.to_basket_row(run_id) for trade in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.basket_pnls:
                raise RuntimeError("No complete New York Morning Momentum trades were found in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            trade_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance)
            profit_factor = (
                trade_metrics.profit_factor
                if trade_metrics.profit_factor is not None and math.isfinite(trade_metrics.profit_factor)
                else None
            )
            recovery_factor = (
                trade_metrics.recovery_factor
                if trade_metrics.recovery_factor is not None and math.isfinite(trade_metrics.recovery_factor)
                else None
            )
            first = datetime.fromisoformat(summary.first_candle) if summary.first_candle else None
            last = datetime.fromisoformat(summary.last_candle) if summary.last_candle else None
            weeks = max(1.0 / 7.0, ((last - first).total_seconds() / 604800.0) if first and last else 0.0)
            drawdown_percent = max(trade_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent)
            verdict = _daily_momentum_verdict(
                net_profit=trade_metrics.net_profit,
                profit_factor=trade_metrics.profit_factor,
                expectancy=trade_metrics.expectancy,
                max_drawdown_percent=drawdown_percent,
                total_trades=summary.total_baskets,
                yearly_net=summary.yearly_net,
                test_segment=test_segment,
                locked_development_run_id=request.get("locked_development_run_id"),
                account_ruined=summary.account_ruined,
            )
            reliability = {
                "progress_percent": 100,
                "message": (
                    f"{NEW_YORK_MOMENTUM_STRATEGY_NAME} stopped when the account reached $0"
                    if summary.account_ruined
                    else f"{NEW_YORK_MOMENTUM_STRATEGY_NAME} backtest complete"
                ),
                "accuracy": accuracy,
                "warning": "Signals and execution use verified M1 bars. M1 still cannot prove tick ordering or exact broker fills; verify any survivor with MT5 real ticks.",
                "input_interval": data_interval,
                "signal_interval": "1min",
                "strategy": strategy_code,
                "test_segment": test_segment,
                "locked_development_run_id": request.get("locked_development_run_id"),
                "candles_processed": summary.candles_processed,
                "candles_available": expected_rows,
                "terminated_early": summary.account_ruined and summary.candles_processed < expected_rows,
                "account_ruined": summary.account_ruined,
                "ruin_time": summary.ruin_time,
                "ambiguous_candles": 0,
                "maximum_trades_per_day": 1,
                "sessions_seen": summary.sessions_seen,
                "eligible_sessions": summary.eligible_sessions,
                "complete_signal_windows": summary.complete_signal_windows,
                "sessions_traded": summary.sessions_traded,
                "incomplete_window_skips": summary.incomplete_window_skips,
                "doji_skips": summary.doji_skips,
                "risk_size_skips": summary.risk_size_skips,
                "gap_stop_fills": summary.gap_stop_fills,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "profitable_years": sum(float(value) > 0 for value in summary.yearly_net.values()),
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": trade_metrics.as_dict(),
                "trade_metrics": trade_metrics.as_dict(),
                "worst_basket": round(min(summary.basket_pnls), 2),
                "worst_trade": round(min(summary.basket_pnls), 2),
                "longest_losing_streak": _longest_losing_streak(summary.basket_pnls),
                "baskets_per_week": round(summary.total_baskets / weeks, 3),
                "trades_per_week": round(summary.total_baskets / weeks, 3),
                "risk_model": "0.25% of current balance, rounded down to broker lot step",
                "verdict": verdict,
                "source_sha256": NEW_YORK_MOMENTUM_SOURCE_SHA256,
            }
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=trade_metrics.net_profit,
                gross_profit=trade_metrics.gross_profit,
                gross_loss=trade_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=trade_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=drawdown_percent,
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=trade_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"{NEW_YORK_MOMENTUM_STRATEGY_NAME} completed: {verdict['label']}",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "trades": summary.total_baskets,
                    "net_profit": trade_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "verdict": verdict["code"],
                    "test_segment": test_segment,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("New York Morning Momentum backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1min",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "error",
                "backtester",
                f"{NEW_YORK_MOMENTUM_STRATEGY_NAME} backtest failed",
                {"run_id": run_id, "error": str(exc)},
            )

    async def _run_comex_closing_momentum(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval = "1min"
        test_segment = str(request.get("test_segment", "full"))
        strategy_code = "comex_closing_momentum"
        accuracy = "Verified M1 reference, 13:00 entry, hard-money stop and exact 13:30 exit replay"
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": "Loading verified XAU/USD M1 candles for the COMEX closing-momentum replay",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1min",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                    "locked_development_run_id": request.get("locked_development_run_id"),
                    "source_sha256": COMEX_CLOSING_MOMENTUM_SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"{COMEX_CLOSING_MOMENTUM_STRATEGY_NAME} M1 replay started",
                {"run_id": run_id, "test_segment": test_segment},
            )

            params = ComexClosingMomentumParameters(
                timezone_name=str(request.get("timezone_name", "America/New_York")),
                reference_hour=int(request.get("reference_hour", 13)),
                reference_minute=int(request.get("reference_minute", 29)),
                entry_hour=int(request.get("entry_hour", 13)),
                entry_minute=int(request.get("entry_minute", 0)),
                exit_hour=int(request.get("exit_hour", 13)),
                exit_minute=int(request.get("exit_minute", 30)),
                fixed_lot=float(request.get("fixed_lot", 0.01)),
                maximum_loss_percent=float(request.get("maximum_loss_percent", 0.25)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            simulator = ComexClosingMomentumBacktester(
                float(request.get("starting_balance", 10_000.0)),
                params,
            )

            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError("No M1 candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0

            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event(
                            "warning",
                            "backtester",
                            "COMEX Closing Momentum backtest cancelled",
                            {"run_id": run_id},
                        )
                        return
                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1
                page_processed = 0
                last_processed_row: dict[str, Any] | None = None
                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                    page_processed += 1
                    last_processed_row = row
                    if simulator.account_ruined:
                        break
                processed += page_processed
                if last_processed_row is not None:
                    cursor = str(last_processed_row["candle_time"])

                trade_buffer.extend(trade.to_trade_row(run_id) for trade in simulator.drain_trades())
                basket_buffer.extend(trade.to_basket_row(run_id) for trade in simulator.drain_baskets())
                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                if processed - last_progress_update >= 10_000 or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified M1 candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "signal_interval": "1min",
                            "strategy": strategy_code,
                            "test_segment": test_segment,
                            "locked_development_run_id": request.get("locked_development_run_id"),
                            "sessions_traded": simulator.sessions_traded,
                            "settlement_references": simulator.settlement_references,
                            "maximum_trades_per_day": 1,
                            "source_sha256": COMEX_CLOSING_MOMENTUM_SOURCE_SHA256,
                        },
                    )
                if simulator.account_ruined or len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_trade_row(run_id) for trade in final_trades)
            basket_buffer.extend(trade.to_basket_row(run_id) for trade in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.basket_pnls:
                raise RuntimeError("No complete COMEX Closing Momentum trades were found in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            trade_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance)
            profit_factor = (
                trade_metrics.profit_factor
                if trade_metrics.profit_factor is not None and math.isfinite(trade_metrics.profit_factor)
                else None
            )
            recovery_factor = (
                trade_metrics.recovery_factor
                if trade_metrics.recovery_factor is not None and math.isfinite(trade_metrics.recovery_factor)
                else None
            )
            first = datetime.fromisoformat(summary.first_candle) if summary.first_candle else None
            last = datetime.fromisoformat(summary.last_candle) if summary.last_candle else None
            weeks = max(1.0 / 7.0, ((last - first).total_seconds() / 604800.0) if first and last else 0.0)
            drawdown_percent = max(trade_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent)
            verdict = _daily_momentum_verdict(
                net_profit=trade_metrics.net_profit,
                profit_factor=trade_metrics.profit_factor,
                expectancy=trade_metrics.expectancy,
                max_drawdown_percent=drawdown_percent,
                total_trades=summary.total_baskets,
                yearly_net=summary.yearly_net,
                test_segment=test_segment,
                locked_development_run_id=request.get("locked_development_run_id"),
                account_ruined=summary.account_ruined,
            )
            reliability = {
                "progress_percent": 100,
                "message": (
                    f"{COMEX_CLOSING_MOMENTUM_STRATEGY_NAME} stopped when the account reached $0"
                    if summary.account_ruined
                    else f"{COMEX_CLOSING_MOMENTUM_STRATEGY_NAME} backtest complete"
                ),
                "accuracy": accuracy,
                "warning": "The spot 13:29 M1 close is a proxy for the COMEX futures settlement. M1 cannot prove tick ordering or exact broker fills; verify any survivor with MT5 real ticks.",
                "input_interval": data_interval,
                "signal_interval": "1min",
                "strategy": strategy_code,
                "test_segment": test_segment,
                "locked_development_run_id": request.get("locked_development_run_id"),
                "candles_processed": summary.candles_processed,
                "candles_available": expected_rows,
                "terminated_early": summary.account_ruined and summary.candles_processed < expected_rows,
                "account_ruined": summary.account_ruined,
                "ruin_time": summary.ruin_time,
                "ambiguous_candles": 0,
                "maximum_trades_per_day": 1,
                "sessions_seen": summary.sessions_seen,
                "eligible_sessions": summary.eligible_sessions,
                "settlement_references": summary.settlement_references,
                "sessions_traded": summary.sessions_traded,
                "missing_reference_skips": summary.missing_reference_skips,
                "doji_skips": summary.doji_skips,
                "gap_stop_fills": summary.gap_stop_fills,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "profitable_years": sum(float(value) > 0 for value in summary.yearly_net.values()),
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": trade_metrics.as_dict(),
                "trade_metrics": trade_metrics.as_dict(),
                "worst_basket": round(min(summary.basket_pnls), 2),
                "worst_trade": round(min(summary.basket_pnls), 2),
                "longest_losing_streak": _longest_losing_streak(summary.basket_pnls),
                "baskets_per_week": round(summary.total_baskets / weeks, 3),
                "trades_per_week": round(summary.total_baskets / weeks, 3),
                "risk_model": "Fixed 0.01 lot with a hard stop capped at 0.25% of current balance",
                "verdict": verdict,
                "source_sha256": COMEX_CLOSING_MOMENTUM_SOURCE_SHA256,
            }
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=trade_metrics.net_profit,
                gross_profit=trade_metrics.gross_profit,
                gross_loss=trade_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=trade_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=drawdown_percent,
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=trade_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"{COMEX_CLOSING_MOMENTUM_STRATEGY_NAME} completed: {verdict['label']}",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "trades": summary.total_baskets,
                    "net_profit": trade_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "verdict": verdict["code"],
                    "test_segment": test_segment,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("COMEX Closing Momentum backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1min",
                    "strategy": strategy_code,
                    "test_segment": test_segment,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "error",
                "backtester",
                f"{COMEX_CLOSING_MOMENTUM_STRATEGY_NAME} backtest failed",
                {"run_id": run_id, "error": str(exc)},
            )

    async def _run_gold_session_anomaly(self, run_id: str, request: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc)
        data_interval = "1min"
        test_segment = str(request.get("test_segment", "full"))
        session_leg = str(request.get("session_leg", "overnight_long"))
        identity = gold_session_anomaly_identity(session_leg)
        strategy_code = identity["code"]
        accuracy = {
            "abnormal_momentum": "Verified M1 causal 60-day abnormal-return baseline, sign-specific GMT+3 entry, day-end exit and hard-money stop replay",
            "gld_fifth_half_hour_momentum": "Verified M1 11:30-12:00 New York predictor, 15:30 entry, 16:00 exit and hard-money stop replay",
            "gld_high_vol_fifth_half_hour_momentum": "Verified M1 30-return realized-volatility window, causal prior-60-window median, 15:30 entry, 16:00 exit and hard-money stop replay",
            "rest_of_day_close_momentum": "Verified M1 prior-16:00 New York reference, 15:30 entry, 16:00 exit and hard-money stop replay",
            "etf_intraday_short": "Verified M1 09:30 New York short entry, 16:00 exit and hard-money stop replay",
            "etf_overnight_long": "Verified M1 16:00 New York long entry, next eligible 09:30 exit, financing and hard-money stop replay",
            "overnight_long": "Verified M1 13:30 New York long entry, next eligible 08:20 exit, financing and hard-money stop replay",
            "asia_long": "Verified M1 18:00 New York long entry, 15:30 Shanghai exit and hard-money stop replay",
            "shanghai_day_long": "Verified M1 09:00 Shanghai long entry, 15:30 Shanghai exit and hard-money stop replay",
            "day_short": "Verified M1 08:20 New York short entry, 13:30 exit and hard-money stop replay",
        }.get(session_leg, "Verified M1 session-boundary replay")
        try:
            await self.repo.update_backtest_run(
                run_id,
                status="running",
                started_at=started_at.isoformat(),
                reliability={
                    "progress_percent": 0,
                    "message": f"Loading verified XAU/USD M1 candles for {identity['name']}",
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1min",
                    "strategy": strategy_code,
                    "session_leg": session_leg,
                    "test_segment": test_segment,
                    "locked_development_run_id": request.get("locked_development_run_id"),
                    "source_sha256": GOLD_SESSION_ANOMALY_SOURCE_SHA256,
                },
            )
            await self.repo.log_event(
                "info",
                "backtester",
                f"{identity['name']} M1 replay started",
                {"run_id": run_id, "test_segment": test_segment, "session_leg": session_leg},
            )

            params = GoldSessionAnomalyParameters(
                session_leg=session_leg,
                timezone_name=str(request.get("timezone_name", "America/New_York")),
                day_open_hour=int(request.get("day_open_hour", 8)),
                day_open_minute=int(request.get("day_open_minute", 20)),
                settlement_hour=int(request.get("settlement_hour", 13)),
                settlement_minute=int(request.get("settlement_minute", 30)),
                asia_entry_hour=int(request.get("asia_entry_hour", 18)),
                asia_entry_minute=int(request.get("asia_entry_minute", 0)),
                asia_exit_timezone_name=str(request.get("asia_exit_timezone_name", "Asia/Shanghai")),
                shanghai_entry_hour=int(request.get("shanghai_entry_hour", 9)),
                shanghai_entry_minute=int(request.get("shanghai_entry_minute", 0)),
                asia_exit_hour=int(request.get("asia_exit_hour", 15)),
                asia_exit_minute=int(request.get("asia_exit_minute", 30)),
                abnormal_timezone_name=str(request.get("abnormal_timezone_name", "Etc/GMT-3")),
                abnormal_lookback_days=int(request.get("abnormal_lookback_days", 60)),
                abnormal_sigma=float(request.get("abnormal_sigma", 2.0)),
                abnormal_negative_entry_hour=int(request.get("abnormal_negative_entry_hour", 17)),
                abnormal_negative_entry_minute=int(request.get("abnormal_negative_entry_minute", 0)),
                abnormal_positive_entry_hour=int(request.get("abnormal_positive_entry_hour", 19)),
                abnormal_positive_entry_minute=int(request.get("abnormal_positive_entry_minute", 0)),
                abnormal_exit_hour=int(request.get("abnormal_exit_hour", 23)),
                abnormal_exit_minute=int(request.get("abnormal_exit_minute", 59)),
                intraday_predictor_start_hour=int(request.get("intraday_predictor_start_hour", 11)),
                intraday_predictor_start_minute=int(request.get("intraday_predictor_start_minute", 30)),
                intraday_predictor_end_hour=int(request.get("intraday_predictor_end_hour", 12)),
                intraday_predictor_end_minute=int(request.get("intraday_predictor_end_minute", 0)),
                intraday_volatility_lookback_days=int(
                    request.get("intraday_volatility_lookback_days", 60)
                ),
                intraday_entry_hour=int(request.get("intraday_entry_hour", 15)),
                intraday_entry_minute=int(request.get("intraday_entry_minute", 30)),
                intraday_exit_hour=int(request.get("intraday_exit_hour", 16)),
                intraday_exit_minute=int(request.get("intraday_exit_minute", 0)),
                etf_market_open_hour=int(request.get("etf_market_open_hour", 9)),
                etf_market_open_minute=int(request.get("etf_market_open_minute", 30)),
                etf_market_close_hour=int(request.get("etf_market_close_hour", 16)),
                etf_market_close_minute=int(request.get("etf_market_close_minute", 0)),
                fixed_lot=float(request.get("fixed_lot", 0.01)),
                maximum_loss_percent=float(request.get("maximum_loss_percent", 0.25)),
                long_overnight_cost_per_001_lot=float(
                    request.get("long_overnight_cost_per_001_lot", 0.70)
                ),
                triple_swap_weekday=int(request.get("triple_swap_weekday", 2)),
                spread_price=float(request.get("spread_price", 0.05)),
                commission_per_001_lot=float(request.get("commission_per_001_lot", 0.08)),
                slippage_price=float(request.get("slippage_price", 0.0)),
                money_per_price_per_001_lot=float(request.get("money_per_price_per_001_lot", 1.0)),
                path_mode=str(request.get("path_mode", "candle_direction")),
            )
            simulator = GoldSessionAnomalyBacktester(
                float(request.get("starting_balance", 10_000.0)),
                params,
            )

            symbol = str(request.get("symbol", "XAU/USD"))
            date_from = request.get("date_from")
            date_to = request.get("date_to")
            if session_leg in {
                "abnormal_momentum",
                "gld_high_vol_fifth_half_hour_momentum",
            } and date_from:
                evaluation_start = datetime.fromisoformat(str(date_from).replace("Z", "+00:00"))
                warmup_from = (evaluation_start - timedelta(days=120)).isoformat()
                warmup_to = (evaluation_start - timedelta(microseconds=1)).isoformat()
                warmup_cursor: str | None = None
                while True:
                    warmup_page = await self.repo.fetch_candles_page(
                        symbol=symbol,
                        interval=data_interval,
                        after=warmup_cursor,
                        date_from=warmup_from,
                        date_to=warmup_to,
                        limit=1000,
                    )
                    if not warmup_page:
                        break
                    for row in warmup_page:
                        simulator.process_candle(
                            Candle.from_row(row),
                            allow_entry=False,
                            count_metrics=False,
                        )
                    warmup_cursor = str(warmup_page[-1]["candle_time"])
                    if len(warmup_page) < 1000:
                        break
                simulator.begin_evaluation()
            expected_rows = await self.repo.count_market_candles(symbol, data_interval, date_from, date_to)
            if expected_rows <= 0:
                raise RuntimeError("No M1 candles exist for the selected date range")

            cursor: str | None = None
            processed = 0
            trade_buffer: list[dict[str, Any]] = []
            basket_buffer: list[dict[str, Any]] = []
            last_progress_update = 0
            page_number = 0

            while True:
                if page_number % 10 == 0:
                    run = await self.repo.get_backtest_run(run_id)
                    if not run or run.get("status") == "cancelled":
                        await self.repo.log_event(
                            "warning",
                            "backtester",
                            f"{identity['name']} backtest cancelled",
                            {"run_id": run_id},
                        )
                        return
                page = await self.repo.fetch_candles_page(
                    symbol=symbol,
                    interval=data_interval,
                    after=cursor,
                    date_from=date_from,
                    date_to=date_to,
                    limit=1000,
                )
                if not page:
                    break
                page_number += 1
                page_processed = 0
                last_processed_row: dict[str, Any] | None = None
                for row in page:
                    simulator.process_candle(Candle.from_row(row))
                    page_processed += 1
                    last_processed_row = row
                    if simulator.account_ruined:
                        break
                processed += page_processed
                if last_processed_row is not None:
                    cursor = str(last_processed_row["candle_time"])

                trade_buffer.extend(trade.to_trade_row(run_id) for trade in simulator.drain_trades())
                basket_buffer.extend(trade.to_basket_row(run_id) for trade in simulator.drain_baskets())
                if len(trade_buffer) >= 1000:
                    await self.repo.bulk_insert_backtest_trades(trade_buffer)
                    trade_buffer.clear()
                if len(basket_buffer) >= 500:
                    await self.repo.bulk_insert_backtest_baskets(basket_buffer)
                    basket_buffer.clear()

                progress = min(99.5, processed / expected_rows * 100.0)
                if processed - last_progress_update >= 10_000 or processed == expected_rows:
                    last_progress_update = processed
                    await self.repo.update_backtest_run(
                        run_id,
                        reliability={
                            "progress_percent": round(progress, 3),
                            "message": f"Processed {processed:,} of {expected_rows:,} verified M1 candles",
                            "accuracy": accuracy,
                            "input_interval": data_interval,
                            "signal_interval": "1min",
                            "strategy": strategy_code,
                            "session_leg": session_leg,
                            "test_segment": test_segment,
                            "locked_development_run_id": request.get("locked_development_run_id"),
                            "sessions_traded": simulator.sessions_traded,
                            "maximum_trades_per_day": 1,
                            "source_sha256": GOLD_SESSION_ANOMALY_SOURCE_SHA256,
                        },
                    )
                if simulator.account_ruined or len(page) < 1000:
                    break

            final_trades, final_baskets = simulator.finalise()
            trade_buffer.extend(trade.to_trade_row(run_id) for trade in final_trades)
            basket_buffer.extend(trade.to_basket_row(run_id) for trade in final_baskets)
            if trade_buffer:
                await self.repo.bulk_insert_backtest_trades(trade_buffer)
            if basket_buffer:
                await self.repo.bulk_insert_backtest_baskets(basket_buffer)

            summary = simulator.summary()
            if not summary.basket_pnls:
                raise RuntimeError(f"No complete {identity['name']} trades were found in the selected period")
            position_metrics = calculate_metrics(summary.position_pnls, summary.starting_balance)
            trade_metrics = calculate_metrics(summary.basket_pnls, summary.starting_balance)
            profit_factor = (
                trade_metrics.profit_factor
                if trade_metrics.profit_factor is not None and math.isfinite(trade_metrics.profit_factor)
                else None
            )
            recovery_factor = (
                trade_metrics.recovery_factor
                if trade_metrics.recovery_factor is not None and math.isfinite(trade_metrics.recovery_factor)
                else None
            )
            first = datetime.fromisoformat(summary.first_candle) if summary.first_candle else None
            last = datetime.fromisoformat(summary.last_candle) if summary.last_candle else None
            weeks = max(1.0 / 7.0, ((last - first).total_seconds() / 604800.0) if first and last else 0.0)
            drawdown_percent = max(trade_metrics.max_drawdown_percent, summary.max_equity_drawdown_percent)
            verdict_builder = (
                _abnormal_momentum_verdict
                if session_leg == "abnormal_momentum"
                else (
                    _high_vol_close_momentum_verdict
                    if session_leg == "gld_high_vol_fifth_half_hour_momentum"
                    else _daily_momentum_verdict
                )
            )
            verdict = verdict_builder(
                net_profit=trade_metrics.net_profit,
                profit_factor=trade_metrics.profit_factor,
                expectancy=trade_metrics.expectancy,
                max_drawdown_percent=drawdown_percent,
                total_trades=summary.total_baskets,
                yearly_net=summary.yearly_net,
                test_segment=test_segment,
                locked_development_run_id=request.get("locked_development_run_id"),
                account_ruined=summary.account_ruined,
            )
            reliability = {
                "progress_percent": 100,
                "message": (
                    f"{identity['name']} stopped when the account reached $0"
                    if summary.account_ruined
                    else f"{identity['name']} backtest complete"
                ),
                "accuracy": accuracy,
                "warning": (
                    "M1 cannot prove tick ordering or exact broker fills. The overnight financing input is a frozen conservative proxy and any survivor still needs broker-specific MT5 real-tick verification."
                    if session_leg in {"overnight_long", "etf_overnight_long"}
                    else "M1 cannot prove tick ordering or exact broker fills. Any survivor still needs broker-specific MT5 real-tick verification."
                ),
                "input_interval": data_interval,
                "signal_interval": "1min",
                "strategy": strategy_code,
                "session_leg": session_leg,
                "test_segment": test_segment,
                "locked_development_run_id": request.get("locked_development_run_id"),
                "candles_processed": summary.candles_processed,
                "candles_available": expected_rows,
                "terminated_early": summary.account_ruined and summary.candles_processed < expected_rows,
                "account_ruined": summary.account_ruined,
                "ruin_time": summary.ruin_time,
                "ambiguous_candles": 0,
                "maximum_trades_per_day": 1,
                "sessions_seen": summary.sessions_seen,
                "eligible_sessions": summary.eligible_sessions,
                "sessions_traded": summary.sessions_traded,
                "missing_entry_skips": summary.missing_entry_skips,
                "missing_exit_fallbacks": summary.missing_exit_fallbacks,
                "incomplete_end_discards": summary.incomplete_end_discards,
                "abnormal_completed_days": summary.abnormal_completed_days,
                "abnormal_warmup_skips": summary.abnormal_warmup_skips,
                "abnormal_negative_signals": summary.abnormal_negative_signals,
                "abnormal_positive_signals": summary.abnormal_positive_signals,
                "abnormal_missing_open_skips": summary.abnormal_missing_open_skips,
                "abnormal_missing_signal_skips": summary.abnormal_missing_signal_skips,
                "high_vol_completed_windows": summary.high_vol_completed_windows,
                "high_vol_warmup_windows": summary.high_vol_warmup_windows,
                "high_vol_qualifying_windows": summary.high_vol_qualifying_windows,
                "high_vol_filtered_windows": summary.high_vol_filtered_windows,
                "high_vol_incomplete_windows": summary.high_vol_incomplete_windows,
                "financing_events": summary.financing_events,
                "financing_costs": summary.financing_costs,
                "gap_stop_fills": summary.gap_stop_fills,
                "first_candle": summary.first_candle,
                "last_candle": summary.last_candle,
                "exit_reasons": summary.exit_reasons,
                "monthly_net": summary.monthly_net,
                "yearly_net": summary.yearly_net,
                "profitable_years": sum(float(value) > 0 for value in summary.yearly_net.values()),
                "position_metrics": position_metrics.as_dict(),
                "basket_metrics": trade_metrics.as_dict(),
                "trade_metrics": trade_metrics.as_dict(),
                "worst_basket": round(min(summary.basket_pnls), 2),
                "worst_trade": round(min(summary.basket_pnls), 2),
                "longest_losing_streak": _longest_losing_streak(summary.basket_pnls),
                "baskets_per_week": round(summary.total_baskets / weeks, 3),
                "trades_per_week": round(summary.total_baskets / weeks, 3),
                "risk_model": "Fixed 0.01 lot with a hard stop capped at 0.25% of current balance",
                "verdict": verdict,
                "source_sha256": GOLD_SESSION_ANOMALY_SOURCE_SHA256,
            }
            await self.repo.update_backtest_run(
                run_id,
                status="complete",
                ending_balance=summary.ending_balance,
                net_profit=trade_metrics.net_profit,
                gross_profit=trade_metrics.gross_profit,
                gross_loss=trade_metrics.gross_loss,
                profit_factor=profit_factor,
                max_balance_drawdown=trade_metrics.max_drawdown,
                max_equity_drawdown=summary.max_equity_drawdown,
                max_drawdown_percent=drawdown_percent,
                total_positions=summary.total_positions,
                total_baskets=summary.total_baskets,
                winning_baskets=summary.winning_baskets,
                losing_baskets=summary.losing_baskets,
                basket_win_rate=(summary.winning_baskets / summary.total_baskets * 100.0) if summary.total_baskets else 0,
                expectancy=trade_metrics.expectancy,
                recovery_factor=recovery_factor,
                reliability=reliability,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "backtester",
                f"{identity['name']} completed: {verdict['label']}",
                {
                    "run_id": run_id,
                    "candles": summary.candles_processed,
                    "trades": summary.total_baskets,
                    "net_profit": trade_metrics.net_profit,
                    "profit_factor": profit_factor,
                    "verdict": verdict["code"],
                    "test_segment": test_segment,
                    "session_leg": session_leg,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Gold Session Anomaly backtest %s failed", run_id)
            await self.repo.update_backtest_run(
                run_id,
                status="failed",
                error=str(exc),
                reliability={
                    "progress_percent": 0,
                    "message": str(exc),
                    "accuracy": accuracy,
                    "input_interval": data_interval,
                    "signal_interval": "1min",
                    "strategy": strategy_code,
                    "session_leg": session_leg,
                    "test_segment": test_segment,
                },
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "error",
                "backtester",
                f"{identity['name']} backtest failed",
                {"run_id": run_id, "error": str(exc)},
            )
