from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from app.backtesting.metrics import calculate_metrics
from app.models.schemas import (
    ApiEnvelope,
    FixedLadderBacktestRequest,
    JobRequest,
    JobResponse,
    LearningBuildRequest,
    MetricsPreviewRequest,
)
from app.services.autonomy import AutonomousLearningService
from app.services.backtests import BacktestService
from app.services.ingestion import IngestionService, historical_backfill_complete
from app.services.historical_research import ContinuousHistoricalResearchService
from app.services.learning import LearningService, SNAPSHOT_INTERVAL
from app.services.strategy_lab import StrategyLabService
from app.services.strategy_evolution import StrategyEvolutionService
from app.services.supabase_repo import SupabaseRepository
from app.services.twelve_data import INTERVAL_SECONDS, TwelveDataClient
from app.settings import Settings, get_settings

APP_VERSION = "2.2"

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

repo = SupabaseRepository(settings.supabase_url, settings.supabase_service_role_key, settings.request_timeout_seconds)
twelve = TwelveDataClient(
    settings.twelve_data_api_key,
    settings.twelve_data_base_url,
    settings.request_timeout_seconds,
    settings.max_http_retries,
)
ingestion = IngestionService(settings, repo, twelve)
backtests = BacktestService(repo)
learning = LearningService(repo)
autonomy = AutonomousLearningService(settings, repo)
historical_research = ContinuousHistoricalResearchService(settings, repo)
strategy_lab = StrategyLabService(settings, repo, historical_research.load_complete_rows)
strategy_evolution = StrategyEvolutionService(settings, repo, historical_research.load_complete_rows)
background_tasks: list[asyncio.Task[Any]] = []


@asynccontextmanager
async def lifespan(_: FastAPI):
    await repo.fail_interrupted_backtests()
    await repo.log_event("info", "railway", "EVE Algo Lab Railway service started", {"version": APP_VERSION})
    background_tasks.append(asyncio.create_task(ingestion.worker_loop(), name="ingestion-worker"))
    background_tasks.append(asyncio.create_task(learning.worker_loop(), name="learning-worker"))
    background_tasks.append(asyncio.create_task(autonomy.loop(), name="autonomous-learning-engine"))
    background_tasks.append(asyncio.create_task(historical_research.loop(), name="continuous-historical-research"))
    background_tasks.append(asyncio.create_task(strategy_lab.loop(), name="strategy-idea-factory"))
    background_tasks.append(asyncio.create_task(strategy_evolution.loop(), name="strategy-evolution-engine"))
    for sync_index, interval in enumerate(settings.auto_sync_interval_list):
        if interval not in INTERVAL_SECONDS:
            logger.warning("Skipping unsupported AUTO_SYNC_INTERVALS value: %s", interval)
            continue
        background_tasks.append(
            asyncio.create_task(ingestion.auto_sync_loop(interval, sync_index), name=f"automatic-sync-{interval}")
        )
    yield
    await ingestion.stop()
    await learning.stop()
    await autonomy.stop()
    await historical_research.stop()
    await strategy_lab.stop()
    await strategy_evolution.stop()
    for task in background_tasks:
        task.cancel()
    for task in list(backtests.tasks.values()):
        task.cancel()
    await asyncio.gather(*background_tasks, *list(backtests.tasks.values()), return_exceptions=True)
    await twelve.close()
    await repo.close()


app = FastAPI(
    title="EVE Algo Lab API",
    version=APP_VERSION,
    description="Permanent multi-timeframe XAU/USD memory with autonomous learning, continuous historical research, an autonomous Strategy Idea Factory, controlled strategy evolution and high-resolution backtesting.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-EVE-ADMIN-TOKEN"],
)


def require_admin(x_eve_admin_token: Annotated[str | None, Header()] = None) -> None:
    if x_eve_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect admin token")


def state_is_historically_ready(state: dict[str, Any] | None, interval: str) -> bool:
    interval_seconds = INTERVAL_SECONDS.get(interval)
    return bool(interval_seconds and historical_backfill_complete(state, interval_seconds))


@app.get("/")
async def root() -> dict[str, Any]:
    return {"name": settings.app_name, "status": "online", "version": APP_VERSION}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": APP_VERSION,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status", response_model=ApiEnvelope)
