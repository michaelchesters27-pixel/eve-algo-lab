from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from app.backtesting.metrics import calculate_metrics
from app.models.schemas import ApiEnvelope, JobRequest, JobResponse, MetricsPreviewRequest
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
background_tasks: list[asyncio.Task[Any]] = []


@asynccontextmanager
async def lifespan(_: FastAPI):
    await repo.log_event("info", "railway", "EVE Algo Lab Railway service started", {"version": "1.1.0"})
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
    await asyncio.gather(*background_tasks, return_exceptions=True)
    await twelve.close()
    await repo.close()


app = FastAPI(
    title="EVE Algo Lab API",
    version="1.1.0",
    description="Resumable historical market memory, data-quality controls and backtest metrics.",
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
    return {"name": settings.app_name, "status": "online", "version": "1.1.0"}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "1.1.0",
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
        # Repair the misleading v1 state where a live sync set progress to 100% before history existed.
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
    dashboard["version"] = "1.1.0"
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


@app.post("/api/backtests/metrics-preview", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def metrics_preview(request: MetricsPreviewRequest) -> ApiEnvelope:
    metrics = calculate_metrics(request.net_pnls, request.starting_balance)
    return ApiEnvelope(data=metrics.as_dict())
