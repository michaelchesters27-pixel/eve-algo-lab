from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.h1_30m_research import analyze_candles


def hour_rows(start: datetime, outcome: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for minute in range(60):
        open_price = 100.0
        close_price = 101.0 if minute < 30 else 100.5
        high = 101.5
        low = 99.0
        if minute == 5:
            high = 101.8
        if minute == 12:
            low = 98.0
        if minute >= 30:
            if outcome == "high_only" and minute == 40:
                high = 103.0
            elif outcome == "low_only" and minute == 41:
                low = 97.0
            elif outcome == "both_low_first":
                if minute == 35:
                    low = 97.0
                if minute == 45:
                    high = 103.0
            elif outcome == "both_same_minute" and minute == 36:
                high = 103.0
                low = 97.0
        rows.append(
            {
                "candle_time": (start + timedelta(minutes=minute)).isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 1,
            }
        )
    return rows


def test_classifies_second_half_outcomes_and_first_break_order() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    candles = []
    for offset, outcome in enumerate(("neither", "high_only", "low_only", "both_low_first", "both_same_minute")):
        candles.extend(hour_rows(start + timedelta(hours=offset), outcome))

    report = analyze_candles(candles)

    assert report["data_quality"]["complete_hours"] == 5
    assert report["data_quality"]["qualifying_two_wick_hours"] == 5
    assert report["full"]["outcomes"]["neither"]["count"] == 1
    assert report["full"]["outcomes"]["high_only"]["count"] == 1
    assert report["full"]["outcomes"]["low_only"]["count"] == 1
    assert report["full"]["outcomes"]["both"]["count"] == 2
    assert report["full"]["first_break"]["high"] == 1
    assert report["full"]["first_break"]["low"] == 2
    assert report["full"]["first_break"]["same_minute_ambiguous"] == 1
    assert report["full"]["first_break"]["none"] == 1


def test_excludes_incomplete_hours_instead_of_inventing_missing_minutes() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    complete = hour_rows(start, "neither")
    incomplete = hour_rows(start + timedelta(hours=1), "high_only")[:-1]

    report = analyze_candles([*complete, *incomplete])

    assert report["data_quality"]["hour_groups_seen"] == 2
    assert report["data_quality"]["complete_hours"] == 1
    assert report["data_quality"]["incomplete_hours_excluded"] == 1
    assert report["data_quality"]["qualifying_two_wick_hours"] == 1


def test_price_position_and_wick_breakdowns_are_reported() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    report = analyze_candles(hour_rows(start, "high_only"))

    position_groups = {row["group"] for row in report["breakdowns"]["price_position"]}
    wick_groups = {row["group"] for row in report["breakdowns"]["wick_dominance"]}

    assert "upper_60_80" in position_groups
    assert "lower_gt_2x_upper" in wick_groups
    assert report["full"]["at_least_one_break"]["rate_pct"] == 100.0