async def market_status(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    interval: str = Query(default="5min"),
) -> ApiEnvelope:
    if interval not in INTERVAL_SECONDS:
        raise HTTPException(status_code=422, detail=f"Unsupported interval: {interval}")

    dashboard = await repo.dashboard(symbol, interval)
    state = dict(dashboard.get("state") or {})
    backfill_job = await repo.get_latest_job(symbol, interval, "backfill")
    historical_ready = state_is_historically_ready(state, interval)

    active_backfill = bool(backfill_job and backfill_job.get("status") in {"queued", "running"})
    if historical_ready:
        display_status = "complete"
        historical_progress = 100.0
    elif active_backfill:
        display_status = "downloading" if backfill_job.get("status") == "running" else "queued"
        historical_progress = float(backfill_job.get("progress_percent") or state.get("progress_percent") or 0)
    elif state.get("status") in {"paused", "error"}:
        display_status = state["status"]
        historical_progress = float(state.get("progress_percent") or 0)
    else:
        display_status = "not_started"
        historical_progress = 0.0

    state["status"] = display_status
    state["progress_percent"] = historical_progress
    state["historical_complete"] = historical_ready
    dashboard["state"] = state
    dashboard["backfill_job"] = backfill_job or {}
    dashboard["historical_ready"] = historical_ready
    dashboard["historical_progress_percent"] = historical_progress
    dashboard["service"] = "online"
    dashboard["symbol"] = symbol
    dashboard["interval"] = interval
    dashboard["version"] = APP_VERSION
    dashboard["latest_backtest"] = (await repo.list_backtest_runs(limit=1) or [{}])[0]
    return ApiEnvelope(data=dashboard)


@app.get("/api/jobs/{job_id}", response_model=ApiEnvelope)
async def get_job(job_id: str) -> ApiEnvelope:
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ApiEnvelope(data=job)


async def enqueue_unique(job_type: str, request: JobRequest) -> JobResponse:
    if request.interval not in INTERVAL_SECONDS:
        raise HTTPException(status_code=422, detail=f"Unsupported interval: {request.interval}")

    if job_type == "backfill" and not request.force_restart:
        state = await repo.get_state(request.symbol, request.interval)
        if state_is_historically_ready(state, request.interval):
            raise HTTPException(status_code=409, detail="Historical database is already complete")

    if await repo.has_active_job(job_type, request.symbol, request.interval):
        raise HTTPException(status_code=409, detail=f"A {job_type} job is already queued or running")

    job = await repo.create_job(
        job_type,
        request.symbol,
        request.interval,
        {"force_restart": request.force_restart},
    )
    if job_type == "backfill":
        await repo.upsert_state(request.symbol, request.interval, status="queued", last_error=None)
    return JobResponse(id=str(job["id"]), status=job["status"], message=job["message"])


