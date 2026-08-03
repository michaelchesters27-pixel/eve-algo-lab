from datetime import datetime, timedelta, timezone

from app.services.high_resolution_validation import (
    ReplayMetrics,
    TradeIntent,
    build_trade_intents,
    classify_validation,
    parameter_profiles,
    replay_one_intent,
    validation_key,
)


def snapshot(timestamp: datetime, *, direction: int = 1, atr: float = 2.0) -> dict:
    return {
        "candle_time": timestamp.isoformat(),
        "direction": direction,
        "alignment_score": direction,
        "atr_14": atr,
        "hour_utc": timestamp.hour,
        "session": "london",
        "regime": "trend_up",
    }


def intent(timestamp: datetime, direction: int = 1, atr: float = 2.0) -> TradeIntent:
    return TradeIntent(
        snapshot_time=timestamp,
        entry_time=timestamp + timedelta(minutes=5),
        direction=direction,
        atr=atr,
        year=timestamp.year,
        month=timestamp.month,
        weekday=timestamp.isoweekday(),
        session="london",
        regime="trend_up",
    )


def candle(timestamp: datetime, open_: float, high: float, low: float, close: float) -> dict:
    return {"candle_time": timestamp.isoformat(), "open": open_, "high": high, "low": low, "close": close}


def metrics(*, trades: int, pf: float, expectancy: float, stability: float = 0.8, resolved: float = 1.0, drawdown: float = 8.0) -> ReplayMetrics:
    return ReplayMetrics(
        trades=trades,
        wins=trades // 2,
        losses=trades // 2,
        win_rate=50.0,
        net_r=trades * expectancy,
        expectancy_r=expectancy,
        profit_factor=pf,
        max_drawdown_r=drawdown,
        yearly_expectancy={"2024": expectancy, "2025": expectancy},
        monthly_expectancy={},
        weekday_expectancy={},
        session_expectancy={},
        regime_expectancy={},
        year_stability=stability,
        unresolved=0,
        resolved_rate=resolved,
    )


def test_intent_enters_after_source_m5_candle_closes() -> None:
    timestamp = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    rows = [snapshot(timestamp)]
    rules = {
        "source_conditions": [],
        "condition_mode": "include",
        "direction_rule": "current_direction",
        "cooldown_minutes": 15,
    }
    intents = build_trade_intents(rows, rules)
    assert len(intents) == 1
    assert intents[0].entry_time == timestamp + timedelta(minutes=5)


def test_m1_replay_can_prove_target_happened_before_later_stop() -> None:
    timestamp = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    trade_intent = intent(timestamp, atr=2.0)
    start = trade_intent.entry_time
    bars = [
        candle(start, 100.0, 101.0, 99.5, 100.8),
        candle(start + timedelta(minutes=1), 100.8, 104.2, 100.5, 103.8),
        candle(start + timedelta(minutes=2), 103.8, 104.0, 97.0, 98.0),
    ]
    trade = replay_one_intent(trade_intent, bars, stop_atr=1.0, target_atr=2.0, hold_minutes=15, cost_r=0.0)
    assert trade is not None
    assert trade.exit_reason == "target"
    assert trade.net_r == 2.0


def test_same_m1_bar_two_sided_ambiguity_counts_stop_first() -> None:
    timestamp = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    trade_intent = intent(timestamp, atr=2.0)
    start = trade_intent.entry_time
    bars = [candle(start, 100.0, 104.5, 97.5, 101.0)]
    trade = replay_one_intent(trade_intent, bars, stop_atr=1.0, target_atr=2.0, hold_minutes=15, cost_r=0.0)
    assert trade is not None
    assert trade.exit_reason == "stop"
    assert trade.net_r == -1.0


def test_ready_classification_requires_cost_and_parameter_robustness() -> None:
    result, reasons = classify_validation(
        metrics(trades=60, pf=1.25, expectancy=0.08, stability=0.8),
        metrics(trades=90, pf=1.35, expectancy=0.09, stability=0.75),
        metrics(trades=90, pf=1.12, expectancy=0.04, stability=0.75),
        0.75,
    )
    assert result == "ready_for_mt5_generation"
    assert reasons == []


def test_bad_execution_cost_stress_prevents_ready_status() -> None:
    result, reasons = classify_validation(
        metrics(trades=60, pf=1.25, expectancy=0.08),
        metrics(trades=90, pf=1.35, expectancy=0.09),
        metrics(trades=90, pf=0.95, expectancy=-0.01),
        0.75,
    )
    assert result == "rejected"
    assert any("execution-cost" in reason for reason in reasons)


def test_parameter_profiles_challenge_nearby_settings_without_changing_base() -> None:
    rules = {"stop_atr": 1.0, "target_atr": 2.0, "horizon_minutes": 60, "cooldown_minutes": 60}
    profiles = parameter_profiles(rules)
    assert profiles["base"]["stop_atr"] == 1.0
    assert profiles["base"]["target_atr"] == 2.0
    assert profiles["stop_minus_15pct"]["stop_atr"] == 0.85
    assert profiles["target_plus_15pct"]["target_atr"] == 2.3
    assert len(profiles) == 9


def test_validation_key_is_deterministic_and_rule_sensitive() -> None:
    first = validation_key("evolution", "abc", {"stop_atr": 1.0})
    second = validation_key("evolution", "abc", {"stop_atr": 1.0})
    changed = validation_key("evolution", "abc", {"stop_atr": 1.1})
    assert first == second
    assert first != changed


def test_day_block_fetch_paginates_without_repeating_first_page() -> None:
    import asyncio
    from app.services.high_resolution_validation import _fetch_m1_days

    class FakeRepo:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_candles_page(self, symbol, interval, after=None, date_from=None, date_to=None, limit=1000):
            self.calls += 1
            start = (datetime.fromisoformat(after) + timedelta(minutes=1)) if after else datetime.fromisoformat(date_from)
            end = datetime.fromisoformat(date_to)
            rows = []
            current = start
            while current <= end and len(rows) < limit:
                rows.append(candle(current, 100.0, 100.2, 99.8, 100.1))
                current += timedelta(minutes=1)
            return rows

    repo = FakeRepo()
    entry = datetime(2026, 1, 5, 10, 5, tzinfo=timezone.utc)
    blocks = asyncio.run(_fetch_m1_days(repo, "XAU/USD", {entry: 240}))
    assert repo.calls == 2
    assert len(blocks["2026-01-05"]) > 1000
