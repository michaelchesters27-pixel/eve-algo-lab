from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

from app.backtesting.fixed_ladder_v261 import Candle, FixedLadderParameters, FixedLadderV261Backtester
from app.backtesting.metrics import calculate_metrics
from app.services.supabase_repo import SupabaseRepository

logger = logging.getLogger(__name__)

STRATEGY_SLUG = "eve-fixed-ladder-v2-61"
STRATEGY_NAME = "EVE Twelve Data Fixed Ladder v2.61"
STRATEGY_VERSION = "2.61"
SOURCE_SHA256 = "f033bc756b8a066b8fdfe780ca36fe82363b3b70c2e4dd4a15e7d57546d02da9"


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

    async def start(self, run_id: str, request: dict[str, Any]) -> None:
        async with self._lock:
            if run_id in self.tasks and not self.tasks[run_id].done():
                return
            task = asyncio.create_task(self._run(run_id, request), name=f"backtest-{run_id}")
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
