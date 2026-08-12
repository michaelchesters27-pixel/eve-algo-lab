from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.fixed_ladder_v261 import Candle
from app.backtesting.london_opening_range import (
    LondonOpeningRangeBacktester,
    LondonOpeningRangeParameters,
)
from app.models.schemas import LondonOpeningRangeBacktestRequest
from app.services.backtests import BacktestService, london_settings_match


WINTER_START = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def parameters(**overrides) -> LondonOpeningRangeParameters:
    values = {
        "breakout_buffer_fraction": 0.10,
        "reward_risk": 2.0,
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
    return LondonOpeningRangeParameters(**values)


def minute(at: datetime, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(candle_time=at, open=open_, high=high, low=low, close=close)


def seed_opening_range(simulator: LondonOpeningRangeBacktester, start: datetime = WINTER_START) -> None:
    for index in range(30):
        high = 110.0 if index == 0 else 109.0
        low = 100.0 if index == 0 else 101.0
        simulator.process_candle(minute(start + timedelta(minutes=index), 105.0, high, low, 105.0))


def seed_buy_signal(simulator: LondonOpeningRangeBacktester, start: datetime = WINTER_START) -> None:
    seed_opening_range(simulator, start)
    closes = [109.5, 110.0, 110.4, 110.9, 111.5]
    previous = 109.0
    for offset, close in enumerate(closes, start=30):
        simulator.process_candle(
            minute(start + timedelta(minutes=offset), previous, max(previous, close) + 0.2, 108.0, close)
        )
        previous = close


def open_buy(simulator: LondonOpeningRangeBacktester, start: datetime = WINTER_START) -> None:
    seed_buy_signal(simulator, start)
    simulator.process_candle(minute(start + timedelta(minutes=35), 111.5, 112.0, 111.0, 111.8))


def test_confirmed_m5_breakout_enters_only_at_next_m5_open() -> None:
    simulator = LondonOpeningRangeBacktester(10_000.0, parameters())
    seed_buy_signal(simulator)

    assert simulator.position is None
    assert simulator.summary().signals_detected == 0

    simulator.process_candle(minute(WINTER_START + timedelta(minutes=35), 111.5, 112.0, 111.0, 111.8))

    assert simulator.summary().signals_detected == 1
    assert simulator.position is not None
    assert simulator.position.side == "buy"
    assert simulator.position.opened_at == WINTER_START + timedelta(minutes=35)
    assert simulator.position.signal.signal_time == WINTER_START + timedelta(minutes=35)


def test_range_midpoint_risk_size_and_two_r_target_are_exact() -> None:
    simulator = LondonOpeningRangeBacktester(10_000.0, parameters())
    open_buy(simulator)

    position = simulator.position
    assert position is not None
    assert position.signal.range_high == 110.0
    assert position.signal.range_low == 100.0
    assert position.stop_mid == 105.0
    assert position.entry_price == 111.5
    assert position.lot_size == pytest.approx(0.03)
    assert position.planned_risk_money == pytest.approx(19.5)
    assert position.planned_reward_money == pytest.approx(39.0)
    assert position.target_mid == pytest.approx(124.5)


@pytest.mark.parametrize(
    ("high", "low", "expected_reason", "expected_net"),
    [
        (125.0, 111.0, "TAKE PROFIT 2R", 39.0),
        (112.0, 104.0, "STOP LOSS", -19.5),
    ],
)
def test_target_and_midpoint_stop_close_at_planned_money(
    high: float,
    low: float,
    expected_reason: str,
    expected_net: float,
) -> None:
    simulator = LondonOpeningRangeBacktester(10_000.0, parameters(path_mode="open_high_low_close"))
    open_buy(simulator)
    simulator.process_candle(minute(WINTER_START + timedelta(minutes=36), 111.8, high, low, 111.0))

    trades, baskets = simulator.finalise()

    assert len(trades) == 1
    assert len(baskets) == 1
    assert baskets[0].exit_reason == expected_reason
    assert baskets[0].net_pnl == pytest.approx(expected_net)


def test_only_one_signal_is_allowed_per_london_date() -> None:
    simulator = LondonOpeningRangeBacktester(10_000.0, parameters())
    open_buy(simulator)
    assert simulator.position is not None
    simulator._close_position(WINTER_START + timedelta(minutes=36), 124.5, "TAKE PROFIT 2R")

    for index in range(40, 50):
        simulator.process_candle(minute(WINTER_START + timedelta(minutes=index), 125.0, 126.0, 124.0, 125.5))

    assert simulator.position is None
    assert simulator.summary().signals_detected == 1
    assert simulator.summary().sessions_traded == 1


def test_open_trade_is_forced_closed_at_1600_london() -> None:
    simulator = LondonOpeningRangeBacktester(10_000.0, parameters())
    open_buy(simulator)
    simulator.process_candle(
        minute(WINTER_START.replace(hour=16), 112.0, 113.0, 111.0, 112.5)
    )

    _, baskets = simulator.finalise()

    assert len(baskets) == 1
    assert baskets[0].closed_at == WINTER_START.replace(hour=16)
    assert baskets[0].exit_reason == "SESSION FORCE EXIT"


def test_europe_london_dst_moves_the_0800_session_to_0700_utc() -> None:
    summer_start = datetime(2026, 6, 8, 7, 0, tzinfo=timezone.utc)
    simulator = LondonOpeningRangeBacktester(10_000.0, parameters())
    open_buy(simulator, summer_start)

    assert simulator.position is not None
    assert simulator.position.opened_at == datetime(2026, 6, 8, 7, 35, tzinfo=timezone.utc)
    assert simulator.position.signal.session_date == "2026-06-08"


def test_minimum_lot_skips_trade_when_quarter_percent_risk_cannot_be_honoured() -> None:
    simulator = LondonOpeningRangeBacktester(1_000.0, parameters())
    seed_buy_signal(simulator)
    simulator.process_candle(minute(WINTER_START + timedelta(minutes=35), 111.5, 112.0, 111.0, 111.8))

    assert simulator.position is None
    assert simulator.summary().risk_size_skips == 1
    assert simulator.summary().sessions_traded == 0


def test_incomplete_m5_range_cannot_create_a_signal() -> None:
    simulator = LondonOpeningRangeBacktester(10_000.0, parameters())
    for index in range(30):
        if index == 12:
            continue
        simulator.process_candle(minute(WINTER_START + timedelta(minutes=index), 105.0, 110.0, 100.0, 105.0))
    for index in range(30, 36):
        simulator.process_candle(minute(WINTER_START + timedelta(minutes=index), 110.0, 113.0, 109.0, 112.0))

    assert simulator.position is None
    assert simulator.summary().sessions_with_complete_range == 0
    assert simulator.summary().signals_detected == 0


def test_request_defaults_lock_the_london_v1_protocol() -> None:
    request = LondonOpeningRangeBacktestRequest()

    assert request.starting_balance == 10_000.0
    assert request.risk_percent == 0.25
    assert request.breakout_buffer_fraction == 0.10
    assert request.reward_risk == 2.0
    assert request.timezone_name == "Europe/London"
    assert (request.range_start_hour, request.range_start_minute, request.range_minutes) == (8, 0, 30)
    assert (request.entry_cutoff_hour, request.entry_cutoff_minute) == (11, 30)
    assert (request.force_exit_hour, request.force_exit_minute) == (16, 0)


def test_untouched_lock_includes_every_london_rule_cost_and_risk_input() -> None:
    baseline = LondonOpeningRangeBacktestRequest().model_dump(mode="json")
    baseline["strategy"] = "london_opening_range"
    untouched = {**baseline, "test_segment": "untouched"}

    assert london_settings_match(baseline, untouched)
    assert not london_settings_match(baseline, {**untouched, "risk_percent": 0.50})
    assert not london_settings_match(baseline, {**untouched, "spread_price": 0.10})
    assert not london_settings_match(baseline, {**untouched, "range_minutes": 60})


class FakeLondonRepository:
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
async def test_service_reconstructs_m5_and_persists_london_trade() -> None:
    source: list[Candle] = []
    for index in range(30):
        source.append(
            minute(
                WINTER_START + timedelta(minutes=index),
                105.0,
                110.0 if index == 0 else 109.0,
                100.0 if index == 0 else 101.0,
                105.0,
            )
        )
    closes = [109.5, 110.0, 110.4, 110.9, 111.5]
    previous = 109.0
    for offset, close in enumerate(closes, start=30):
        source.append(
            minute(
                WINTER_START + timedelta(minutes=offset),
                previous,
                max(previous, close) + 0.2,
                108.0,
                close,
            )
        )
        previous = close
    source.append(minute(WINTER_START + timedelta(minutes=35), 111.5, 112.0, 111.0, 111.8))
    source.append(minute(WINTER_START + timedelta(minutes=36), 111.8, 125.0, 111.0, 124.0))
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
    repo = FakeLondonRepository(rows)
    service = BacktestService(repo)  # type: ignore[arg-type]
    request = {
        **LondonOpeningRangeBacktestRequest(test_segment="development").model_dump(mode="json"),
        "strategy": "london_opening_range",
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
    }

    await service._run_london("run-1", request)

    assert repo.run["status"] == "complete"
    assert repo.run["net_profit"] == pytest.approx(39.0)
    assert repo.run["total_positions"] == 1
    assert repo.run["total_baskets"] == 1
    assert repo.run["reliability"]["strategy"] == "london_opening_range"
    assert repo.run["reliability"]["sessions_traded"] == 1
    assert repo.run["reliability"]["verdict"]["code"] == "insufficient_evidence"
    assert len(repo.trades) == 1
    assert repo.trades[0]["metadata"]["strategy"] == "london_opening_range"
    assert len(repo.baskets) == 1
