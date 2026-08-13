from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.fixed_ladder_v261 import Candle
from app.backtesting.new_york_morning_momentum import (
    NewYorkMorningMomentumBacktester,
    NewYorkMorningMomentumParameters,
)
from app.models.schemas import NewYorkMorningMomentumBacktestRequest
from app.services.backtests import (
    BacktestService,
    _daily_momentum_verdict,
    new_york_momentum_settings_match,
)


WINTER_SIGNAL_START = datetime(2026, 1, 5, 13, 30, tzinfo=timezone.utc)


def parameters(**overrides) -> NewYorkMorningMomentumParameters:
    values = {
        "risk_percent": 0.25,
        "minimum_lot": 0.01,
        "lot_step": 0.01,
        "maximum_lot": 1.0,
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "slippage_price": 0.0,
        "money_per_price_per_001_lot": 1.0,
        "path_mode": "candle_direction",
    }
    values.update(overrides)
    return NewYorkMorningMomentumParameters(**values)


def minute(at: datetime, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(candle_time=at, open=open_, high=high, low=low, close=close)


def seed_signal_window(
    simulator: NewYorkMorningMomentumBacktester,
    start: datetime = WINTER_SIGNAL_START,
    *,
    skip: int | None = None,
    close_above_open: bool = True,
) -> None:
    for index in range(30):
        if index == skip:
            continue
        close = 105.0 if index == 29 and close_above_open else 100.0
        simulator.process_candle(
            minute(
                start + timedelta(minutes=index),
                100.0,
                110.0 if index == 0 else 106.0,
                95.0 if index == 0 else 99.0,
                close,
            )
        )


def open_buy(
    simulator: NewYorkMorningMomentumBacktester,
    start: datetime = WINTER_SIGNAL_START,
) -> None:
    seed_signal_window(simulator, start)
    simulator.process_candle(minute(start + timedelta(minutes=30), 105.0, 106.0, 104.0, 105.5))


def test_complete_window_opens_exactly_one_risk_sized_trade_at_0900_new_york() -> None:
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)

    assert simulator.position is not None
    assert simulator.position.side == "buy"
    assert simulator.position.opened_at == datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
    assert simulator.position.stop_mid == 95.0
    assert simulator.position.lot_size == pytest.approx(0.02)
    assert simulator.position.planned_risk_money == pytest.approx(20.0)
    assert simulator.summary().sessions_traded == 1


def test_strategy_cannot_reenter_after_the_daily_trade_stops() -> None:
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)
    simulator.process_candle(minute(WINTER_SIGNAL_START + timedelta(minutes=31), 105.5, 106.0, 94.0, 95.0))
    assert simulator.position is None

    for offset in range(32, 90):
        simulator.process_candle(minute(WINTER_SIGNAL_START + timedelta(minutes=offset), 105.0, 120.0, 90.0, 110.0))

    assert simulator.position is None
    assert simulator.summary().total_baskets == 1
    assert simulator.summary().sessions_traded == 1


def test_missing_signal_minute_skips_the_entire_day() -> None:
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    seed_signal_window(simulator, skip=12)
    simulator.process_candle(minute(WINTER_SIGNAL_START + timedelta(minutes=30), 105.0, 106.0, 104.0, 105.5))

    assert simulator.position is None
    assert simulator.summary().incomplete_window_skips == 1
    assert simulator.summary().sessions_traded == 0


def test_doji_signal_window_skips_the_entire_day() -> None:
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    seed_signal_window(simulator, close_above_open=False)
    simulator.process_candle(minute(WINTER_SIGNAL_START + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.5))

    assert simulator.position is None
    assert simulator.summary().doji_skips == 1


def test_hard_stop_closes_at_the_opposite_morning_range_edge() -> None:
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)
    simulator.process_candle(minute(WINTER_SIGNAL_START + timedelta(minutes=31), 105.5, 106.0, 94.0, 95.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].exit_reason == "MORNING RANGE STOP"
    assert trades[0].exit_price == 95.0
    assert trades[0].net_pnl == pytest.approx(-20.0)


def test_open_trade_is_forced_closed_at_1555_new_york() -> None:
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)
    force_exit = datetime(2026, 1, 5, 20, 55, tzinfo=timezone.utc)
    simulator.process_candle(minute(force_exit, 107.0, 108.0, 106.0, 107.5))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].closed_at == force_exit
    assert trades[0].exit_reason == "NEW YORK FORCE EXIT"
    assert trades[0].net_pnl == pytest.approx(4.0)


