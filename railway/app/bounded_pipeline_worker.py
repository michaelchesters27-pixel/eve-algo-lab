from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from app.services.autonomy import AutonomousLearningService
from app.services.high_resolution_validation import HighResolutionValidationService
from app.services.historical_research import ContinuousHistoricalResearchService
from app.services.learning import SNAPSHOT_INTERVAL
from app.services.mt5_generator import MT5GeneratorService
from app.services.strategy_evolution import StrategyEvolutionService
from app.services.strategy_lab import StrategyLabService
from app.services.supabase_repo import SupabaseRepository
from app.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _summary(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int, float)):
        return value
    if isinstance(value, dict):
        keep = (
            "status", "result_status", "sample_count", "rows_scanned",
            "trades_total", "profit_factor", "expectancy_r", "message",
        )
        return {key: value.get(key) for key in keep if key in value}
    return str(type(value).__name__)


async def _stage(
    name: str,
    operation: Callable[[], Awaitable[Any]],
    repo: SupabaseRepository,
) -> dict[str, Any]:
    try:
        result = await operation()
        logger.info("Bounded Algo stage %s complete: %s", name, _summary(result))
        return {"ok": True, "result": _summary(result)}
    except Exception as exc:
        logger.exception("Bounded Algo stage %s failed", name)
        try:
            await repo.log_event(
                "error",
                "bounded-pipeline",
                f"Bounded pipeline stage {name} failed safely",
                {"stage": name, "error": str(exc)[:2000]},
            )
        except Exception:
            logger.exception("Could not persist bounded-pipeline failure event")
        return {"ok": False, "error": str(exc)[:2000]}


async def run_once() -> dict[str, Any]:
    settings = get_settings()
    repo = SupabaseRepository(
        settings.supabase_url,
        settings.supabase_service_role_key,
        settings.request_timeout_seconds,
    )

    autonomy = AutonomousLearningService(settings, repo)
    historical = ContinuousHistoricalResearchService(settings, repo)

    # Within one disposable child process the heavy snapshot list may be shared
    # between stages. The process then exits, so the heap cannot remain resident.
    strategy = StrategyLabService(settings, repo, historical.load_complete_rows)
    evolution = StrategyEvolutionService(settings, repo, historical.load_complete_rows)
    validation = HighResolutionValidationService(settings, repo, historical.load_complete_rows)
    mt5 = MT5GeneratorService(settings, repo)

    results: dict[str, Any] = {}

    async def incremental_learning() -> dict[str, Any]:
        queued = await autonomy._queue_incremental_learning_if_needed()
        graded = await autonomy._grade_pending_predictions()
        created = await autonomy._create_latest_predictions()
        return {
            "status": "complete",
            "learning_queued": queued,
            "predictions_graded": graded,
            "predictions_created": created,
        }

    async def historical_stage() -> dict[str, Any]:
        await repo.reset_stale_historical_research_jobs()
        await historical._ensure_queue()
        job = await repo.claim_next_historical_research_job(historical.worker_id)
        if not job:
            return {"status": "idle", "message": "No historical research job queued"}
        await historical._execute_job(job)
        return {"status": "complete", "message": str(job.get("question") or "Historical research completed")}

    async def strategy_stage() -> dict[str, Any]:
        await strategy._ensure_queue()
        candidate = await repo.claim_next_strategy_candidate(strategy.worker_id)
        if not candidate:
            return {"status": "idle", "message": "No Strategy Lab candidate queued"}
        await strategy._execute_candidate(candidate)
        return {"status": "complete", "message": str(candidate.get("name") or "Strategy candidate completed")}

    async def evolution_stage() -> dict[str, Any]:
        await evolution._ensure_lineages()
        await evolution._ensure_queue()
        child = await repo.claim_next_evolution_candidate(evolution.worker_id)
        if not child:
            return {"status": "idle", "message": "No Strategy Evolution candidate queued"}
        await evolution._execute_child(child)
        return {"status": "complete", "message": str(child.get("name") or "Evolution candidate completed")}

    async def validation_stage() -> dict[str, Any]:
        await repo.reset_stale_validation_jobs()
        await validation._ensure_queue()
        job = await repo.claim_next_validation_job(validation.worker_id)
        if not job:
            return {"status": "idle", "message": "No high-resolution validation job queued"}
        await validation._execute(job)
        return {"status": "complete", "message": str(job.get("name") or "M1 validation completed")}

    async def mt5_stage() -> dict[str, Any]:
        await repo.reset_stale_mt5_generation_jobs()
        await mt5._ensure_queue()
        job = await repo.claim_next_mt5_generation_job(mt5.worker_id)
        if not job:
            return {"status": "idle", "message": "No MT5 generation job queued"}
        await mt5._execute(job)
        return {"status": "complete", "message": str(job.get("name") or "MT5 package generated")}

    try:
        results["learning"] = await _stage("learning", incremental_learning, repo)
        results["historical_research"] = await _stage("historical_research", historical_stage, repo)
        results["strategy_lab"] = await _stage("strategy_lab", strategy_stage, repo)
        results["strategy_evolution"] = await _stage("strategy_evolution", evolution_stage, repo)
        results["m1_validation"] = await _stage("m1_validation", validation_stage, repo)
        results["mt5_generation"] = await _stage("mt5_generation", mt5_stage, repo)

        succeeded = sum(1 for item in results.values() if item.get("ok"))
        failed = len(results) - succeeded
        try:
            await repo.log_event(
                "success" if failed == 0 else "warning",
                "bounded-pipeline",
                f"Bounded autonomous pipeline finished: {succeeded} stages succeeded, {failed} failed",
                {"stages": results},
            )
        except Exception:
            logger.exception("Could not persist bounded-pipeline completion event")
        return {"ok": failed == 0, "succeeded": succeeded, "failed": failed, "stages": results}
    finally:
        await repo.close()


if __name__ == "__main__":
    result = asyncio.run(run_once())
    print(json.dumps(result, sort_keys=True, default=str))
