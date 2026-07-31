from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from app.backtesting.metrics import calculate_metrics
from app.models.schemas import ApiEnvelope, JobRequest, JobResponse, MetricsPreviewRequest
from app.services.ingestion import IngestionService
from app.services.supabase_repo import SupabaseRepository
from app.services.twelve_data import TwelveDataClient
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
background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(_: FastAPI):
    await repo.log_event("info", "railway", "EVE Algo Lab Railway service started")
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
    version="1.0.0",
    description="Historical market-data foundation, data-quality controls and backtest metrics.",
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


@app.get("/")
async def root() -> dict:
    return {"name": settings.app_name, "status": "online", "version": "1.0.0"}


@app.get("/health")
async def health() -> dict:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status", response_model=ApiEnvelope)
async def market_status(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    interval: str = Query(default="5min"),
) -> ApiEnvelope:
    dashboard = await repo.dashboard(symbol, interval)
    return ApiEnvelope(data={"service": "online", "symbol": symbol, "interval": interval, **dashboard})


@app.get("/api/jobs/{job_id}", response_model=ApiEnvelope)
async def get_job(job_id: str) -> ApiEnvelope:
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ApiEnvelope(data=job)


async def enqueue_unique(job_type: str, request: JobRequest) -> JobResponse:
    if job_type == "backfill" and not request.force_restart:
        state = await repo.get_state(request.symbol, request.interval)
        if state and state.get("status") == "complete":
            raise HTTPException(status_code=409, detail="Historical database is already complete")
    if await repo.has_active_job(job_type, request.symbol, request.interval):
        raise HTTPException(status_code=409, detail=f"A {job_type} job is already queued or running")
    job = await repo.create_job(
        job_type,
        request.symbol,
        request.interval,
        {"force_restart": request.force_restart},
    )
    await repo.upsert_state(request.symbol, request.interval, status="queued")
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


@app.post("/api/backtests/metrics-preview", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def metrics_preview(request: MetricsPreviewRequest) -> ApiEnvelope:
    metrics = calculate_metrics(request.net_pnls, request.starting_balance)
    return ApiEnvelope(data=metrics.as_dict())