def test_missing_1555_bar_closes_at_the_last_available_session_bar_not_overnight() -> None:
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    open_buy(simulator)
    last_session_bar = datetime(2026, 1, 5, 20, 54, tzinfo=timezone.utc)
    simulator.process_candle(minute(last_session_bar, 106.0, 107.0, 105.0, 106.5))
    next_session = datetime(2026, 1, 6, 13, 30, tzinfo=timezone.utc)
    simulator.process_candle(minute(next_session, 120.0, 121.0, 119.0, 120.5))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].closed_at == last_session_bar
    assert trades[0].exit_price == 106.5
    assert trades[0].exit_reason == "LAST AVAILABLE SESSION BAR"


def test_new_york_dst_moves_the_0830_window_to_1230_utc_in_summer() -> None:
    summer_start = datetime(2026, 6, 8, 12, 30, tzinfo=timezone.utc)
    simulator = NewYorkMorningMomentumBacktester(10_000.0, parameters())
    open_buy(simulator, summer_start)

    assert simulator.position is not None
    assert simulator.position.opened_at == datetime(2026, 6, 8, 13, 0, tzinfo=timezone.utc)
    assert simulator.position.signal.session_date == "2026-06-08"


def test_request_defaults_lock_the_once_per_day_protocol() -> None:
    request = NewYorkMorningMomentumBacktestRequest()

    assert request.starting_balance == 10_000.0
    assert request.risk_percent == 0.25
    assert request.timezone_name == "America/New_York"
    assert (request.signal_start_hour, request.signal_start_minute, request.signal_minutes) == (8, 30, 30)
    assert (request.entry_hour, request.entry_minute) == (9, 0)
    assert (request.force_exit_hour, request.force_exit_minute) == (15, 55)


def test_untouched_lock_includes_every_daily_rule_cost_and_risk_input() -> None:
    baseline = NewYorkMorningMomentumBacktestRequest().model_dump(mode="json")
    baseline["strategy"] = "new_york_morning_momentum"
    untouched = {**baseline, "test_segment": "untouched"}

    assert new_york_momentum_settings_match(baseline, untouched)
    assert not new_york_momentum_settings_match(baseline, {**untouched, "risk_percent": 0.50})
    assert not new_york_momentum_settings_match(baseline, {**untouched, "entry_hour": 10})
    assert not new_york_momentum_settings_match(baseline, {**untouched, "spread_price": 0.10})


def test_predeclared_gate_requires_500_trades_three_years_pf_and_drawdown() -> None:
    passing = _daily_momentum_verdict(
        net_profit=1_000.0,
        profit_factor=1.21,
        expectancy=2.0,
        max_drawdown_percent=14.9,
        total_trades=500,
        yearly_net={"2022": 100, "2023": 200, "2024": 300},
        test_segment="development",
    )
    failing = _daily_momentum_verdict(
        net_profit=1_000.0,
        profit_factor=1.19,
        expectancy=2.0,
        max_drawdown_percent=14.9,
        total_trades=500,
        yearly_net={"2022": 100, "2023": 200, "2024": 300},
        test_segment="development",
    )

    assert passing["code"] == "promising"
    assert failing["code"] == "failed"


class FakeMomentumRepository:
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
async def test_service_persists_one_daily_trade_and_verdict() -> None:
    source: list[Candle] = []
    for index in range(30):
        source.append(
            minute(
                WINTER_SIGNAL_START + timedelta(minutes=index),
                100.0,
                110.0 if index == 0 else 106.0,
                95.0 if index == 0 else 99.0,
                105.0 if index == 29 else 100.0,
            )
        )
    source.append(minute(WINTER_SIGNAL_START + timedelta(minutes=30), 105.0, 106.0, 104.0, 105.5))
    source.append(minute(datetime(2026, 1, 5, 20, 55, tzinfo=timezone.utc), 107.0, 108.0, 106.0, 107.5))
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
    repo = FakeMomentumRepository(rows)
    service = BacktestService(repo)  # type: ignore[arg-type]
    request = {
        **NewYorkMorningMomentumBacktestRequest(test_segment="development").model_dump(mode="json"),
        "strategy": "new_york_morning_momentum",
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
    }

    await service._run_new_york_momentum("run-1", request)

    assert repo.run["status"] == "complete"
    assert repo.run["net_profit"] == pytest.approx(4.0)
    assert repo.run["total_positions"] == 1
    assert repo.run["total_baskets"] == 1
    assert repo.run["reliability"]["strategy"] == "new_york_morning_momentum"
    assert repo.run["reliability"]["maximum_trades_per_day"] == 1
    assert len(repo.trades) == 1
    assert repo.trades[0]["metadata"]["strategy"] == "new_york_morning_momentum"
    assert len(repo.baskets) == 1
