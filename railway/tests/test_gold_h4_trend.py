from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.fixed_ladder_v261 import Candle
from app.backtesting.gold_h4_trend import (
    GoldH4TrendBacktester,
    GoldH4TrendParameters,
    TrendBarEvent,
    build_trend_events,
)
from app.models.schemas import GoldH4TrendBacktestRequest
from app.services.backtests import BacktestService, gold_h4_settings_match


UTC = timezone.utc


def candle(at: datetime, open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(candle_time=at, open=open_price, high=high, low=low, close=close)


def signal_event(
    at: datetime,
    *,
    side: str | None = "buy",
    close: float = 102.0,
    exit_high: float = 105.0,
    exit_low: float = 95.0,
) -> TrendBarEvent:
    return TrendBarEvent(
        event_time=at,
        h4_bar_time=at - timedelta(hours=4),
        h4_close=close,
        raw_breakout_side=side,  # type: ignore[arg-type]
        entry_side=side,  # type: ignore[arg-type]
        atr_h4=2.0,
        entry_channel_high=101.0,
        entry_channel_low=90.0,
        exit_channel_high=exit_high,
        exit_channel_low=exit_low,
        daily_close=120.0,
        daily_reference_close=100.0,
    )


def trend_history() -> tuple[list[Candle], list[Candle], datetime]:
    h4_start = datetime(2026, 3, 1, tzinfo=UTC)
    h4 = [candle(h4_start + timedelta(hours=4 * index), 100.0, 101.0, 99.0, 100.0) for index in range(55)]
    h4.append(candle(h4_start + timedelta(hours=4 * 55), 100.0, 103.0, 99.5, 102.0))
    event_time = h4[-1].candle_time + timedelta(hours=4)

    daily_start = datetime(2025, 11, 1, tzinfo=UTC)
    daily = [
        candle(daily_start + timedelta(days=index), 100.0 + index, 101.0 + index, 99.0 + index, 100.0 + index)
        for index in range(150)
    ]
    return h4, daily, event_time


def zero_cost_parameters(**overrides) -> GoldH4TrendParameters:
    values = {
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "slippage_price": 0.0,
        "overnight_long_cost_per_001_lot": 0.0,
        "overnight_short_cost_per_001_lot": 0.0,
    }
    values.update(overrides)
    return GoldH4TrendParameters(**values)


def test_completed_h4_breakout_requires_matching_60_day_direction() -> None:
    h4, daily, event_time = trend_history()

    events = build_trend_events(h4, daily, zero_cost_parameters())

    assert len(events) == 1
    assert events[0].event_time == event_time
    assert events[0].raw_breakout_side == "buy"
    assert events[0].entry_side == "buy"
    assert events[0].daily_close is not None
    assert events[0].daily_reference_close is not None
    assert events[0].daily_close > events[0].daily_reference_close

    falling_daily = [
        candle(item.candle_time, 300.0 - index, 301.0 - index, 299.0 - index, 300.0 - index)
        for index, item in enumerate(daily)
    ]
    rejected = build_trend_events(h4, falling_daily, zero_cost_parameters())
    assert rejected[0].raw_breakout_side == "buy"
    assert rejected[0].entry_side is None


def test_risk_sizing_rounds_down_and_hard_stop_is_replayed_on_m1() -> None:
    at = datetime(2026, 3, 10, 12, tzinfo=UTC)
    simulator = GoldH4TrendBacktester(10_000.0, zero_cost_parameters(), [signal_event(at)])

    simulator.process_candle(candle(at, 100.0, 101.0, 95.0, 96.0))

    summary = simulator.summary()
    assert summary.total_positions == 1
    assert summary.ending_balance == pytest.approx(9_976.0)
    assert summary.exit_reasons == {"2 ATR STOP": 1}
    assert summary.basket_pnls == pytest.approx([-24.0])


def test_completed_h4_channel_exit_closes_at_next_m1_open() -> None:
    at = datetime(2026, 3, 10, 12, tzinfo=UTC)
    exit_event = signal_event(at + timedelta(hours=4), side=None, close=94.0, exit_low=95.0)
    simulator = GoldH4TrendBacktester(10_000.0, zero_cost_parameters(), [signal_event(at), exit_event])

    simulator.process_candle(candle(at, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(candle(at + timedelta(hours=4), 110.0, 111.0, 109.0, 110.0))

    summary = simulator.summary()
    assert summary.total_positions == 1
    assert summary.ending_balance == pytest.approx(10_060.0)
    assert summary.channel_exits == 1
    assert summary.exit_reasons == {"20-H4 CHANNEL EXIT": 1}


def test_wednesday_overnight_financing_is_charged_three_times() -> None:
    wednesday = datetime(2026, 3, 11, 12, tzinfo=UTC)
    params = zero_cost_parameters(overnight_long_cost_per_001_lot=0.70)
    simulator = GoldH4TrendBacktester(10_000.0, params, [signal_event(wednesday)])

    simulator.process_candle(candle(wednesday, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(candle(wednesday + timedelta(days=1), 100.0, 101.0, 99.0, 100.0))
    simulator.finalise()

    summary = simulator.summary()
    assert summary.overnight_rollovers == 1
    assert summary.financing_costs == pytest.approx(12.60)
    assert summary.ending_balance == pytest.approx(9_987.40)
    assert summary.basket_pnls == pytest.approx([-12.60])


def test_request_defaults_and_untouched_lock_freeze_every_trend_input() -> None:
    request = GoldH4TrendBacktestRequest()
    assert request.starting_balance == 10_000.0
    assert request.entry_lookback_h4 == 55
    assert request.exit_lookback_h4 == 20
    assert request.daily_trend_lookback == 60
    assert request.atr_period_h4 == 20
    assert request.atr_multiplier == 2.0
    assert request.risk_percent == 0.25
    assert request.triple_swap_weekday == 2

    baseline = request.model_dump(mode="json")
    baseline["strategy"] = "gold_h4_trend"
    untouched = {**baseline, "test_segment": "untouched"}
    assert gold_h4_settings_match(baseline, untouched)
    assert not gold_h4_settings_match(baseline, {**untouched, "risk_percent": 0.50})
    assert not gold_h4_settings_match(baseline, {**untouched, "overnight_long_cost_per_001_lot": 0.0})
    assert not gold_h4_settings_match(baseline, {**untouched, "entry_lookback_h4": 45})


class FakeTrendRepository:
    def __init__(self, rows_by_interval: dict[str, list[dict]]) -> None:
        self.rows_by_interval = rows_by_interval
        self.run = {"id": "run-1", "status": "queued"}
        self.trades: list[dict] = []
        self.baskets: list[dict] = []
        self.events: list[tuple] = []

    async def update_backtest_run(self, run_id: str, **changes) -> None:
        assert run_id == "run-1"
        self.run.update(changes)

    async def log_event(self, *args) -> None:
        self.events.append(args)

    async def count_market_candles(self, symbol, interval, date_from, date_to) -> int:
        return len(self.rows_by_interval[interval])

    async def get_backtest_run(self, run_id: str) -> dict:
        return self.run

    async def fetch_candles_page(self, *args, **kwargs) -> list[dict]:
        return self.rows_by_interval[kwargs["interval"]]

    async def bulk_insert_backtest_trades(self, rows: list[dict]) -> None:
        self.trades.extend(rows)

    async def bulk_insert_backtest_baskets(self, rows: list[dict]) -> None:
        self.baskets.extend(rows)


def rows(candles: list[Candle]) -> list[dict]:
    return [
        {
            "candle_time": item.candle_time.isoformat(),
            "open": item.open,
            "high": item.high,
            "low": item.low,
            "close": item.close,
            "volume": 1,
        }
        for item in candles
    ]


@pytest.mark.asyncio
async def test_service_loads_h4_and_d1_then_persists_m1_replayed_trade() -> None:
    h4, daily, event_time = trend_history()
    m1 = [candle(event_time, 100.0, 101.0, 95.0, 96.0)]
    repo = FakeTrendRepository({"4h": rows(h4), "1day": rows(daily), "1min": rows(m1)})
    service = BacktestService(repo)  # type: ignore[arg-type]
    request = {
        **GoldH4TrendBacktestRequest(test_segment="development").model_dump(mode="json"),
        "strategy": "gold_h4_trend",
        "date_from": (event_time - timedelta(minutes=1)).isoformat(),
        "date_to": (event_time + timedelta(minutes=1)).isoformat(),
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "overnight_long_cost_per_001_lot": 0.0,
        "overnight_short_cost_per_001_lot": 0.0,
    }

    await service._run_gold_h4("run-1", request)

    assert repo.run["status"] == "complete"
    assert repo.run["net_profit"] == pytest.approx(-24.9)
    assert repo.run["total_positions"] == 1
    assert repo.run["reliability"]["strategy"] == "gold_h4_trend"
    assert repo.run["reliability"]["verdict"]["code"] == "insufficient_evidence"
    assert len(repo.trades) == 1
    assert repo.trades[0]["metadata"]["strategy"] == "gold_h4_trend"
    assert len(repo.baskets) == 1
