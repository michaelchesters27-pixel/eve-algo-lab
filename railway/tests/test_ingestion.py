from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.ingestion import completed_only, deduplicate_candles, historical_backfill_complete
from app.services.twelve_data import Candle


def candle_at(timestamp: datetime, close: str = "4000") -> Candle:
    value = Decimal(close)
    return Candle(timestamp=timestamp, open=value, high=value, low=value, close=value, volume=None)


def test_completed_only_excludes_forming_bar() -> None:
    now = datetime(2026, 7, 31, 10, 7, tzinfo=timezone.utc)
    completed = candle_at(datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc))
    forming = candle_at(datetime(2026, 7, 31, 10, 5, tzinfo=timezone.utc))
    assert completed_only([forming, completed], 300, now=now) == [completed]


def test_deduplicate_candles_keeps_one_row_per_timestamp() -> None:
    when = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    result = deduplicate_candles([candle_at(when, "4000"), candle_at(when, "4001")])
    assert len(result) == 1
    assert result[0].close == Decimal("4001")


def test_live_sync_only_is_not_historical_complete() -> None:
    state = {
        "status": "complete",  # bad v1 state caused by live sync
        "rows_in_database": 50,
        "oldest_stored": "2026-07-31T06:00:00+00:00",
        "earliest_available": None,
        "next_end_time": None,
    }
    assert historical_backfill_complete(state, 300) is False


def test_verified_boundaries_are_historical_complete() -> None:
    earliest = datetime(2020, 1, 9, tzinfo=timezone.utc)
    state = {
        "status": "complete",
        "rows_in_database": 570_000,
        "oldest_stored": (earliest + timedelta(minutes=5)).isoformat(),
        "earliest_available": earliest.isoformat(),
        "next_end_time": None,
    }
    assert historical_backfill_complete(state, 300) is True
