from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.supabase_repo import SupabaseRepository
from app.services.twelve_data import INTERVAL_SECONDS, TwelveDataClient
from app.settings import Settings

logger = logging.getLogger(__name__)


def _as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def estimate_market_bars(earliest: datetime, latest: datetime, interval_seconds: int) -> int:
    """Approximate 24/5 bars. Exact database count replaces this at completion."""
    if latest <= earliest:
        return 0
    full_days = (latest.date() - earliest.date()).days + 1
    business_days = sum(
        1 for offset in range(full_days) if (earliest.date() + timedelta(days=offset)).weekday() < 5
    )
    bars_per_day = max(1, 86400 // interval_seconds)
    return business_days * bars_per_day


def completed_only(candles: list[Any], interval_seconds: int, now: datetime | None = None) -> list[Any]:
    """Exclude the currently forming bar; the database stores completed candles as source-of-truth."""
    reference = now or datetime.now(timezone.utc)
    return [candle for candle in candles if candle.timestamp + timedelta(seconds=interval_seconds) <= reference]


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
        await self.repo.reset_stale_jobs()
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
            await self.repo.log_event("error", "ingestion", f"{job_type} failed for {symbol} {interval}", {"error": str(exc)})

    async def backfill(self, job_id: str, symbol: str, interval: str, parameters: dict[str, Any]) -> None:
        interval_seconds = INTERVAL_SECONDS[interval]
        state = await self.repo.get_state(symbol, interval) or {}
        force_restart = bool(parameters.get("force_restart", False))

        if force_restart:
            cursor = datetime.now(timezone.utc)
            rows_processed = 0
            batches = 0
        else:
            cursor = _as_datetime(state.get("next_end_time")) or datetime.now(timezone.utc)
            rows_processed = int(state.get("rows_processed") or 0)
            batches = int(state.get("batches_completed") or 0)

        latest_seen = _as_datetime(state.get("latest_stored"))
        earliest = _as_datetime(state.get("earliest_available"))
        if earliest is None or force_restart:
            await self.repo.update_job(job_id, message="Finding earliest available Twelve Data candle")
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
        await self.repo.log_event("info", "ingestion", f"Historical download started for {symbol} {interval}")

        previous_oldest: datetime | None = None
        while cursor >= earliest and not self._stop.is_set():
            current_job = await self.repo.get_job(job_id)
            if current_job and current_job.get("status") == "cancelled":
                await self.repo.upsert_state(symbol, interval, status="paused")
                await self.repo.update_job(job_id, finished_at=datetime.now(timezone.utc).isoformat(), message="Download cancelled")
                return

            candles = await self.twelve.time_series(
                symbol=symbol,
                interval=interval,
                outputsize=self.settings.twelve_data_batch_size,
                end_date=cursor,
            )
            candles = completed_only(candles, interval_seconds)
            if not candles:
                raise RuntimeError(f"Twelve Data returned no candles before {cursor.isoformat()}")

            oldest = min(candle.timestamp for candle in candles)
            newest = max(candle.timestamp for candle in candles)
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
            )
            await self.repo.update_job(
                job_id,
                progress_percent=round(progress, 3),
                message=f"Batch {batches}: processed {rows_processed:,} candles; oldest {oldest:%Y-%m-%d %H:%M UTC}",
            )

            if oldest <= earliest + timedelta(seconds=interval_seconds):
                break
            await asyncio.sleep(self.settings.twelve_data_request_delay_seconds)

        await self.repo.refresh_state(symbol, interval)
        await self.repo.upsert_state(
            symbol,
            interval,
            status="complete",
            next_end_time=None,
            progress_percent=100,
            last_success_at=datetime.now(timezone.utc).isoformat(),
            last_error=None,
        )
        gaps = await self.repo.scan_gaps(symbol, interval, interval_seconds)
        await self.repo.update_job(
            job_id,
            status="complete",
            progress_percent=100,
            message=f"Historical database ready. Gap review items: {gaps.get('review', 0)}",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        await self.repo.log_event("success", "ingestion", f"Historical download completed for {symbol} {interval}", {"rows_processed": rows_processed, "gaps": gaps})

    async def sync_latest(self, job_id: str | None, symbol: str, interval: str) -> None:
        if job_id:
            await self.repo.update_job(job_id, message="Fetching latest completed candles")
        await self.repo.upsert_state(symbol, interval, status="syncing", last_error=None)
        candles = await self.twelve.time_series(symbol, interval, outputsize=50)
        candles = completed_only(candles, INTERVAL_SECONDS[interval])
        if not candles:
            raise RuntimeError("No recent candles returned")
        await self.repo.bulk_upsert_candles([candle.to_row(symbol, interval) for candle in candles])
        latest = max(candle.timestamp for candle in candles)
        await self.repo.upsert_state(
            symbol,
            interval,
            status="complete",
            progress_percent=100,
            latest_stored=latest.isoformat(),
            last_success_at=datetime.now(timezone.utc).isoformat(),
        )
        if job_id:
            await self.repo.update_job(
                job_id,
                status="complete",
                progress_percent=100,
                message=f"Latest candles synchronised through {latest:%Y-%m-%d %H:%M UTC}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        await self.repo.log_event("success", "live_sync", f"Latest {symbol} {interval} candles synchronised", {"latest": latest.isoformat()})

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

    async def auto_sync_loop(self) -> None:
        if not self.settings.auto_sync_enabled:
            logger.info("Automatic latest-candle sync is disabled")
            return

        interval = self.settings.default_interval
        seconds = INTERVAL_SECONDS.get(interval, 300)
        logger.info("Automatic sync enabled for %s %s", self.settings.default_symbol, interval)

        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            next_boundary_epoch = ((int(now.timestamp()) // seconds) + 1) * seconds
            run_at = datetime.fromtimestamp(next_boundary_epoch, tz=timezone.utc) + timedelta(seconds=self.settings.auto_sync_offset_seconds)
            wait_seconds = max(1, (run_at - now).total_seconds())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
                break
            except asyncio.TimeoutError:
                pass

            try:
                state = await self.repo.get_state(self.settings.default_symbol, interval)
                if state and state.get("status") == "downloading":
                    continue
                await self.sync_latest(None, self.settings.default_symbol, interval)
            except Exception as exc:
                logger.exception("Automatic sync failed")
                await self.repo.log_event("error", "live_sync", "Automatic sync failed", {"error": str(exc)})
