from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.supabase_repo import SupabaseRepository
from app.services.twelve_data import INTERVAL_SECONDS, Candle, TwelveDataClient
from app.settings import Settings

logger = logging.getLogger(__name__)


def as_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def estimate_market_bars(earliest: datetime, latest: datetime, interval_seconds: int) -> int:
    """Approximate 24/5 bars. The exact database count replaces this at completion."""
    if latest <= earliest:
        return 0
    full_days = (latest.date() - earliest.date()).days + 1
    business_days = sum(
        1 for offset in range(full_days) if (earliest.date() + timedelta(days=offset)).weekday() < 5
    )
    bars_per_day = max(1, 86400 // interval_seconds)
    return business_days * bars_per_day


def completed_only(candles: list[Candle], interval_seconds: int, now: datetime | None = None) -> list[Candle]:
    """Exclude the currently forming bar; only completed candles become source-of-truth."""
    reference = now or datetime.now(timezone.utc)
    return [candle for candle in candles if candle.timestamp + timedelta(seconds=interval_seconds) <= reference]


def deduplicate_candles(candles: list[Candle]) -> list[Candle]:
    """Defensively remove duplicate timestamps from a provider response."""
    by_time = {candle.timestamp: candle for candle in candles}
    return sorted(by_time.values(), key=lambda candle: candle.timestamp, reverse=True)


def historical_backfill_complete(state: dict[str, Any] | None, interval_seconds: int) -> bool:
    """Return True only when the stored oldest candle reaches Twelve Data's earliest boundary.

    Earlier releases incorrectly marked the whole historical dataset complete after a latest-candle
    sync. Requiring both boundaries prevents that state from disabling the real backfill button.
    """
    if not state:
        return False
    earliest = as_utc_datetime(state.get("earliest_available"))
    oldest = as_utc_datetime(state.get("oldest_stored"))
    rows = int(state.get("rows_in_database") or 0)
    if not earliest or not oldest or rows <= 0:
        return False
    strict_tolerance = timedelta(seconds=max(interval_seconds * 2, 120))
    if oldest <= earliest + strict_tolerance:
        return True

    # Some instruments publish an earliest boundary during a market closure rather than the
    # timestamp of the first actual bar. A completed job with no remaining cursor may therefore
    # finish a few days after that boundary (for example, over a weekend).
    status = str(state.get("status") or "")
    no_remaining_cursor = not state.get("next_end_time")
    return status == "complete" and no_remaining_cursor and oldest <= earliest + timedelta(days=7)


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        repo: SupabaseRepository,
        twelve: TwelveDataClient,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.twelve = twelve
        self.worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    async def worker_loop(self) -> None:
        logger.info("Ingestion worker %s started", self.worker_id)
        await self.repo.reset_stale_jobs(stale_minutes=0)
        while not self._stop.is_set():
            try:
                job = await self.repo.claim_next_job(self.worker_id)
                if not job:
                    await asyncio.sleep(self.settings.worker_poll_seconds)
                    continue
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(5)

    async def _run_job(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        job_type = job["job_type"]
        symbol = job["symbol"]
        interval = job["interval"]
        try:
            if job_type == "backfill":
                await self.backfill(job_id, symbol, interval, job.get("parameters") or {})
            elif job_type == "sync_latest":
                await self.sync_latest(job_id, symbol, interval)
            elif job_type == "gap_scan":
                await self.gap_scan(job_id, symbol, interval)
            else:
                raise ValueError(f"Unsupported job type: {job_type}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            await self.repo.update_job(
                job_id,
                status="failed",
                error=str(exc)[:4000],
                message="Job failed — see Railway logs",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.upsert_state(symbol, interval, status="error", last_error=str(exc)[:4000])
            await self.repo.log_event(
                "error",
                "ingestion",
                f"{job_type} failed for {symbol} {interval}",
                {"error": str(exc)},
            )

    async def backfill(self, job_id: str, symbol: str, interval: str, parameters: dict[str, Any]) -> None:
        interval_seconds = INTERVAL_SECONDS[interval]
        state = await self.repo.get_state(symbol, interval) or {}
        force_restart = bool(parameters.get("force_restart", False))

        if force_restart:
            cursor = datetime.now(timezone.utc)
            rows_processed = 0
            batches = 0
        else:
            cursor = as_utc_datetime(state.get("next_end_time")) or datetime.now(timezone.utc)
            rows_processed = int(state.get("rows_processed") or 0)
            batches = int(state.get("batches_completed") or 0)

        latest_seen = as_utc_datetime(state.get("latest_stored"))
        earliest = as_utc_datetime(state.get("earliest_available"))
        if earliest is None or force_restart:
            await self.repo.update_job(job_id, message="Finding the earliest available Twelve Data candle")
            earliest = await self.twelve.earliest_timestamp(symbol, interval)

        estimated_total = estimate_market_bars(earliest, datetime.now(timezone.utc), interval_seconds)
        await self.repo.upsert_state(
            symbol,
            interval,
            status="downloading",
            earliest_available=earliest.isoformat(),
            next_end_time=cursor.isoformat(),
            estimated_total=estimated_total,
            last_error=None,
        )
        await self.repo.log_event(
            "info",
            "ingestion",
            f"Historical download started for {symbol} {interval}",
            {"resume_cursor": cursor.isoformat(), "estimated_total": estimated_total},
        )

        previous_oldest: datetime | None = None
        reached_start = False

        while cursor >= earliest and not self._stop.is_set():
            current_job = await self.repo.get_job(job_id)
            if current_job and current_job.get("status") == "cancelled":
                await self.repo.upsert_state(symbol, interval, status="paused")
                await self.repo.update_job(
                    job_id,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    message="Historical download paused. Press Resume to continue from the saved cursor.",
                )
                await self.repo.log_event("warning", "ingestion", f"Historical download paused for {symbol} {interval}")
                return

            candles = await self.twelve.time_series(
                symbol=symbol,
                interval=interval,
                outputsize=self.settings.twelve_data_batch_size,
                end_date=cursor,
            )
            provider_row_count = len(candles)
            candles = deduplicate_candles(completed_only(candles, interval_seconds))
            if not candles:
                raise RuntimeError(f"Twelve Data returned no completed candles before {cursor.isoformat()}")

            oldest = min(candle.timestamp for candle in candles)
            newest = max(candle.timestamp for candle in candles)
            if newest > cursor + timedelta(seconds=interval_seconds):
                raise RuntimeError("Twelve Data returned candles newer than the requested historical cursor")
            if previous_oldest is not None and oldest >= previous_oldest:
                raise RuntimeError("Historical cursor did not move backwards; stopped to prevent an infinite loop")

            await self.repo.bulk_upsert_candles([candle.to_row(symbol, interval) for candle in candles])
            rows_processed += len(candles)
            batches += 1
            previous_oldest = oldest
            latest_seen = newest if latest_seen is None else max(latest_seen, newest)
            cursor = oldest - timedelta(seconds=interval_seconds)

            coverage = (datetime.now(timezone.utc) - oldest).total_seconds()
            available = max(1, (datetime.now(timezone.utc) - earliest).total_seconds())
            progress = min(99.9, max(0.0, coverage / available * 100))

            await self.repo.upsert_state(
                symbol,
                interval,
                status="downloading",
                next_end_time=cursor.isoformat(),
                oldest_stored=oldest.isoformat(),
                latest_stored=latest_seen.isoformat(),
                rows_processed=rows_processed,
                batches_completed=batches,
                progress_percent=round(progress, 3),
                last_success_at=datetime.now(timezone.utc).isoformat(),
                last_error=None,
            )

            count_every = max(self.settings.exact_count_every_batches, 20) if interval == "1min" else self.settings.exact_count_every_batches
            if batches % count_every == 0:
                await self.repo.refresh_state(symbol, interval)

            await self.repo.update_job(
                job_id,
                progress_percent=round(progress, 3),
                message=(
                    f"Batch {batches}: processed {rows_processed:,} candles; "
                    f"oldest {oldest:%Y-%m-%d %H:%M UTC}"
                ),
            )

            near_published_start = oldest <= earliest + timedelta(days=7)
            reached_start = (
                oldest <= earliest + timedelta(seconds=interval_seconds * 2)
                or (provider_row_count < self.settings.twelve_data_batch_size and near_published_start)
            )
            if reached_start:
                break

            await asyncio.sleep(self.settings.twelve_data_request_delay_seconds)

        if self._stop.is_set() and not reached_start:
            await self.repo.upsert_state(symbol, interval, status="paused")
            return

        await self.repo.refresh_state(symbol, interval)
        final_state = await self.repo.get_state(symbol, interval) or {}
        if not historical_backfill_complete(final_state, interval_seconds):
            # A short final provider batch can legitimately finish just after the published earliest
            # timestamp. If not, keep the saved cursor and require a resume rather than falsely claiming 100%.
            oldest_stored = as_utc_datetime(final_state.get("oldest_stored"))
            if oldest_stored and reached_start and oldest_stored <= earliest + timedelta(days=7):
                pass
            else:
                await self.repo.upsert_state(
                    symbol,
                    interval,
                    status="paused",
                    progress_percent=min(99.9, float(final_state.get("progress_percent") or 0)),
                    last_error="Historical boundary was not verified. Resume the download to continue.",
                )
                await self.repo.update_job(
                    job_id,
                    status="failed",
                    message="Historical boundary was not verified; the saved cursor is safe to resume.",
                    error="Backfill stopped before the verified earliest boundary.",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return

        await self.repo.upsert_state(
            symbol,
            interval,
            status="complete",
            next_end_time=None,
            progress_percent=100,
            last_success_at=datetime.now(timezone.utc).isoformat(),
            last_error=None,
        )

        gaps: dict[str, Any] = {"total": 0, "review": 0}
        try:
            gaps = await self.repo.scan_gaps(symbol, interval, interval_seconds)
        except Exception as exc:
            logger.exception("Post-backfill gap scan failed")
            await self.repo.log_event(
                "warning",
                "data_quality",
                "Historical download completed, but the automatic gap scan needs to be run again",
                {"error": str(exc)},
            )

        exact_state = await self.repo.get_state(symbol, interval) or {}
        exact_rows = int(exact_state.get("rows_in_database") or 0)
        await self.repo.update_job(
            job_id,
            status="complete",
            progress_percent=100,
            message=f"Historical database ready: {exact_rows:,} candles stored. Gap review items: {gaps.get('review', 0)}",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        await self.repo.log_event(
            "success",
            "ingestion",
            f"Historical download completed for {symbol} {interval}",
            {"rows_in_database": exact_rows, "batches": batches, "gaps": gaps},
        )

    async def sync_latest(self, job_id: str | None, symbol: str, interval: str) -> None:
        interval_seconds = INTERVAL_SECONDS[interval]
        original_state = await self.repo.get_state(symbol, interval) or {}
        original_status = original_state.get("status") or "not_started"

        if job_id:
            await self.repo.update_job(job_id, message="Fetching the latest completed candles")

        candles = await self.twelve.time_series(symbol, interval, outputsize=50)
        candles = deduplicate_candles(completed_only(candles, interval_seconds))
        if not candles:
            raise RuntimeError("No recent completed candles returned")

        await self.repo.bulk_upsert_candles([candle.to_row(symbol, interval) for candle in candles])
        await self.repo.refresh_state(symbol, interval)
        refreshed = await self.repo.get_state(symbol, interval) or {}
        latest = max(candle.timestamp for candle in candles)

        # Live synchronisation must never pretend that the multi-year historical backfill is complete.
        if historical_backfill_complete(refreshed, interval_seconds):
            preserved_status = "complete"
            preserved_progress = 100
        elif original_status in {"queued", "downloading", "paused", "error"}:
            preserved_status = original_status
            preserved_progress = float(original_state.get("progress_percent") or 0)
        else:
            preserved_status = "not_started"
            preserved_progress = 0

        preserved_error = original_state.get("last_error") if preserved_status == "error" else None
        await self.repo.upsert_state(
            symbol,
            interval,
            status=preserved_status,
            progress_percent=preserved_progress,
            latest_stored=latest.isoformat(),
            last_success_at=datetime.now(timezone.utc).isoformat(),
            last_error=preserved_error,
        )

        if job_id:
            await self.repo.update_job(
                job_id,
                status="complete",
                progress_percent=100,
                message=f"Latest candles synchronised through {latest:%Y-%m-%d %H:%M UTC}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.repo.log_event(
                "success",
                "live_sync",
                f"Latest {symbol} {interval} candles synchronised",
                {"latest": latest.isoformat()},
            )

    async def gap_scan(self, job_id: str | None, symbol: str, interval: str) -> dict[str, Any]:
        if job_id:
            await self.repo.update_job(job_id, message="Scanning chronological candle gaps")
        result = await self.repo.scan_gaps(symbol, interval, INTERVAL_SECONDS[interval])
        if job_id:
            await self.repo.update_job(
                job_id,
                status="complete",
                progress_percent=100,
                message=f"Gap scan complete: {result.get('review', 0)} items need review",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        await self.repo.log_event("info", "data_quality", f"Gap scan completed for {symbol} {interval}", result)
        return result

    async def auto_sync_loop(self, interval: str | None = None) -> None:
        """Synchronise one interval shortly after each completed candle boundary.

        v1.3 runs one loop for M1 and one for M5. A historical backfill for an
        interval takes priority, so automatic sync quietly waits until that job
        is no longer queued or downloading.
        """
        if not self.settings.auto_sync_enabled:
            logger.info("Automatic latest-candle sync is disabled")
            return

        selected_interval = interval or self.settings.default_interval
        seconds = INTERVAL_SECONDS.get(selected_interval)
        if seconds is None:
            logger.error("Automatic sync interval is unsupported: %s", selected_interval)
            return
        logger.info("Automatic sync enabled for %s %s", self.settings.default_symbol, selected_interval)

        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            next_boundary_epoch = ((int(now.timestamp()) // seconds) + 1) * seconds
            run_at = datetime.fromtimestamp(next_boundary_epoch, tz=timezone.utc) + timedelta(
                seconds=self.settings.auto_sync_offset_seconds
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
                await self.sync_latest(None, self.settings.default_symbol, selected_interval)
            except Exception as exc:
                logger.exception("Automatic sync failed for %s", selected_interval)
                await self.repo.log_event(
                    "error",
                    "live_sync",
                    f"Automatic {selected_interval} sync failed",
                    {"error": str(exc), "interval": selected_interval},
                )