@app.post("/api/jobs/backfill", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_backfill(request: JobRequest) -> ApiEnvelope:
    result = await enqueue_unique("backfill", request)
    return ApiEnvelope(data=result.model_dump(), message="Historical download queued")


@app.post("/api/jobs/sync", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_sync(request: JobRequest) -> ApiEnvelope:
    result = await enqueue_unique("sync_latest", request)
    return ApiEnvelope(data=result.model_dump(), message="Latest-candle sync queued")


@app.post("/api/jobs/gap-scan", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_gap_scan(request: JobRequest) -> ApiEnvelope:
    result = await enqueue_unique("gap_scan", request)
    return ApiEnvelope(data=result.model_dump(), message="Gap scan queued")


@app.post("/api/jobs/{job_id}/cancel", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def cancel_job(job_id: str) -> ApiEnvelope:
    job = await repo.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=409, detail="Job is no longer queued or running")
    return ApiEnvelope(data=job, message="Pause requested. The saved cursor will be used when you resume.")


@app.get("/api/learning/status", response_model=ApiEnvelope)
async def learning_status(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
) -> ApiEnvelope:
    dashboard = await repo.learning_dashboard(symbol, SNAPSHOT_INTERVAL)
    dashboard["service"] = "online"
    dashboard["version"] = APP_VERSION
    dashboard["snapshot_interval"] = SNAPSHOT_INTERVAL
    dashboard["historical_research"] = await repo.historical_research_dashboard(symbol, SNAPSHOT_INTERVAL)
    return ApiEnvelope(data=dashboard)


@app.get("/api/learning/runs", response_model=ApiEnvelope)
async def list_learning_runs(limit: int = Query(default=20, ge=1, le=100)) -> ApiEnvelope:
    return ApiEnvelope(data=await repo.list_learning_runs(limit))


@app.post("/api/learning/build", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_learning_build(request: LearningBuildRequest) -> ApiEnvelope:
    if await repo.has_active_learning_run(request.symbol, SNAPSHOT_INTERVAL):
        raise HTTPException(status_code=409, detail="A learning build is already queued or running")

    required = {
        "5min": "M5 Market Memory",
        "1day": "D1 Market Memory",
    }
    for interval, label in required.items():
        state = await repo.get_state(request.symbol, interval)
        if not state_is_historically_ready(state, interval):
            raise HTTPException(status_code=409, detail=f"{label} must be complete before EVE can build its learning foundation")

    run = await repo.create_learning_run(
        {
            "symbol": request.symbol,
            "source_interval": "5min",
            "snapshot_interval": SNAPSHOT_INTERVAL,
            "full_rebuild": request.full_rebuild,
            "message": "Waiting for Railway learning worker",
        }
    )
    await repo.upsert_learning_state(
        request.symbol,
        SNAPSHOT_INTERVAL,
        status="queued",
        last_run_id=str(run["id"]),
        last_error=None,
    )
    message = "Full learning rebuild queued" if request.full_rebuild else "Learning foundation update queued"
    return ApiEnvelope(data={"id": str(run["id"]), "status": run["status"]}, message=message)


@app.post("/api/learning/runs/{run_id}/cancel", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def cancel_learning_run(run_id: str) -> ApiEnvelope:
    run = await repo.cancel_learning_run(run_id)
    if not run:
        raise HTTPException(status_code=409, detail="Learning build is no longer queued or running")
    return ApiEnvelope(data=run, message="Learning build cancellation requested")


@app.post("/api/autonomy/run", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def run_autonomous_cycle() -> ApiEnvelope:
    await autonomy.request_cycle()
    return ApiEnvelope(
        data={"status": "requested"},
        message="Autonomous learning cycle requested. Railway will run it in the background.",
    )


@app.get("/api/research/results", response_model=ApiEnvelope)
async def list_historical_research_results(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    result_status: str = Query(default="all", pattern="^(all|validated|promising|rejected)$"),
    order: str = Query(default="confidence", pattern="^(confidence|stability|sample|recent|effect)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiEnvelope:
    items = await repo.list_historical_research_results(
        symbol, SNAPSHOT_INTERVAL, result_status=result_status, order=order, limit=limit
    )
    return ApiEnvelope(data={"items": items, "result_status": result_status, "order": order})


@app.post("/api/research/wake", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def wake_historical_research() -> ApiEnvelope:
    await historical_research.request_wake()
    return ApiEnvelope(
        data={"status": "requested"},
        message="Historical research worker wake requested. Normal 24/7 research never requires this button.",
    )


@app.get("/api/strategy-lab/status", response_model=ApiEnvelope)
async def strategy_lab_status(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
) -> ApiEnvelope:
    dashboard = await repo.strategy_lab_dashboard(symbol, SNAPSHOT_INTERVAL)
    dashboard["service"] = "online"
    dashboard["version"] = APP_VERSION
    return ApiEnvelope(data=dashboard)


@app.get("/api/strategy-lab/candidates", response_model=ApiEnvelope)
async def list_strategy_candidates(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    result_status: str = Query(default="all", pattern="^(all|elite|validated|promising|rejected)$"),
    order: str = Query(default="profit_factor", pattern="^(profit_factor|expectancy|drawdown|trades|recent)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiEnvelope:
    items = await repo.list_strategy_candidates(
        symbol, SNAPSHOT_INTERVAL, result_status=result_status, order=order, limit=limit
    )
    return ApiEnvelope(data={"items": items, "result_status": result_status, "order": order})


@app.post("/api/strategy-lab/wake", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def wake_strategy_lab() -> ApiEnvelope:
    await strategy_lab.request_wake()
    return ApiEnvelope(
        data={"status": "requested"},
        message="Strategy Lab wake requested. Normal strategy generation and testing runs automatically.",
    )


@app.get("/api/evolution/status", response_model=ApiEnvelope)
async def strategy_evolution_status(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
) -> ApiEnvelope:
    dashboard = await repo.strategy_evolution_dashboard(symbol, SNAPSHOT_INTERVAL)
    dashboard["service"] = "online"
    dashboard["version"] = APP_VERSION
    return ApiEnvelope(data=dashboard)


@app.get("/api/evolution/candidates", response_model=ApiEnvelope)
async def list_evolution_candidates(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    result_status: str = Query(default="all", pattern="^(all|elite|champion|development|rejected)$"),
    order: str = Query(default="validation_improvement", pattern="^(validation_improvement|profit_factor|expectancy|drawdown|generation|recent)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiEnvelope:
    items = await repo.list_evolution_candidates(
        symbol, SNAPSHOT_INTERVAL, result_status=result_status, order=order, limit=limit
    )
    return ApiEnvelope(data={"items": items, "result_status": result_status, "order": order})


@app.post("/api/evolution/wake", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def wake_strategy_evolution() -> ApiEnvelope:
    await strategy_evolution.request_wake()
    return ApiEnvelope(
        data={"status": "requested"},
        message="Strategy Evolution wake requested. Normal mutation and selection already run automatically.",
    )


@app.post("/api/backtests/fixed-ladder-v2-61", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_fixed_ladder_backtest(request: FixedLadderBacktestRequest) -> ApiEnvelope:
    data_interval = "1min" if request.resolution == "m1_replay" else "5min"
    state = await repo.get_state(request.symbol, data_interval)
    if not state_is_historically_ready(state, data_interval):
        label = "M1 Market Memory" if data_interval == "1min" else "M5 Market Memory"
        raise HTTPException(status_code=409, detail=f"{label} must be complete before this backtest can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")

    strategy_version_id = await backtests.ensure_strategy_version()
    settings_payload = request.model_dump(mode="json")
    accuracy = "M1 high-resolution candle replay" if request.resolution == "m1_replay" else "M5 candle-path approximation"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": request.name,
            "symbol": request.symbol,
            "interval": request.interval,
            "resolution": request.resolution,
            "status": "queued",
            "date_from": request.date_from.isoformat() if request.date_from else state.get("oldest_stored"),
            "date_to": request.date_to.isoformat() if request.date_to else state.get("latest_stored"),
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": accuracy,
                "input_interval": data_interval,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start(run_id, settings_payload)
    label = "M1 replay" if request.resolution == "m1_replay" else "M5 approximation"
    return ApiEnvelope(data={"id": run_id, "status": "queued"}, message=f"Fixed Ladder v2.61 {label} started")


@app.get("/api/backtests", response_model=ApiEnvelope)
async def list_backtests(limit: int = Query(default=20, ge=1, le=100)) -> ApiEnvelope:
    return ApiEnvelope(data=await repo.list_backtest_runs(limit))


@app.get("/api/backtests/{run_id}", response_model=ApiEnvelope)
async def get_backtest(run_id: str) -> ApiEnvelope:
    run = await repo.get_backtest_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest not found")
    baskets = await repo.list_backtest_baskets(run_id, 100) if run.get("status") == "complete" else []
    trades = await repo.list_backtest_trades(run_id, 100) if run.get("status") == "complete" else []
    return ApiEnvelope(data={"run": run, "baskets": baskets, "trades": trades})


@app.post("/api/backtests/{run_id}/cancel", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def cancel_backtest(run_id: str) -> ApiEnvelope:
    run = await repo.get_backtest_run(run_id)
    if not run or run.get("status") not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Backtest is no longer running")
    await backtests.cancel(run_id)
    return ApiEnvelope(data={"id": run_id, "status": "cancelled"}, message="Backtest cancellation requested")


@app.post("/api/backtests/metrics-preview", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def metrics_preview(request: MetricsPreviewRequest) -> ApiEnvelope:
    metrics = calculate_metrics(request.net_pnls, request.starting_balance)
    return ApiEnvelope(data=metrics.as_dict())
