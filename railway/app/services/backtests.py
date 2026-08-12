from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

from app.backtesting.fixed_ladder_v261 import Candle, FixedLadderParameters, FixedLadderV261Backtester
from app.backtesting.liquidity_basket import LiquidityBasketBacktester, LiquidityBasketParameters
from app.backtesting.london_opening_range import LondonOpeningRangeBacktester, LondonOpeningRangeParameters
from app.backtesting.metrics import calculate_metrics
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
