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
    MetricsPreviewRequest,
)
from app.services.backtests import BacktestService
from app.services.ingestion import IngestionService, historical_backfill_complete
from app.services.supabase_repo import SupabaseRepository
from app.services.twelve_data import INTERVAL_SECONDS, TwelveDataClient
from app.settings import Settings, get_settings

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
background_tasks: list[asyncio.Task[Any]] = []


@asynccontextmanager
async def lifespan(_: FastAPI):
    await repo.fail_interrupted_backtests()
    await repo.log_event("info", "railway", "EVE Algo Lab Railway service started", {"version": "1.2.0"})
    background_tasks.extend(
        [
            asyncio.create_task(ingestion.worker_loop(), name="ingestion-worker"),
            asyncio.create_task(ingestion.auto_sync_loop(), name="automatic-sync"),
        ]
    )
    yield
    await ingestion.stop()
    for task in background_tasks:
        task.cancel()
    for task in list(backtests.tasks.values()):
        task.cancel()
    await asyncio.gather(*background_tasks, *list(backtests.tasks.values()), return_exceptions=True)
    await twelve.close()
    await repo.close()


app = FastAPI(
    title="EVE Algo Lab API",
    version="1.2.0",
    description="Permanent market memory and an exact-rule M5 backtester for EVE Fixed Ladder v2.61.",
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
    return {"name": settings.app_name, "status": "online", "version": "1.2.0"}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "1.2.0",
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
    dashboard["version"] = "1.2.0"
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


@app.post("/api/backtests/fixed-ladder-v2-61", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_fixed_ladder_backtest(request: FixedLadderBacktestRequest) -> ApiEnvelope:
    state = await repo.get_state(request.symbol, request.interval)
    if not state_is_historically_ready(state, request.interval):
        raise HTTPException(status_code=409, detail="Market Memory must be complete before backtesting")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")

    strategy_version_id = await backtests.ensure_strategy_version()
    settings_payload = request.model_dump(mode="json")
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": request.name,
            "symbol": request.symbol,
            "interval": request.interval,
            "resolution": "candle",
            "status": "queued",
            "date_from": request.date_from.isoformat() if request.date_from else state.get("oldest_stored"),
            "date_to": request.date_to.isoformat() if request.date_to else state.get("latest_stored"),
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "M5 candle-path approximation",
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start(run_id, settings_payload)
    return ApiEnvelope(data={"id": run_id, "status": "queued"}, message="Fixed Ladder v2.61 backtest started")


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
