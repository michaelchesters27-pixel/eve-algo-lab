from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

from app.services import strategy_evolution as strategy_evolution_module
from app.services.supabase_repo import SupabaseRepository


STRATEGY_SOURCE_PAGE_SIZE = 250
VALIDATION_SCAN_PAGE_SIZE = 200
VALIDATION_SCAN_ROW_CAP = 5000
EVOLUTION_LINEAGE_WINDOW = 50


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _content_range_total(content_range: str | None) -> int:
    if not content_range or "/" not in content_range:
        return 0
    try:
        return int(content_range.rsplit("/", 1)[1])
    except (TypeError, ValueError):
        return 0


async def progressive_list_strategy_source_research(
    self: SupabaseRepository,
    symbol: str,
    snapshot_interval: str,
    limit: int = STRATEGY_SOURCE_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Rotate Strategy Lab through the full eligible research pool.

    The old selector always returned the same highest-confidence page. Once every
    candidate shape for that page had been tried, generation numbers kept moving
    while duplicate candidate keys were ignored. This selector uses the current
    generator generation as a deterministic page cursor so later research findings
    are eventually reached without weakening any strategy acceptance gate.
    """

    safe_limit = max(1, min(500, int(limit)))
    encoded_symbol = quote(symbol, safe="")
    encoded_interval = quote(snapshot_interval, safe="")
    filters = (
        f"symbol=eq.{encoded_symbol}&snapshot_interval=eq.{encoded_interval}"
        "&status=eq.complete&result_status=in.(validated,promising)"
    )

    response = await self._request(
        "HEAD",
        f"historical_research_jobs?select=id&{filters}",
        headers={"Prefer": "count=exact"},
    )
    total = _content_range_total(response.headers.get("content-range"))
    if total <= 0:
        return []

    state = await self.get_strategy_lab_state(symbol, snapshot_interval) or {}
    generation = max(0, _number(state.get("generator_generation")))
    page_count = max(1, math.ceil(total / safe_limit))
    page_index = generation % page_count
    offset = page_index * safe_limit

    fields = (
        "id,job_key,symbol,snapshot_interval,question,test_definition,result_status,"
        "effect_size,confidence_score,stability_score,evidence"
    )
    query = (
        f"select={fields}&{filters}"
        "&order=confidence_score.desc.nullslast,id.asc"
        f"&limit={safe_limit}&offset={offset}"
    )
    rows = await self.select("historical_research_jobs", query)

    # If the pool changed between the HEAD count and the SELECT, recover cleanly
    # instead of leaving the factory idle for a cycle.
    if not rows and offset:
        rows = await self.select(
            "historical_research_jobs",
            (
                f"select={fields}&{filters}"
                "&order=confidence_score.desc.nullslast,id.asc"
                f"&limit={safe_limit}&offset=0"
            ),
        )
    return rows


async def _scan_unseen_validation_candidates(
    repo: SupabaseRepository,
    *,
    table: str,
    fields: str,
    filters: str,
    used_ids: set[str],
    source_kind: str,
    target: int,
    family: str | None = None,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    offset = 0

    while offset < VALIDATION_SCAN_ROW_CAP and len(found) < target:
        page = await repo.select(
            table,
            (
                f"select={fields}&{filters}"
                "&order=result_status.desc,profit_factor.desc.nullslast,expectancy_r.desc.nullslast,id.asc"
                f"&limit={VALIDATION_SCAN_PAGE_SIZE}&offset={offset}"
            ),
        )
        if not page:
            break

        for item in page:
            if str(item.get("id")) in used_ids:
                continue
            seed = {**item, "source_kind": source_kind}
            if family:
                seed["family"] = family
            found.append(seed)
            if len(found) >= target:
                break

        if len(page) < VALIDATION_SCAN_PAGE_SIZE:
            break
        offset += VALIDATION_SCAN_PAGE_SIZE

    return found


async def progressive_list_validation_seed_candidates(
    self: SupabaseRepository,
    symbol: str,
    snapshot_interval: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Find the next unvalidated survivor even when the top ranked page is used.

    Previously the database query fetched only the top 50 candidates and *then*
    removed candidates with an existing M1-validation job. If all top 50 had been
    used, lower-ranked eligible survivors were invisible. This version paginates
    past used rows before deciding that the queue is empty.
    """

    safe_limit = max(1, min(50, int(limit)))
    encoded_symbol = quote(symbol, safe="")
    encoded_interval = quote(snapshot_interval, safe="")

    existing = await self.select(
        "strategy_validation_jobs",
        (
            "select=source_kind,source_strategy_candidate_id,source_evolution_candidate_id"
            f"&symbol=eq.{encoded_symbol}&snapshot_interval=eq.{encoded_interval}"
        ),
    )
    used_strategy = {
        str(item.get("source_strategy_candidate_id"))
        for item in existing
        if item.get("source_strategy_candidate_id")
    }
    used_evolution = {
        str(item.get("source_evolution_candidate_id"))
        for item in existing
        if item.get("source_evolution_candidate_id")
    }

    evolution_fields = (
        "id,lineage_id,symbol,snapshot_interval,name,rules,result_status,profit_factor,"
        "expectancy_r,max_drawdown_r,trades_total,metrics,evidence,finished_at"
    )
    evolution_filters = (
        f"symbol=eq.{encoded_symbol}&snapshot_interval=eq.{encoded_interval}"
        "&status=eq.complete&result_status=in.(champion,elite)"
        "&selection_passed=eq.true&locked_test_passed=eq.true"
    )
    strategy_fields = (
        "id,symbol,snapshot_interval,name,family,rules,result_status,profit_factor,"
        "expectancy_r,max_drawdown_r,trades_total,metrics,evidence,finished_at"
    )
    strategy_filters = (
        f"symbol=eq.{encoded_symbol}&snapshot_interval=eq.{encoded_interval}"
        "&status=eq.complete&result_status=in.(elite,validated)&trades_total=gte.50"
    )

    evolution = await _scan_unseen_validation_candidates(
        self,
        table="strategy_evolution_candidates",
        fields=evolution_fields,
        filters=evolution_filters,
        used_ids=used_evolution,
        source_kind="evolution",
        family="evolved_strategy",
        target=safe_limit,
    )
    strategy = await _scan_unseen_validation_candidates(
        self,
        table="strategy_candidates",
        fields=strategy_fields,
        filters=strategy_filters,
        used_ids=used_strategy,
        source_kind="strategy",
        target=safe_limit,
    )

    seeds = [*evolution, *strategy]
    rank = {"elite": 4, "champion": 3, "validated": 2}
    seeds.sort(
        key=lambda item: (
            rank.get(str(item.get("result_status")), 0),
            _float(item.get("profit_factor")),
            _float(item.get("expectancy_r")),
        ),
        reverse=True,
    )
    return seeds[:safe_limit]


def apply_queue_progression() -> None:
    """Install queue selectors before app.main creates the service objects."""

    if getattr(SupabaseRepository, "_eve_queue_progression_applied", False):
        return

    SupabaseRepository.list_strategy_source_research = progressive_list_strategy_source_research
    SupabaseRepository.list_validation_seed_candidates = progressive_list_validation_seed_candidates

    # The repository already caps evolution seeds at 50. Matching that cap here
    # lets the engine use every seeded active lineage instead of permanently
    # ignoring lineages ranked below the old top-20 window.
    strategy_evolution_module.MAX_ACTIVE_LINEAGES = EVOLUTION_LINEAGE_WINDOW

    setattr(SupabaseRepository, "_eve_queue_progression_applied", True)
