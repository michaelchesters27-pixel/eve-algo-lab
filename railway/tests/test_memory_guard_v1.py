from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import weakref

import pytest

from app.services import memory_guard_v1 as guard
from app.services.autonomy import AutonomousLearningService
from app.services.historical_research import ContinuousHistoricalResearchService


def _row(timestamp: datetime, close: float) -> dict:
    return {"candle_time": timestamp.isoformat(), "close": close, "outcome_complete": True}


class FakeRepo:
    def __init__(self, latest: datetime, pages: list[list[dict]] | None = None) -> None:
        self.latest = latest
        self.pages = list(pages or [])
        self.fetch_calls: list[dict] = []
        self.state_updates: list[dict] = []

    async def get_learning_state(self, symbol: str, interval: str) -> dict:
        return {"last_snapshot_time": self.latest.isoformat()}

    async def fetch_learning_snapshots_page(self, symbol: str, interval: str, **kwargs):
        self.fetch_calls.append(dict(kwargs))
        return self.pages.pop(0) if self.pages else []

    async def upsert_historical_research_state(self, symbol: str, interval: str, **kwargs):
        self.state_updates.append(dict(kwargs))
        return {}


def _service(repo: FakeRepo, rows: list[dict], snapshot_time: datetime) -> ContinuousHistoricalResearchService:
    service = ContinuousHistoricalResearchService.__new__(ContinuousHistoricalResearchService)
    service.repo = repo
    service._stop = asyncio.Event()
    service._wake = asyncio.Event()
    service._rows_cache = rows
    service._cache_snapshot_time = snapshot_time
    service._cache_loaded_at = snapshot_time
    service._memory_load_lock = asyncio.Lock()
    return service


@pytest.mark.asyncio
async def test_unchanged_snapshot_authority_never_reloads_full_history() -> None:
    t0 = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)
    rows = [_row(t0 - timedelta(minutes=15), 100.0), _row(t0, 101.0)]
    repo = FakeRepo(t0)
    service = _service(repo, rows, t0)

    result = await guard.memory_bounded_history_load(service)

    assert result is rows
    assert repo.fetch_calls == []


@pytest.mark.asyncio
async def test_new_authority_appends_only_tail_to_same_list_object() -> None:
    t0 = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=15)
    t2 = t1 + timedelta(minutes=15)
    resident = [_row(t0 - timedelta(minutes=15), 100.0), _row(t0, 101.0)]
    repo = FakeRepo(t2, pages=[[_row(t1, 102.0), _row(t2, 103.0)]])
    service = _service(repo, resident, t0)

    result = await guard.memory_bounded_history_load(service)

    assert result is resident
    assert len(result) == 4
    assert result[-1]["candle_time"] == t2.isoformat()
    assert len(repo.fetch_calls) == 1
    assert repo.fetch_calls[0]["after"] == t0.isoformat()
    assert service._cache_snapshot_time == t2


@pytest.mark.asyncio
async def test_autonomy_borrows_shared_history_instead_of_materialising_copy() -> None:
    shared = [{"candle_time": "2026-08-21T06:00:00+00:00"}]

    class Owner:
        def __init__(self) -> None:
            self._stop = asyncio.Event()
            self.calls = 0

        async def load_complete_rows(self):
            self.calls += 1
            return shared

    owner = Owner()
    guard._SHARED_HISTORY_REF = weakref.ref(owner)
    autonomy = AutonomousLearningService.__new__(AutonomousLearningService)

    result = await guard.shared_autonomy_fetch(autonomy, complete_only=True)

    assert result is shared
    assert owner.calls == 1


def test_memory_guard_runtime_policy_is_explicit() -> None:
    status = guard.runtime_status()
    assert status["history_refresh_policy"] == "append_only_keyset"
    assert status["autonomy_policy"] == "borrow_shared_complete_snapshot_cache"
