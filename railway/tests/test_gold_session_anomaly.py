from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.fixed_ladder_v261 import Candle
from app.backtesting.gold_session_anomaly import (
    GoldSessionAnomalyBacktester,
    GoldSessionAnomalyParameters,
)
from app.models.schemas import GoldSessionAnomalyBacktestRequest
from app.services.backtests import (
    BacktestService,
    _abnormal_momentum_verdict,
    _daily_momentum_verdict,
    gold_session_anomaly_settings_match,
)


WINTER_SETTLEMENT = datetime(2026, 1, 5, 18, 30, tzinfo=timezone.utc)
WINTER_NEXT_OPEN = datetime(2026, 1, 6, 13, 20, tzinfo=timezone.utc)


def parameters(session_leg: str = "overnight_long", **overrides) -> GoldSessionAnomalyParameters:
    values = {
        "session_leg": session_leg,
        "fixed_lot": 0.01,
        "maximum_loss_percent": 0.25,
        "long_overnight_cost_per_001_lot": 0.0,
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "slippage_price": 0.0,
        "money_per_price_per_001_lot": 1.0,
        "path_mode": "candle_direction",
    }
    values.update(overrides)
    return GoldSessionAnomalyParameters(**values)


def minute(at: datetime, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(candle_time=at, open=open_, high=high, low=low, close=close)


def test_overnight_long_opens_at_1330_and_exits_next_0820_new_york() -> None:
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters())
    simulator.process_candle(minute(WINTER_SETTLEMENT, 100.0, 101.0, 99.0, 100.0))

    assert simulator.position is not None
    assert simulator.position.side == "buy"
    assert simulator.position.opened_at == WINTER_SETTLEMENT
    assert simulator.position.lot_size == 0.01
    assert simulator.position.planned_risk_money == pytest.approx(25.0)

    simulator.process_candle(minute(WINTER_NEXT_OPEN, 105.0, 110.0, 70.0, 80.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].closed_at == WINTER_NEXT_OPEN
    assert trades[0].exit_reason == "FROZEN SESSION EXIT"
    assert trades[0].net_pnl == pytest.approx(5.0)


def test_summer_dst_moves_both_boundaries_one_hour_earlier_utc() -> None:
    entry = datetime(2026, 6, 8, 17, 30, tzinfo=timezone.utc)
    exit_ = datetime(2026, 6, 9, 12, 20, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters())
    simulator.process_candle(minute(entry, 100.0, 101.0, 99.0, 100.0))
    assert simulator.position is not None

    simulator.process_candle(minute(exit_, 101.0, 102.0, 100.0, 101.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].opened_at == entry
    assert trades[0].closed_at == exit_


def test_friday_overnight_trade_waits_until_monday_open() -> None:
    friday_entry = datetime(2026, 1, 9, 18, 30, tzinfo=timezone.utc)
    sunday_bar = datetime(2026, 1, 11, 23, 0, tzinfo=timezone.utc)
    monday_exit = datetime(2026, 1, 12, 13, 20, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters())
    simulator.process_candle(minute(friday_entry, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(minute(sunday_bar, 102.0, 103.0, 101.0, 102.0))

    assert simulator.position is not None

    simulator.process_candle(minute(monday_exit, 103.0, 104.0, 102.0, 103.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].closed_at == monday_exit
    assert trades[0].net_pnl == pytest.approx(3.0)


def test_overnight_financing_is_charged_at_1700_and_wednesday_is_triple() -> None:
    wednesday_entry = datetime(2026, 1, 7, 18, 30, tzinfo=timezone.utc)
    wednesday_rollover = datetime(2026, 1, 7, 22, 0, tzinfo=timezone.utc)
    thursday_exit = datetime(2026, 1, 8, 13, 20, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(
        10_000.0,
        parameters(long_overnight_cost_per_001_lot=0.70),
    )
    simulator.process_candle(minute(wednesday_entry, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(minute(wednesday_rollover, 100.0, 101.0, 99.0, 100.0))

    assert simulator.position is not None
    assert simulator.position.financing_costs == pytest.approx(2.10)
    assert simulator.summary().financing_events == 1

    simulator.process_candle(minute(thursday_exit, 105.0, 106.0, 104.0, 105.0))
    trades, _ = simulator.finalise()

    assert trades[0].financing_costs == pytest.approx(2.10)
    assert trades[0].net_pnl == pytest.approx(2.90)


def test_hard_stop_caps_total_loss_after_spread_commission_and_financing() -> None:
    rollover = datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(
        10_000.0,
        parameters(
            long_overnight_cost_per_001_lot=0.70,
            spread_price=0.05,
            commission_per_001_lot=0.08,
        ),
    )
    simulator.process_candle(minute(WINTER_SETTLEMENT, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(minute(rollover, 100.0, 101.0, 99.0, 100.0))
    assert simulator.position is not None
    stop = simulator.position.stop_mid
    simulator.process_candle(minute(rollover + timedelta(minutes=1), 100.0, 100.0, stop - 1.0, stop - 1.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].exit_reason == "HARD MONEY STOP"
    assert trades[0].net_pnl == pytest.approx(-25.0)


def test_strategy_cannot_reenter_after_same_day_stop() -> None:
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters())
    simulator.process_candle(minute(WINTER_SETTLEMENT, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(minute(WINTER_SETTLEMENT + timedelta(minutes=1), 100.0, 101.0, 70.0, 70.0))
    assert simulator.position is None

    simulator.process_candle(minute(WINTER_SETTLEMENT + timedelta(minutes=2), 100.0, 110.0, 90.0, 100.0))

    assert simulator.position is None
    assert simulator.summary().sessions_traded == 1
    assert simulator.summary().total_baskets == 1


def test_missing_exact_entry_minute_skips_instead_of_entering_late() -> None:
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters())
    simulator.process_candle(minute(WINTER_SETTLEMENT + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.0))

    assert simulator.position is None
    assert simulator.summary().missing_entry_skips == 1
    assert simulator.summary().sessions_traded == 0


def test_test_boundary_discards_an_incomplete_session_instead_of_inventing_an_exit() -> None:
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters())
    simulator.process_candle(minute(WINTER_SETTLEMENT, 100.0, 101.0, 99.0, 100.0))
    trades, baskets = simulator.finalise()

    assert trades == []
    assert baskets == []
    assert simulator.summary().total_baskets == 0
    assert simulator.summary().incomplete_end_discards == 1


def test_day_short_opens_at_0820_and_exits_at_1330_same_day() -> None:
    entry = datetime(2026, 1, 5, 13, 20, tzinfo=timezone.utc)
    exit_ = datetime(2026, 1, 5, 18, 30, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters("day_short"))
    simulator.process_candle(minute(entry, 100.0, 101.0, 99.0, 100.0))

    assert simulator.position is not None
    assert simulator.position.side == "sell"

    simulator.process_candle(minute(exit_, 95.0, 110.0, 90.0, 105.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].exit_reason == "FROZEN SESSION EXIT"
    assert trades[0].net_pnl == pytest.approx(5.0)
    assert trades[0].financing_costs == 0.0


def test_asia_long_opens_sunday_1800_new_york_and_exits_monday_1530_shanghai() -> None:
    entry = datetime(2026, 1, 4, 23, 0, tzinfo=timezone.utc)
    exit_ = datetime(2026, 1, 5, 7, 30, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(
        10_000.0,
        parameters("asia_long", long_overnight_cost_per_001_lot=0.70),
    )
    simulator.process_candle(minute(entry, 100.0, 101.0, 99.0, 100.0))

    assert simulator.position is not None
    assert simulator.position.side == "buy"
    assert simulator.position.signal.trade_date == "2026-01-05"

    simulator.process_candle(minute(exit_, 105.0, 110.0, 70.0, 80.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].closed_at == exit_
    assert trades[0].net_pnl == pytest.approx(5.0)
    assert trades[0].financing_costs == 0.0


def test_asia_long_uses_new_york_dst_for_entry_and_fixed_shanghai_exit() -> None:
    entry = datetime(2026, 6, 7, 22, 0, tzinfo=timezone.utc)
    exit_ = datetime(2026, 6, 8, 7, 30, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters("asia_long"))
    simulator.process_candle(minute(entry, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(minute(exit_, 102.0, 103.0, 101.0, 102.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].opened_at == entry
    assert trades[0].closed_at == exit_


def test_asia_long_never_enters_on_friday_evening() -> None:
    friday_1800_new_york = datetime(2026, 1, 9, 23, 0, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters("asia_long"))
    simulator.process_candle(minute(friday_1800_new_york, 100.0, 101.0, 99.0, 100.0))

    assert simulator.position is None
    assert simulator.summary().sessions_traded == 0


def test_asia_long_produces_at_most_five_complete_trades_in_a_week() -> None:
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters("asia_long"))
    first_entry = datetime(2026, 1, 4, 23, 0, tzinfo=timezone.utc)
    for offset in range(5):
        entry = first_entry + timedelta(days=offset)
        exit_ = datetime(2026, 1, 5 + offset, 7, 30, tzinfo=timezone.utc)
        simulator.process_candle(minute(entry, 100.0, 101.0, 99.0, 100.0))
        simulator.process_candle(minute(exit_, 101.0, 102.0, 100.0, 101.0))
    simulator.process_candle(
        minute(datetime(2026, 1, 9, 23, 0, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.0)
    )
    trades, _ = simulator.finalise()

    assert len(trades) == 5
    assert simulator.summary().sessions_traded == 5


def test_asia_exit_missing_exact_bar_uses_last_available_pre_exit_price() -> None:
    entry = datetime(2026, 1, 4, 23, 0, tzinfo=timezone.utc)
    last_before_exit = datetime(2026, 1, 5, 7, 29, tzinfo=timezone.utc)
    first_after_exit = datetime(2026, 1, 5, 7, 31, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters("asia_long"))
    simulator.process_candle(minute(entry, 100.0, 101.0, 99.0, 100.0))
    simulator.process_candle(minute(last_before_exit, 102.0, 103.0, 101.0, 102.5))
    simulator.process_candle(minute(first_after_exit, 110.0, 111.0, 109.0, 110.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].closed_at == last_before_exit
    assert trades[0].exit_price == pytest.approx(102.5)
    assert trades[0].exit_reason == "LAST AVAILABLE PRE-EXIT BAR"
    assert simulator.summary().missing_exit_fallbacks == 1


def test_shanghai_day_long_trades_the_exact_official_day_session() -> None:
    entry = datetime(2026, 1, 5, 1, 0, tzinfo=timezone.utc)
    exit_ = datetime(2026, 1, 5, 7, 30, tzinfo=timezone.utc)
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters("shanghai_day_long"))
    simulator.process_candle(minute(entry, 100.0, 101.0, 99.0, 100.0))

    assert simulator.position is not None
    assert simulator.position.side == "buy"
    assert simulator.position.signal.trade_date == "2026-01-05"

    simulator.process_candle(minute(exit_, 104.0, 110.0, 70.0, 80.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].opened_at == entry
    assert trades[0].closed_at == exit_
    assert trades[0].net_pnl == pytest.approx(4.0)
    assert trades[0].financing_costs == 0.0


def new_york_time(day: int, hour: int, minute_: int = 0) -> datetime:
    # January is UTC-5 in America/New_York.
    return datetime(2026, 1, day, hour + 5, minute_, tzinfo=timezone.utc)


def test_intraday_close_momentum_follows_fifth_half_hour_and_exits_at_1600() -> None:
    simulator = GoldSessionAnomalyBacktester(
        10_000.0,
        parameters("gld_fifth_half_hour_momentum"),
    )
    simulator.process_candle(minute(new_york_time(5, 11, 30), 100.0, 101.0, 99.0, 100.5))
    simulator.process_candle(minute(new_york_time(5, 12, 0), 102.0, 103.0, 101.0, 102.0))
    simulator.process_candle(minute(new_york_time(5, 15, 30), 105.0, 106.0, 104.0, 105.0))

    assert simulator.position is not None
    assert simulator.position.side == "buy"
    assert simulator.position.signal.predictor_start_price == 100.0
    assert simulator.position.signal.predictor_end_price == 102.0

    simulator.process_candle(minute(new_york_time(5, 16, 0), 107.0, 108.0, 90.0, 90.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].net_pnl == pytest.approx(2.0)
    assert trades[0].closed_at == new_york_time(5, 16, 0)
    assert trades[0].exit_reason == "FROZEN SESSION EXIT"
    assert trades[0].strategy_code == "gold_intraday_close_momentum"


def test_intraday_close_momentum_sells_nonpositive_predictor_and_trades_once() -> None:
    simulator = GoldSessionAnomalyBacktester(
        10_000.0,
        parameters("gld_fifth_half_hour_momentum"),
    )
    simulator.process_candle(minute(new_york_time(5, 11, 30), 100.0, 100.0, 100.0, 100.0))
    simulator.process_candle(minute(new_york_time(5, 12, 0), 100.0, 100.0, 100.0, 100.0))
    simulator.process_candle(minute(new_york_time(5, 15, 30), 100.0, 100.0, 100.0, 100.0))

    assert simulator.position is not None
    assert simulator.position.side == "sell"

    simulator.process_candle(minute(new_york_time(5, 16, 0), 99.0, 99.0, 99.0, 99.0))
    simulator.process_candle(minute(new_york_time(5, 16, 1), 98.0, 98.0, 98.0, 98.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert simulator.summary().sessions_traded == 1


def test_intraday_close_momentum_skips_an_incomplete_predictor_day() -> None:
    simulator = GoldSessionAnomalyBacktester(
        10_000.0,
        parameters("gld_fifth_half_hour_momentum"),
    )
    simulator.process_candle(minute(new_york_time(5, 12, 0), 102.0, 103.0, 101.0, 102.0))
    simulator.process_candle(minute(new_york_time(5, 15, 30), 105.0, 106.0, 104.0, 105.0))

    assert simulator.position is None
    assert simulator.summary().missing_entry_skips == 1
    assert simulator.summary().sessions_traded == 0


def test_intraday_close_momentum_trades_all_five_complete_weekdays() -> None:
    simulator = GoldSessionAnomalyBacktester(
        10_000.0,
        parameters("gld_fifth_half_hour_momentum"),
    )
    for day in range(5, 10):
        simulator.process_candle(minute(new_york_time(day, 11, 30), 100.0, 100.0, 100.0, 100.0))
        simulator.process_candle(minute(new_york_time(day, 12, 0), 101.0, 101.0, 101.0, 101.0))
        simulator.process_candle(minute(new_york_time(day, 15, 30), 102.0, 102.0, 102.0, 102.0))
        simulator.process_candle(minute(new_york_time(day, 16, 0), 103.0, 103.0, 103.0, 103.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 5
    assert simulator.summary().sessions_traded == 5


def test_intraday_close_momentum_uses_the_predeclared_daily_gate() -> None:
    verdict = _daily_momentum_verdict(
        net_profit=100.0,
        profit_factor=1.20,
        expectancy=0.10,
        max_drawdown_percent=15.0,
        total_trades=500,
        yearly_net={"2021": 1.0, "2022": 1.0, "2023": 1.0},
        test_segment="development",
    )
    assert verdict["code"] == "promising"


def abnormal_time(day: int, hour: int, minute_: int = 0) -> datetime:
    # The published study uses a fixed GMT+3 clock.
    gmt_plus_three = timezone(timedelta(hours=3))
    return datetime(2026, 1, day, hour, minute_, tzinfo=gmt_plus_three).astimezone(timezone.utc)


def seeded_abnormal_simulator() -> GoldSessionAnomalyBacktester:
    simulator = GoldSessionAnomalyBacktester(10_000.0, parameters("abnormal_momentum"))
    simulator._abnormal_daily_returns = [0.10 if index % 2 else -0.10 for index in range(60)]
    return simulator


def test_abnormal_momentum_shorts_two_sigma_negative_move_and_exits_at_day_end() -> None:
    simulator = seeded_abnormal_simulator()
    simulator.process_candle(minute(abnormal_time(5, 0), 100.0, 100.0, 100.0, 100.0))
    simulator.process_candle(minute(abnormal_time(5, 17), 97.0, 97.0, 97.0, 97.0))

    assert simulator.position is not None
    assert simulator.position.side == "sell"
    assert simulator.position.signal.observed_return_percent == pytest.approx(-3.0)
    assert simulator.position.signal.baseline_std_percent is not None

    simulator.process_candle(minute(abnormal_time(5, 23, 59), 96.0, 96.0, 96.0, 96.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].net_pnl == pytest.approx(1.0)
    assert trades[0].exit_reason == "FROZEN GMT+3 DAY-END EXIT"
    assert trades[0].strategy_code == "gold_abnormal_momentum"


def test_abnormal_momentum_waits_until_1900_for_positive_two_sigma_move() -> None:
    simulator = seeded_abnormal_simulator()
    simulator.process_candle(minute(abnormal_time(5, 0), 100.0, 100.0, 100.0, 100.0))
    simulator.process_candle(minute(abnormal_time(5, 17), 100.0, 100.0, 100.0, 100.0))
    assert simulator.position is None

    simulator.process_candle(minute(abnormal_time(5, 19), 103.0, 103.0, 103.0, 103.0))
    assert simulator.position is not None
    assert simulator.position.side == "buy"

    simulator.process_candle(minute(abnormal_time(5, 23, 59), 104.0, 104.0, 104.0, 104.0))
    trades, _ = simulator.finalise()

    assert len(trades) == 1
    assert trades[0].net_pnl == pytest.approx(1.0)
    assert simulator.summary().abnormal_positive_signals == 1
    assert simulator.summary().abnormal_negative_signals == 0


def test_abnormal_momentum_requires_sixty_prior_days_and_skips_missing_day_open() -> None:
    warmup = GoldSessionAnomalyBacktester(10_000.0, parameters("abnormal_momentum"))
    warmup._abnormal_daily_returns = [0.0] * 59
    warmup.process_candle(minute(abnormal_time(5, 0), 100.0, 100.0, 100.0, 100.0))
    warmup.process_candle(minute(abnormal_time(5, 17), 90.0, 90.0, 90.0, 90.0))
    assert warmup.position is None
    assert warmup.summary().abnormal_warmup_skips == 1

    missing_open = seeded_abnormal_simulator()
    missing_open.process_candle(minute(abnormal_time(5, 3), 100.0, 100.0, 100.0, 100.0))
    missing_open.process_candle(minute(abnormal_time(5, 17), 90.0, 90.0, 90.0, 90.0))
    assert missing_open.position is None
    assert missing_open.summary().abnormal_missing_open_skips == 1


def test_abnormal_warmup_reset_preserves_baseline_but_skips_split_day() -> None:
    simulator = seeded_abnormal_simulator()
    simulator.process_candle(
        minute(abnormal_time(5, 0), 100.0, 100.0, 100.0, 100.0),
        allow_entry=False,
        count_metrics=False,
    )
    simulator.begin_evaluation()
    simulator.process_candle(minute(abnormal_time(5, 19), 110.0, 110.0, 110.0, 110.0))

    assert simulator.position is None
    assert simulator.summary().candles_processed == 1
    assert len(simulator._abnormal_daily_returns) == 60


def test_abnormal_momentum_uses_the_predeclared_development_and_untouched_gates() -> None:
    development = _abnormal_momentum_verdict(
        net_profit=100.0,
        profit_factor=1.35,
        expectancy=1.0,
        max_drawdown_percent=5.0,
        total_trades=30,
        yearly_net={"2021": 1.0, "2022": 1.0, "2023": 1.0},
        test_segment="development",
    )
    assert development["code"] == "promising"

    insufficient = _abnormal_momentum_verdict(
        net_profit=100.0,
        profit_factor=2.0,
        expectancy=1.0,
        max_drawdown_percent=1.0,
        total_trades=29,
        yearly_net={"2021": 1.0, "2022": 1.0, "2023": 1.0},
        test_segment="development",
    )
    assert insufficient["code"] == "failed"

    untouched = _abnormal_momentum_verdict(
        net_profit=50.0,
        profit_factor=1.20,
        expectancy=0.5,
        max_drawdown_percent=5.0,
        total_trades=15,
        yearly_net={"2024": 1.0, "2025": 1.0},
        test_segment="untouched",
        locked_development_run_id="development-run",
    )
    assert untouched["code"] == "untouched_pass"


def test_request_and_untouched_lock_cover_both_predeclared_session_legs() -> None:
    request = GoldSessionAnomalyBacktestRequest()

    assert request.session_leg == "overnight_long"
    assert request.fixed_lot == 0.01
    assert request.maximum_loss_percent == 0.25
    assert (request.day_open_hour, request.day_open_minute) == (8, 20)
    assert (request.settlement_hour, request.settlement_minute) == (13, 30)
    assert request.long_overnight_cost_per_001_lot == 0.70
    assert (request.asia_entry_hour, request.asia_entry_minute) == (18, 0)
    assert request.asia_exit_timezone_name == "Asia/Shanghai"
    assert (request.shanghai_entry_hour, request.shanghai_entry_minute) == (9, 0)
    assert (request.asia_exit_hour, request.asia_exit_minute) == (15, 30)
    assert request.abnormal_timezone_name == "Etc/GMT-3"
    assert request.abnormal_lookback_days == 60
    assert request.abnormal_sigma == 2.0
    assert (request.abnormal_negative_entry_hour, request.abnormal_negative_entry_minute) == (17, 0)
    assert (request.abnormal_positive_entry_hour, request.abnormal_positive_entry_minute) == (19, 0)
    assert (request.abnormal_exit_hour, request.abnormal_exit_minute) == (23, 59)
    assert (request.intraday_predictor_start_hour, request.intraday_predictor_start_minute) == (11, 30)
    assert (request.intraday_predictor_end_hour, request.intraday_predictor_end_minute) == (12, 0)
    assert (request.intraday_entry_hour, request.intraday_entry_minute) == (15, 30)
    assert (request.intraday_exit_hour, request.intraday_exit_minute) == (16, 0)

    baseline = request.model_dump(mode="json")
    baseline["strategy"] = "gold_overnight_long"
    untouched = {**baseline, "test_segment": "untouched"}
    assert gold_session_anomaly_settings_match(baseline, untouched)
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "session_leg": "day_short"})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "long_overnight_cost_per_001_lot": 0.0})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "settlement_minute": 29})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "asia_entry_hour": 17})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "asia_exit_minute": 0})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "shanghai_entry_hour": 8})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "abnormal_lookback_days": 59})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "abnormal_sigma": 1.5})
    assert not gold_session_anomaly_settings_match(baseline, {**untouched, "intraday_entry_minute": 29})


class FakeGoldSessionRepository:
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
        after = kwargs.get("after")
        date_from = kwargs.get("date_from")
        date_to = kwargs.get("date_to")
        limit = int(kwargs.get("limit", 1000))
        selected = self.rows
        if after:
            selected = [row for row in selected if row["candle_time"] > after]
        if date_from:
            selected = [row for row in selected if row["candle_time"] >= date_from]
        if date_to:
            selected = [row for row in selected if row["candle_time"] <= date_to]
        return selected[:limit]

    async def bulk_insert_backtest_trades(self, rows: list[dict]) -> None:
        self.trades.extend(rows)

    async def bulk_insert_backtest_baskets(self, rows: list[dict]) -> None:
        self.baskets.extend(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_leg", "source", "expected_code"),
    [
        (
            "overnight_long",
            [
                minute(WINTER_SETTLEMENT, 100.0, 101.0, 99.0, 100.0),
                minute(WINTER_NEXT_OPEN, 105.0, 106.0, 104.0, 105.0),
            ],
            "gold_overnight_long",
        ),
        (
            "day_short",
            [
                minute(datetime(2026, 1, 5, 13, 20, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.0),
                minute(datetime(2026, 1, 5, 18, 30, tzinfo=timezone.utc), 95.0, 96.0, 94.0, 95.0),
            ],
            "comex_day_short",
        ),
        (
            "asia_long",
            [
                minute(datetime(2026, 1, 4, 23, 0, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.0),
                minute(datetime(2026, 1, 5, 7, 30, tzinfo=timezone.utc), 105.0, 106.0, 104.0, 105.0),
            ],
            "asia_session_long",
        ),
        (
            "shanghai_day_long",
            [
                minute(datetime(2026, 1, 5, 1, 0, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.0),
                minute(datetime(2026, 1, 5, 7, 30, tzinfo=timezone.utc), 105.0, 106.0, 104.0, 105.0),
            ],
            "shanghai_day_long",
        ),
        (
            "gld_fifth_half_hour_momentum",
            [
                minute(new_york_time(5, 11, 30), 100.0, 100.0, 100.0, 100.0),
                minute(new_york_time(5, 12, 0), 102.0, 102.0, 102.0, 102.0),
                minute(new_york_time(5, 15, 30), 105.0, 105.0, 105.0, 105.0),
                minute(new_york_time(5, 16, 0), 110.0, 110.0, 110.0, 110.0),
            ],
            "gold_intraday_close_momentum",
        ),
    ],
)
async def test_service_persists_each_daily_session_hypothesis(
    session_leg: str,
    source: list[Candle],
    expected_code: str,
) -> None:
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
    repo = FakeGoldSessionRepository(rows)
    service = BacktestService(repo)  # type: ignore[arg-type]
    request = {
        **GoldSessionAnomalyBacktestRequest(
            session_leg=session_leg,
            test_segment="development",
        ).model_dump(mode="json"),
        "strategy": expected_code,
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "long_overnight_cost_per_001_lot": 0.0,
    }

    await service._run_gold_session_anomaly("run-1", request)

    assert repo.run["status"] == "complete"
    assert repo.run["net_profit"] == pytest.approx(5.0)
    assert repo.run["total_positions"] == 1
    assert repo.run["total_baskets"] == 1
    assert repo.run["reliability"]["strategy"] == expected_code
    assert repo.run["reliability"]["maximum_trades_per_day"] == 1
    assert len(repo.trades) == 1
    assert repo.trades[0]["metadata"]["strategy"] == expected_code
    assert len(repo.baskets) == 1


@pytest.mark.asyncio
async def test_service_runs_abnormal_momentum_with_a_causal_daily_baseline() -> None:
    source: list[Candle] = []
    local_day = datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=3)))
    completed = 0
    while completed < 61:
        if local_day.weekday() < 5:
            base = 100.0
            final = base + (0.10 if completed % 2 else -0.10)
            source.extend(
                [
                    minute(local_day.astimezone(timezone.utc), base, base, base, base),
                    minute((local_day + timedelta(hours=17)).astimezone(timezone.utc), base, base, base, base),
                    minute((local_day + timedelta(hours=19)).astimezone(timezone.utc), base, base, base, base),
                    minute((local_day + timedelta(hours=23, minutes=59)).astimezone(timezone.utc), final, final, final, final),
                ]
            )
            completed += 1
        local_day += timedelta(days=1)

    trade_day = local_day
    while trade_day.weekday() >= 5:
        trade_day += timedelta(days=1)
    source.extend(
        [
            minute(trade_day.astimezone(timezone.utc), 100.0, 100.0, 100.0, 100.0),
            minute((trade_day + timedelta(hours=17)).astimezone(timezone.utc), 97.0, 97.0, 97.0, 97.0),
            minute((trade_day + timedelta(hours=23, minutes=59)).astimezone(timezone.utc), 96.0, 96.0, 96.0, 96.0),
        ]
    )
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
    repo = FakeGoldSessionRepository(rows)
    service = BacktestService(repo)  # type: ignore[arg-type]
    request = {
        **GoldSessionAnomalyBacktestRequest(
            session_leg="abnormal_momentum",
            test_segment="development",
        ).model_dump(mode="json"),
        "strategy": "gold_abnormal_momentum",
        "spread_price": 0.0,
        "commission_per_001_lot": 0.0,
        "long_overnight_cost_per_001_lot": 0.0,
    }

    await service._run_gold_session_anomaly("run-1", request)

    assert repo.run["status"] == "complete"
    assert repo.run["net_profit"] == pytest.approx(1.0)
    assert repo.run["total_baskets"] == 1
    assert repo.run["reliability"]["strategy"] == "gold_abnormal_momentum"
    assert repo.run["reliability"]["abnormal_negative_signals"] == 1
    assert repo.trades[0]["metadata"]["baseline_days"] == 60
