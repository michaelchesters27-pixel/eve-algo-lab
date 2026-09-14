from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.services import strategy_evolution as strategy_evolution_module
from app.services.queue_progression import (
    EVOLUTION_LINEAGE_WINDOW,
    apply_queue_progression,
    progressive_list_strategy_source_research,
    progressive_list_validation_seed_candidates,
)
from app.services.supabase_repo import SupabaseRepository


class StrategySourceRepo:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def _request(self, method: str, path: str, **_: Any) -> Any:
        assert method == "HEAD"
        assert "historical_research_jobs" in path
        return SimpleNamespace(headers={"content-range": "0-249/600"})

    async def get_strategy_lab_state(self, _symbol: str, _interval: str) -> dict[str, Any]:
        return {"generator_generation": 1}

    async def select(self, table: str, query: str) -> list[dict[str, Any]]:
        assert table == "historical_research_jobs"
        self.queries.append(query)
        return [{"id": "research-page-2", "result_status": "validated"}]


def test_strategy_source_selector_rotates_beyond_first_page() -> None:
    repo = StrategySourceRepo()
    rows = asyncio.run(
        progressive_list_strategy_source_research(repo, "XAU/USD", "5min", limit=250)  # type: ignore[arg-type]
    )

    assert rows[0]["id"] == "research-page-2"
    assert any("offset=250" in query for query in repo.queries)


class ValidationRepo:
    def __init__(self) -> None:
        self.candidate_queries: list[str] = []

    async def select(self, table: str, query: str) -> list[dict[str, Any]]:
        if table == "strategy_validation_jobs":
            return [
                {"source_evolution_candidate_id": f"e{i}", "source_strategy_candidate_id": None}
                for i in range(200)
            ]

        if table == "strategy_evolution_candidates":
            self.candidate_queries.append(query)
            if "offset=0" in query:
                return [
                    {
                        "id": f"e{i}",
                        "result_status": "champion",
                        "profit_factor": 1.50,
                        "expectancy_r": 0.10,
                    }
                    for i in range(200)
                ]
            if "offset=200" in query:
                return [
                    {
                        "id": "e200",
                        "result_status": "champion",
                        "profit_factor": 1.40,
                        "expectancy_r": 0.08,
                    }
                ]
            return []

        if table == "strategy_candidates":
            return []

        raise AssertionError(f"Unexpected table: {table}")


def test_validation_selector_pages_past_used_top_rows() -> None:
    repo = ValidationRepo()
    rows = asyncio.run(
        progressive_list_validation_seed_candidates(repo, "XAU/USD", "5min", limit=1)  # type: ignore[arg-type]
    )

    assert [row["id"] for row in rows] == ["e200"]
    assert rows[0]["source_kind"] == "evolution"
    assert any("offset=200" in query for query in repo.candidate_queries)


def test_runtime_patch_expands_evolution_window_and_replaces_selectors() -> None:
    original_source = SupabaseRepository.list_strategy_source_research
    original_validation = SupabaseRepository.list_validation_seed_candidates
    original_window = strategy_evolution_module.MAX_ACTIVE_LINEAGES
    had_flag = hasattr(SupabaseRepository, "_eve_queue_progression_applied")
    original_flag = getattr(SupabaseRepository, "_eve_queue_progression_applied", None)

    try:
        if had_flag:
            delattr(SupabaseRepository, "_eve_queue_progression_applied")
        apply_queue_progression()

        assert SupabaseRepository.list_strategy_source_research is progressive_list_strategy_source_research
        assert SupabaseRepository.list_validation_seed_candidates is progressive_list_validation_seed_candidates
        assert strategy_evolution_module.MAX_ACTIVE_LINEAGES == EVOLUTION_LINEAGE_WINDOW == 50
    finally:
        SupabaseRepository.list_strategy_source_research = original_source
        SupabaseRepository.list_validation_seed_candidates = original_validation
        strategy_evolution_module.MAX_ACTIVE_LINEAGES = original_window
        if hasattr(SupabaseRepository, "_eve_queue_progression_applied"):
            delattr(SupabaseRepository, "_eve_queue_progression_applied")
        if had_flag:
            setattr(SupabaseRepository, "_eve_queue_progression_applied", original_flag)
