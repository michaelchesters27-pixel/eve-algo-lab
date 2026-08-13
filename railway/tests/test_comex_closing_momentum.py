from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.comex_closing_momentum import (
    ComexClosingMomentumBacktester,
    ComexClosingMomentumParameters,
)
from app.backtesting.fixed_ladder_v261 import Candle
from app.models.schemas import ComexClosingMomentumBacktestRequest
from app.services.backtests import BacktestService, comex_closing_momentum_settings_match


WINTER_REFERENCE = datetime(2026, 1, 5, 18, 29, tzinfo=timezone.utc)
WINTER_ENTRY = datetime(2026, 1, 6, 18, 0, tzinfo=timezone.utc)


def parameters(**overrides) -> ComexClosingMomentumParameters:
    values = {
        "fixed_lot": 0.01,
        "maximum_loss_percent": 0.25,
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "slippage_price": 0.0,
        "money_per_price_per_001_lot": 1.0,
        "path_mode": "candle_direction",
    }
    values.update(overrides)
    return ComexClosingMomentumParameters(**values)


def minute(at: datetime, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(candle_time=at, open=open_, high=high, low=low, close=close)


def seed_reference(
    simulator: ComexClosingMomentumBacktester,
    at: datetime = WINTER_REFERENCE,
    price: float = 100.0,
) -> None:
    simulator.process_candle(minute(at, price, price + 1.0, price - 1.0, price))


def open_buy(simulator: ComexClosingMomentumBacktester) -> None:
    seed_reference(simulator)
    simulator.process_candle(minute(WINTER_ENTRY, 105.0, 106.0, 104.0, 105.5))


def test_prior_settlement_move_opens_exactly_one_fixed_lot_buy_at_1300_new_york() -> None:
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)

    assert simulator.position is not None
    assert simulator.position.side == "buy"
    assert simulator.position.opened_at == WINTER_ENTRY
    assert simulator.position.lot_size == 0.01
    assert simulator.position.planned_risk_money == pytest.approx(25.0)
    assert simulator.position.stop_mid == pytest.approx(80.0)
    assert simulator.summary().sessions_traded == 1


def test_move_below_prior_settlement_opens_sell() -> None:
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    seed_reference(simulator, price=100.0)
    simulator.process_candle(minute(WINTER_ENTRY, 95.0, 96.0, 94.0, 94.5))

    assert simulator.position is not None
    assert simulator.position.side == "sell"


def test_strategy_cannot_reenter_after_daily_hard_stop() -> None:
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)
    simulator.process_candle(minute(WINTER_ENTRY + timedelta(minutes=1), 105.5, 106.0, 79.0, 80.0))
    assert simulator.position is None

    for offset in range(2, 31):
        simulator.process_candle(minute(WINTER_ENTRY + timedelta(minutes=offset), 105.0, 120.0, 70.0, 110.0))

    assert simulator.position is None
    assert simulator.summary().total_baskets == 1
    assert simulator.summary().sessions_traded == 1


