from datetime import datetime, timedelta, timezone

from app.backtesting.fixed_ladder_v261 import Candle, FixedLadderParameters, FixedLadderV261Backtester


def candle(index: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5 * index), o, h, l, c)


def test_first_bullet_quick_cut_closes_campaign() -> None:
    engine = FixedLadderV261Backtester(
        1000,
        FixedLadderParameters(path_mode="open_high_low_close", spread_price=0.05),
    )
    engine.process_candle(candle(0, 100.0, 103.2, 102.0, 102.0))
    engine.finalise()
    summary = engine.summary()
    assert summary.total_baskets >= 1
    assert any("FIRST BULLET QUICK CUT" in reason for reason in summary.exit_reasons)
    assert summary.ending_balance < 1000


def test_full_engine_produces_profit_factor_inputs() -> None:
    engine = FixedLadderV261Backtester(1000, FixedLadderParameters(spread_price=0.05))
    price = 100.0
    for index in range(200):
        direction = 1 if index % 4 in (0, 1) else -1
        close = price + direction * 4.0
        high = max(price, close) + 1.0
        low = min(price, close) - 1.0
        engine.process_candle(candle(index, price, high, low, close))
        price = close
    engine.finalise()
    summary = engine.summary()
    assert summary.candles_processed == 200
    assert summary.total_positions > 0
    assert summary.total_baskets > 0
    assert len(summary.position_pnls) == summary.total_positions


def test_break_even_protected_stop_is_recorded() -> None:
    params = FixedLadderParameters(
        spread_price=0.0,
        commission_per_001_lot=0.0,
        path_mode="open_high_low_close",
        profit_target_money=1000,
        peak_protection_activation_money=1000,
        emergency_loss_money=1000,
        emergency_loss_percent=0,
    )
    engine = FixedLadderV261Backtester(1000, params)
    # Buy at 103, reach 104.6 to arm BE, then reverse through 103.15.
    engine.process_candle(candle(0, 100.0, 104.6, 102.0, 102.0))
    engine.finalise()
    assert any("BE PROTECTED STOP" in reason for reason in engine.summary().exit_reasons)
