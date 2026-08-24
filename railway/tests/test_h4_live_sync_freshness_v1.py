from datetime import datetime, timezone

from app.services.h4_live_sync_freshness_v1 import (
    H4_SYNC_POLL_SECONDS,
    auto_sync_poll_seconds,
    next_auto_sync_run_at,
)


def test_h4_is_polled_every_fifteen_minutes_not_every_four_hours() -> None:
    assert auto_sync_poll_seconds("4h") == 15 * 60
    assert H4_SYNC_POLL_SECONDS == 15 * 60


def test_other_timeframes_keep_existing_sync_cadence() -> None:
    assert auto_sync_poll_seconds("1min") == 60
    assert auto_sync_poll_seconds("5min") == 5 * 60
    assert auto_sync_poll_seconds("15min") == 15 * 60
    assert auto_sync_poll_seconds("1h") == 60 * 60
    assert auto_sync_poll_seconds("1day") == 24 * 60 * 60


def test_h4_does_not_wait_for_next_utc_four_hour_boundary() -> None:
    now = datetime(2026, 8, 24, 5, 1, tzinfo=timezone.utc)
    run_at = next_auto_sync_run_at(
        now,
        "4h",
        offset_seconds=22,
        stagger_seconds=12,
    )
    assert run_at == datetime(2026, 8, 24, 5, 15, 34, tzinfo=timezone.utc)


def test_h4_polling_is_independent_of_provider_dst_anchor() -> None:
    # Summer provider H4 starts have historically appeared at 01/05/09...
    summer = next_auto_sync_run_at(
        datetime(2026, 8, 24, 4, 59, tzinfo=timezone.utc),
        "4h",
        offset_seconds=22,
        stagger_seconds=12,
    )
    # Winter history also contains 00/04/08... H4 anchors. The same poller catches
    # either schedule without hardcoding which UTC hour the provider is using.
    winter = next_auto_sync_run_at(
        datetime(2026, 1, 12, 3, 59, tzinfo=timezone.utc),
        "4h",
        offset_seconds=22,
        stagger_seconds=12,
    )
    assert summer == datetime(2026, 8, 24, 5, 0, 34, tzinfo=timezone.utc)
    assert winter == datetime(2026, 1, 12, 4, 0, 34, tzinfo=timezone.utc)
