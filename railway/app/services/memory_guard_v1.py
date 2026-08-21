from __future__ import annotations

"""P0 process-memory hardening for EVE Algo Lab.

The learning snapshot history is immutable and append-only. Rebuilding the full
six-year Python object graph whenever one new snapshot arrives temporarily keeps
both the old and new lists alive and creates large Railway RAM spikes. This guard
makes the existing ContinuousHistoricalResearchService cache append-only and
makes AutonomousLearningService borrow that shared cache instead of independently
materialising the same history.
"""

import asyncio
from datetime import datetime, timezone
import weakref
from typing import Any

from app.services.autonomy import AutonomousLearningService
from app.services.historical_research import ContinuousHistoricalResearchService
from app.services.learning import SNAPSHOT_INTERVAL, as_utc

MEMORY_GUARD_VERSION = "eve-algo-memory-guard-v1"

_ORIGINAL_HISTORY_INIT = ContinuousHistoricalResearchService.__init__
_ORIGINAL_HISTORY_LOAD = ContinuousHistoricalResearchService._load_rows
_ORIGINAL_AUTONOMY_FETCH = AutonomousLearningService._fetch_all_snapshots
_SHARED_HISTORY_REF: weakref.ReferenceType[Any] | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _patched_history_init(self: ContinuousHistoricalResearchService, *args: Any, **kwargs: Any) -> None:
    global _SHARED_HISTORY_REF
    _ORIGINAL_HISTORY_INIT(self, *args, **kwargs)
    self._memory_load_lock = asyncio.Lock()
    _SHARED_HISTORY_REF = weakref.ref(self)


async def _append_new_complete_rows(self: ContinuousHistoricalResearchService, latest_snapshot: datetime) -> list[dict[str, Any]]:
    """Append only rows newer than the resident immutable history."""
    if not self._rows_cache:
        return await _ORIGINAL_HISTORY_LOAD(self)

    last_cached = as_utc(self._rows_cache[-1].get("candle_time"))
    if last_cached is None:
        # Corrupt/unknown cache ordering: rebuild through the original guarded
        # path rather than guessing a cursor.
        self._rows_cache = []
        self._cache_snapshot_time = None
        self._cache_loaded_at = None
        return await _ORIGINAL_HISTORY_LOAD(self)

    # A source reset moving backwards is exceptional. Rebuild exactly once so
    # the cache cannot silently contain rows beyond the authoritative state.
    if self._cache_snapshot_time is not None and latest_snapshot < self._cache_snapshot_time:
        self._rows_cache = []
        self._cache_snapshot_time = None
        self._cache_loaded_at = None
        return await _ORIGINAL_HISTORY_LOAD(self)

    after = last_cached.isoformat()
    appended = 0
    while not self._stop.is_set():
        page = await self.repo.fetch_learning_snapshots_page(
            "XAU/USD",
            SNAPSHOT_INTERVAL,
            after=after,
            complete_only=True,
            limit=1000,
        )
        if not page:
            break
        # Defensive keyset monotonicity: never append a duplicate/non-advancing
        # page because that would turn a cache optimisation into a true leak.
        next_after = str(page[-1].get("candle_time") or "")
        if not next_after or as_utc(next_after) is None or as_utc(next_after) <= as_utc(after):
            raise RuntimeError("Historical memory append cursor did not advance")
        self._rows_cache.extend(page)
        appended += len(page)
        after = next_after
        if len(page) < 1000:
            break

    self._cache_snapshot_time = latest_snapshot
    self._cache_loaded_at = _utc_now()
    if appended:
        # Keep the operator state truthful without forcing a second full scan.
        try:
            await self.repo.upsert_historical_research_state(
                "XAU/USD",
                SNAPSHOT_INTERVAL,
                heartbeat_at=_utc_now().isoformat(),
                current_question=f"Historical memory appended {appended:,} new complete snapshots; {len(self._rows_cache):,} resident",
            )
        except Exception:
            pass
    return self._rows_cache


async def memory_bounded_history_load(self: ContinuousHistoricalResearchService) -> list[dict[str, Any]]:
    lock = getattr(self, "_memory_load_lock", None)
    if lock is None:
        self._memory_load_lock = asyncio.Lock()
        lock = self._memory_load_lock

    async with lock:
        learning_state = await self.repo.get_learning_state("XAU/USD", SNAPSHOT_INTERVAL) or {}
        latest_snapshot = as_utc(learning_state.get("last_snapshot_time"))

        if not self._rows_cache or latest_snapshot is None:
            return await _ORIGINAL_HISTORY_LOAD(self)

        # The snapshot history is immutable. If authority has not advanced,
        # there is no reason to rebuild after an arbitrary cache TTL.
        if self._cache_snapshot_time is not None and latest_snapshot == self._cache_snapshot_time:
            return self._rows_cache

        return await _append_new_complete_rows(self, latest_snapshot)


async def shared_autonomy_fetch(self: AutonomousLearningService, complete_only: bool = True) -> list[dict[str, Any]]:
    """Borrow the single resident historical list for complete-snapshot work."""
    service = _SHARED_HISTORY_REF() if _SHARED_HISTORY_REF is not None else None
    if complete_only and service is not None and not service._stop.is_set():
        return await service.load_complete_rows()
    return await _ORIGINAL_AUTONOMY_FETCH(self, complete_only=complete_only)


ContinuousHistoricalResearchService.__init__ = _patched_history_init
ContinuousHistoricalResearchService._load_rows = memory_bounded_history_load
AutonomousLearningService._fetch_all_snapshots = shared_autonomy_fetch


def runtime_status() -> dict[str, Any]:
    service = _SHARED_HISTORY_REF() if _SHARED_HISTORY_REF is not None else None
    return {
        "version": MEMORY_GUARD_VERSION,
        "shared_history_owner_registered": service is not None,
        "resident_rows": len(service._rows_cache) if service is not None else 0,
        "history_refresh_policy": "append_only_keyset",
        "autonomy_policy": "borrow_shared_complete_snapshot_cache",
    }
