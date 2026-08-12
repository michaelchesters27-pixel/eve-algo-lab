from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.fixed_ladder_v261 import Candle
from app.backtesting.liquidity_basket import LiquidityBasketBacktester, LiquidityBasketParameters
from app.services.backtests import BacktestService, _liquidity_verdict, liquidity_settings_match


START = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        candle_time=START + timedelta(minutes=index),
        open=open_,
        high=high,
        low=low,
        close=close,
    )


def parameters(**overrides) -> LiquidityBasketParameters:
    values = {
        "positions_per_basket": 4,
        "fixed_lot": 0.01,
        "lookback_candles": 3,
        "trend_period": 3,
        "use_trend_filter": False,
        "minimum_sweep_price": 0.0,
        "profit_target_money": 4.0,
        "basket_stop_money": 8.0,
        "maximum_hold_minutes": 180,
        "cooldown_candles": 0,
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "slippage_price": 0.0,
        "money_per_price_per_001_lot": 1.0,
        "path_mode": "candle_direction",
    }
    values.update(overrides)
    return LiquidityBasketParameters(**values)


def seed_sell_signal(simulator: LiquidityBasketBacktester) -> None:
    simulator.process_candle(candle(0, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(candle(1, 100.0, 101.2, 99.2, 100.2))
    simulator.process_candle(candle(2, 100.2, 101.4, 99.4, 100.4))
    # Sweeps the prior high, rejects it and closes bearish. Entry must wait.
    simulator.process_candle(candle(3, 101.6, 102.0, 100.8, 101.2))


def test_signal_is_confirmed_at_close_and_four_positions_open_next_candle() -> None:
    simulator = LiquidityBasketBacktester(1000.0, parameters())
    seed_sell_signal(simulator)

    assert simulator.positions == []
    assert simulator.summary().signals_detected == 1

    simulator.process_candle(candle(4, 101.2, 101.4, 100.8, 101.0))

    assert len(simulator.positions) == 4
    assert {position.side for position in simulator.positions} == {"sell"}
    assert {position.entry_price for position in simulator.positions} == {101.2}


def test_combined_four_dollar_target_closes_the_complete_basket() -> None:
    simulator = LiquidityBasketBacktester(1000.0, parameters())
    seed_sell_signal(simulator)
    # Four 0.01 positions make $4 when gold falls $1 from the common entry.
    simulator.process_candle(candle(4, 101.2, 101.3, 100.0, 100.4))

    trades, baskets = simulator.finalise()
    summary = simulator.summary()

    assert len(trades) == 4
    assert len(baskets) == 1
    assert baskets[0].exit_reason == "BASKET PROFIT TARGET"
    assert baskets[0].net_pnl == pytest.approx(4.0)
    assert sum(trade.net_pnl for trade in trades) == pytest.approx(4.0)
    assert summary.ending_balance == pytest.approx(1004.0)
    assert summary.winning_baskets == 1


def test_hard_eight_dollar_basket_loss_closes_all_four_positions() -> None:
    simulator = LiquidityBasketBacktester(1000.0, parameters())
    seed_sell_signal(simulator)
    simulator.process_candle(candle(4, 101.2, 103.5, 101.0, 102.8))

    trades, baskets = simulator.finalise()

    assert len(trades) == 4
    assert len(baskets) == 1
    assert baskets[0].exit_reason == "HARD BASKET LOSS LIMIT"
    assert baskets[0].net_pnl == pytest.approx(-8.0)
    assert simulator.summary().ending_balance == pytest.approx(992.0)


def test_spread_and_commission_are_included_before_target_is_declared() -> None:
    simulator = LiquidityBasketBacktester(
        1000.0,
        parameters(spread_price=0.10, commission_per_001_lot=0.10),
    )
    seed_sell_signal(simulator)
    simulator.process_candle(candle(4, 101.2, 101.25, 100.0, 100.3))
    trades, baskets = simulator.finalise()

    assert len(baskets) == 1
    assert baskets[0].exit_reason == "BASKET PROFIT TARGET"
    assert baskets[0].net_pnl == pytest.approx(4.0)
    assert sum(trade.costs for trade in trades) == pytest.approx(0.4)


def test_maximum_hold_prevents_an_unbounded_open_basket() -> None:
    simulator = LiquidityBasketBacktester(1000.0, parameters(maximum_hold_minutes=2))
    seed_sell_signal(simulator)
    simulator.process_candle(candle(4, 101.2, 101.3, 101.0, 101.1))
    simulator.process_candle(candle(5, 101.1, 101.3, 101.0, 101.2))
    # At the time limit the candle later rallies enough to hit the target, but
    # the basket must already have been closed at this candle's 101.3 open.
    simulator.process_candle(candle(6, 101.3, 101.4, 100.0, 100.2))

    _, baskets = simulator.finalise()

    assert len(baskets) == 1
    assert baskets[0].exit_reason == "MAXIMUM HOLD TIME"
    assert baskets[0].closed_at == START + timedelta(minutes=6)
    assert baskets[0].net_pnl == pytest.approx(-0.4)


def test_same_bar_target_and_stop_is_counted_as_ambiguous() -> None:
    simulator = LiquidityBasketBacktester(
        1000.0,
        parameters(profit_target_money=4.0, basket_stop_money=4.0, path_mode="open_high_low_close"),
    )
    seed_sell_signal(simulator)
    simulator.process_candle(candle(4, 101.2, 102.5, 100.0, 101.0))

    _, baskets = simulator.finalise()

    assert simulator.summary().ambiguous_candles == 1
    assert baskets[0].exit_reason == "HARD BASKET LOSS LIMIT"


def test_parameter_validation_rejects_missing_loss_control() -> None:
    with pytest.raises(ValueError, match="loss limit"):
        LiquidityBasketBacktester(1000.0, parameters(basket_stop_money=0.0))


def test_verdict_requires_profit_drawdown_and_enough_baskets_together() -> None:
    promising = _liquidity_verdict(
        net_profit=300.0,
        profit_factor=1.35,
        expectancy=1.5,
        max_drawdown_percent=12.0,
        total_baskets=200,
        test_segment="development",
    )
    insufficient = _liquidity_verdict(
        net_profit=30.0,
        profit_factor=2.0,
        expectancy=3.0,
        max_drawdown_percent=2.0,
        total_baskets=10,
        test_segment="full",
    )
    failed = _liquidity_verdict(
        net_profit=-50.0,
        profit_factor=0.8,
        expectancy=-0.5,
        max_drawdown_percent=25.0,
        total_baskets=200,
        test_segment="full",
    )
    unlocked = _liquidity_verdict(
        net_profit=300.0,
        profit_factor=1.35,
        expectancy=1.5,
        max_drawdown_percent=12.0,
        total_baskets=200,
        test_segment="untouched",
    )
    untouched = _liquidity_verdict(
        net_profit=300.0,
        profit_factor=1.35,
        expectancy=1.5,
        max_drawdown_percent=12.0,
        total_baskets=200,
        test_segment="untouched",
        locked_development_run_id="development-run-1",
    )
    no_losses = _liquidity_verdict(
        net_profit=400.0,
        profit_factor=float("inf"),
        expectancy=4.0,
        max_drawdown_percent=0.0,
        total_baskets=100,
        test_segment="development",
    )

    assert promising["code"] == "promising"
    assert insufficient["code"] == "insufficient_evidence"
    assert failed["code"] == "failed"
    assert unlocked["code"] == "unlocked_untouched"
    assert untouched["code"] == "untouched_pass"
    assert no_losses["code"] == "promising"


def test_untouched_setting_lock_compares_costs_risk_and_entry_rules() -> None:
    baseline = {
        "symbol": "XAU/USD",
        "starting_balance": 1000.0,
        "positions_per_basket": 4,
        "fixed_lot": 0.02,
        "lookback_candles": 20,
        "trend_period": 50,
        "use_trend_filter": True,
        "minimum_sweep_price": 0.05,
        "profit_target_money": 4.0,
        "basket_stop_money": 8.0,
        "maximum_hold_minutes": 180,
        "cooldown_candles": 5,
        "spread_price": 0.05,
        "commission_per_001_lot": 0.08,
        "slippage_price": 0.0,
        "money_per_price_per_001_lot": 1.0,
        "path_mode": "candle_direction",
    }
    identical = {**baseline, "test_segment": "untouched"}
    changed_cost = {**identical, "spread_price": 0.04}

    assert liquidity_settings_match(baseline, identical)
    assert not liquidity_settings_match(baseline, changed_cost)


class FakeBacktestRepository:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.run = {"id": "run-1", "status": "queued"}
        self.trades: list[dict] = []
        self.baskets: list[dict] = []
        self.events: list[tuple] = []

    async def update_backtest_run(self, run_id: str, **changes) -> None:
        assert run_id == "run-1"
        self.run.update(changes)

    async def log_event(self, *args) -> None:
        self.events.append(args)

    async def count_market_candles(self, *args, **kwargs) -> int:
        return len(self.rows)

    async def get_backtest_run(self, run_id: str) -> dict:
        return self.run

    async def fetch_candles_page(self, *args, **kwargs) -> list[dict]:
        return self.rows

    async def bulk_insert_backtest_trades(self, rows: list[dict]) -> None:
        self.trades.extend(rows)

    async def bulk_insert_backtest_baskets(self, rows: list[dict]) -> None:
        self.baskets.extend(rows)


@pytest.mark.asyncio
async def test_service_streams_m1_rows_and_persists_a_complete_result() -> None:
    source = [
        candle(0, 100.0, 101.0, 99.0, 100.0),
        candle(1, 100.0, 101.2, 99.2, 100.2),
        candle(2, 100.2, 101.4, 99.4, 100.4),
        candle(3, 101.6, 102.0, 100.8, 101.2),
        candle(4, 101.2, 101.3, 100.0, 100.4),
    ]
    rows = [
        {
            "candle_time": item.candle_time.isoformat(),
            "open": item.open,
            "high": item.high,
            "low": item.low,
            "close": item.close,
            "volume": 1,
        }
        for item in source
    ]
    repo = FakeBacktestRepository(rows)
    service = BacktestService(repo)  # type: ignore[arg-type]
    request = {
        "symbol": "XAU/USD",
        "starting_balance": 1000.0,
        "positions_per_basket": 4,
        "fixed_lot": 0.01,
        "lookback_candles": 3,
        "trend_period": 3,
        "use_trend_filter": False,
        "minimum_sweep_price": 0.0,
        "profit_target_money": 4.0,
        "basket_stop_money": 8.0,
        "maximum_hold_minutes": 180,
        "cooldown_candles": 0,
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "slippage_price": 0.0,
        "money_per_price_per_001_lot": 1.0,
        "path_mode": "candle_direction",
        "test_segment": "full",
    }

    await service._run_liquidity("run-1", request)

    assert repo.run["status"] == "complete"
    assert repo.run["net_profit"] == pytest.approx(4.0)
    assert repo.run["total_positions"] == 4
    assert repo.run["total_baskets"] == 1
    assert repo.run["reliability"]["verdict"]["code"] == "insufficient_evidence"
    assert len(repo.trades) == 4
    assert len(repo.baskets) == 1