def test_missing_prior_reference_skips_the_day() -> None:
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    simulator.process_candle(minute(WINTER_REFERENCE + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(minute(WINTER_ENTRY, 105.0, 106.0, 104.0, 105.0))

    assert simulator.position is None
    assert simulator.summary().missing_reference_skips == 1
    assert simulator.summary().sessions_traded == 0


def test_equal_reference_and_entry_price_skips_the_day() -> None:
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    seed_reference(simulator, price=100.0)
    simulator.process_candle(minute(WINTER_ENTRY, 100.0, 101.0, 99.0, 100.5))

    assert simulator.position is None
    assert simulator.summary().doji_skips == 1


def test_hard_money_stop_caps_loss_at_quarter_percent() -> None:
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)
    simulator.process_candle(minute(WINTER_ENTRY + timedelta(minutes=1), 105.5, 106.0, 79.0, 80.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].exit_reason == "HARD MONEY STOP"
    assert trades[0].exit_price == pytest.approx(80.0)
    assert trades[0].net_pnl == pytest.approx(-25.0)


def test_open_trade_is_closed_at_exact_1330_new_york_open() -> None:
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)
    exit_time = datetime(2026, 1, 6, 18, 30, tzinfo=timezone.utc)
    simulator.process_candle(minute(exit_time, 107.0, 110.0, 70.0, 80.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].closed_at == exit_time
    assert trades[0].exit_reason == "COMEX 13:30 EXIT"
    assert trades[0].exit_price == pytest.approx(107.0)
    assert trades[0].net_pnl == pytest.approx(2.0)


def test_new_york_dst_moves_reference_and_entry_one_hour_earlier_in_summer() -> None:
    reference = datetime(2026, 6, 8, 17, 29, tzinfo=timezone.utc)
    entry = datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc)
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    seed_reference(simulator, reference, 100.0)
    simulator.process_candle(minute(entry, 105.0, 106.0, 104.0, 105.0))

    assert simulator.position is not None
    assert simulator.position.opened_at == entry
    assert simulator.position.signal.session_date == "2026-06-09"


def test_friday_reference_can_seed_monday_after_weekend_session() -> None:
    friday_reference = datetime(2026, 1, 9, 18, 29, tzinfo=timezone.utc)
    sunday_bar = datetime(2026, 1, 11, 23, 0, tzinfo=timezone.utc)
    monday_entry = datetime(2026, 1, 12, 18, 0, tzinfo=timezone.utc)
    simulator = ComexClosingMomentumBacktester(10_000.0, parameters())
    seed_reference(simulator, friday_reference, 100.0)
    simulator.process_candle(minute(sunday_bar, 101.0, 102.0, 100.0, 101.0))
    simulator.process_candle(minute(monday_entry, 105.0, 106.0, 104.0, 105.0))

    assert simulator.position is not None
    assert simulator.position.side == "buy"


def test_request_defaults_lock_the_daily_comex_protocol() -> None:
    request = ComexClosingMomentumBacktestRequest()

    assert request.starting_balance == 10_000.0
    assert request.fixed_lot == 0.01
    assert request.maximum_loss_percent == 0.25
    assert request.timezone_name == "America/New_York"
    assert (request.reference_hour, request.reference_minute) == (13, 29)
    assert (request.entry_hour, request.entry_minute) == (13, 0)
    assert (request.exit_hour, request.exit_minute) == (13, 30)


def test_untouched_lock_includes_every_comex_rule_cost_and_risk_input() -> None:
    baseline = ComexClosingMomentumBacktestRequest().model_dump(mode="json")
    baseline["strategy"] = "comex_closing_momentum"
    untouched = {**baseline, "test_segment": "untouched"}

    assert comex_closing_momentum_settings_match(baseline, untouched)
    assert not comex_closing_momentum_settings_match(baseline, {**untouched, "maximum_loss_percent": 0.50})
    assert not comex_closing_momentum_settings_match(baseline, {**untouched, "entry_hour": 12})
    assert not comex_closing_momentum_settings_match(baseline, {**untouched, "spread_price": 0.10})


class FakeComexRepository:
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
async def test_service_persists_one_daily_comex_trade_and_verdict() -> None:
    source = [
        minute(WINTER_REFERENCE, 100.0, 101.0, 99.0, 100.0),
        minute(WINTER_ENTRY, 105.0, 106.0, 104.0, 105.5),
        minute(datetime(2026, 1, 6, 18, 30, tzinfo=timezone.utc), 107.0, 108.0, 106.0, 107.5),
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
    repo = FakeComexRepository(rows)
    service = BacktestService(repo)  # type: ignore[arg-type]
    request = {
        **ComexClosingMomentumBacktestRequest(test_segment="development").model_dump(mode="json"),
        "strategy": "comex_closing_momentum",
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
    }

    await service._run_comex_closing_momentum("run-1", request)

    assert repo.run["status"] == "complete"
    assert repo.run["net_profit"] == pytest.approx(2.0)
    assert repo.run["total_positions"] == 1
    assert repo.run["total_baskets"] == 1
    assert repo.run["reliability"]["strategy"] == "comex_closing_momentum"
    assert repo.run["reliability"]["maximum_trades_per_day"] == 1
    assert repo.run["reliability"]["settlement_references"] == 1
    assert len(repo.trades) == 1
    assert repo.trades[0]["metadata"]["strategy"] == "comex_closing_momentum"
    assert len(repo.baskets) == 1
