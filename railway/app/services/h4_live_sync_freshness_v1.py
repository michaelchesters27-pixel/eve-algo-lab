from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services import ingestion as core
from app.services.twelve_data import INTERVAL_SECONDS

logger = logging.getLogger(__name__)

# Twelve Data's XAU/USD 4H bars are aligned to the provider/market session, not
# permanently to UTC epoch multiples. The alignment shifts by an hour across
# daylight-saving periods. Polling at a short UTC cadence is therefore safer
# than guessing a fixed 00/04/08 or 01/05/09 schedule.
H4_SYNC_POLL_SECONDS = 15 * 60
PATCH_VERSION = "eve-h4-live-sync-freshness-v1"


def auto_sync_poll_seconds(interval: str) -> int:
    """Return how often live sync should check for a newly completed candle.

    Normal intervals retain their original candle-boundary cadence. H4 is the
    exception because provider H4 boundaries are session-aligned and can move
    by one UTC hour with DST. A 15-minute poll keeps H4 fresh without inventing
    candle timestamps; `completed_only` still decides whether a provider bar is
    actually closed before it can enter source-of-truth storage.
    """
    interval_seconds = INTERVAL_SECONDS[interval]
    if interval == "4h":
        return H4_SYNC_POLL_SECONDS
    return interval_seconds


def next_auto_sync_run_at(
    now: datetime,
    interval: str,
    *,
    offset_seconds: int,
    stagger_seconds: int,
) -> datetime:
    """Return the next polling instant on a deterministic UTC cadence."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    cadence = auto_sync_poll_seconds(interval)
    next_boundary_epoch = ((int(now.timestamp()) // cadence) + 1) * cadence
    return datetime.fromtimestamp(next_boundary_epoch, tz=timezone.utc) + timedelta(
        seconds=max(0, offset_seconds) + max(0, stagger_seconds)
    )


async def auto_sync_loop_v1(
    self: core.IngestionService,
    interval: str | None = None,
    stagger_index: int = 0,
) -> None:
    """Synchronise completed candles without assuming a fixed UTC H4 anchor."""
    if not self.settings.auto_sync_enabled:
        logger.info("Automatic latest-candle sync is disabled")
        return

    selected_interval = interval or self.settings.default_interval
    if selected_interval not in INTERVAL_SECONDS:
        logger.error("Automatic sync interval is unsupported: %s", selected_interval)
        return

    cadence = auto_sync_poll_seconds(selected_interval)
    logger.info(
        "Automatic sync enabled for %s %s (poll cadence %ss; %s)",
        self.settings.default_symbol,
        selected_interval,
        cadence,
        PATCH_VERSION,
    )

    while not self._stop.is_set():
        now = datetime.now(timezone.utc)
        stagger = max(0, stagger_index) * self.settings.auto_sync_stagger_seconds
        run_at = next_auto_sync_run_at(
            now,
            selected_interval,
            offset_seconds=self.settings.auto_sync_offset_seconds,
            stagger_seconds=stagger,
        )
        wait_seconds = max(1, (run_at - now).total_seconds())
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
            break
        except asyncio.TimeoutError:
            pass

        try:
            state = await self.repo.get_state(self.settings.default_symbol, selected_interval)
            if state and state.get("status") in {"queued", "downloading"}:
                continue
            # sync_latest remains the single source of truth: it asks Twelve Data
            # for recent bars, rejects every still-forming candle, and upserts by
            # provider timestamp. Repeated H4 polls are therefore idempotent.
            await self.sync_latest(None, self.settings.default_symbol, selected_interval)
        except Exception as exc:
            logger.exception("Automatic sync failed for %s", selected_interval)
            await self.repo.log_event(
                "error",
                "live_sync",
                f"Automatic {selected_interval} sync failed",
                {
                    "error": str(exc),
                    "interval": selected_interval,
                    "poll_cadence_seconds": cadence,
                    "sync_patch_version": PATCH_VERSION,
                },
            )


core.IngestionService.auto_sync_loop = auto_sync_loop_v1  # type: ignore[method-assign]
