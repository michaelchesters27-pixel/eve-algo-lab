from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from app.backtesting.metrics import calculate_metrics
from app.models.schemas import (
    ApiEnvelope,
    ComexClosingMomentumBacktestRequest,
    FixedLadderBacktestRequest,
    FleetHeartbeatRequest,
    GoldH1TrendBacktestRequest,
    GoldH4TrendBacktestRequest,
    GoldSessionAnomalyBacktestRequest,
    JobRequest,
    JobResponse,
    LearningBuildRequest,
    LiquidityBasketBacktestRequest,
    LondonOpeningRangeBacktestRequest,
    MetricsPreviewRequest,
    NewYorkMorningMomentumBacktestRequest,
)
from app.services.autonomy import AutonomousLearningService
from app.services.backtests import (
    BacktestService,
    comex_closing_momentum_settings_match,
    gold_session_anomaly_identity,
    gold_session_anomaly_settings_match,
    gold_h1_settings_match,
    gold_h4_settings_match,
    liquidity_identity,
    liquidity_settings_match,
    london_settings_match,
    new_york_momentum_settings_match,
)
from app.services.ingestion import IngestionService, historical_backfill_complete
from app.services.historical_research import ContinuousHistoricalResearchService
from app.services.learning import LearningService, SNAPSHOT_INTERVAL
from app.services.strategy_lab import StrategyLabService
from app.services.strategy_evolution import StrategyEvolutionService
from app.services.high_resolution_validation import HighResolutionValidationService
from app.services.mt5_generator import MT5GeneratorService, build_package_zip, prepare_package_for_download
from app.services.demo_eligibility import build_demo_dashboard
from app.services.fleet import build_fleet_dashboard, heartbeat_row, verify_fleet_token
from app.services.supabase_repo import SupabaseError, SupabaseRepository
from app.services.twelve_data import INTERVAL_SECONDS, TwelveDataClient
from app.settings import Settings, get_settings

APP_VERSION = "3.8"

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
high_resolution_validation = HighResolutionValidationService(settings, repo, historical_research.load_complete_rows)
mt5_generator = MT5GeneratorService(settings, repo)
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
    background_tasks.append(asyncio.create_task(high_resolution_validation.loop(), name="high-resolution-validation"))
    background_tasks.append(asyncio.create_task(mt5_generator.loop(), name="mt5-ea-generator"))
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
    await high_resolution_validation.stop()
    await mt5_generator.stop()
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
    description="Permanent multi-timeframe XAU/USD memory with autonomous learning, continuous historical research, an autonomous Strategy Idea Factory, controlled strategy evolution, automatic M1 validation, frozen-rule MT5 EA generation, live eligibility labelling and high-resolution backtesting.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-EVE-ADMIN-TOKEN", "X-EVE-FLEET-TOKEN"],
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


@app.get("/api/validation/status", response_model=ApiEnvelope)
async def high_resolution_validation_status(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
) -> ApiEnvelope:
    dashboard = await repo.validation_dashboard(symbol, SNAPSHOT_INTERVAL)
    dashboard["service"] = "online"
    dashboard["version"] = APP_VERSION
    return ApiEnvelope(data=dashboard)


@app.get("/api/validation/jobs", response_model=ApiEnvelope)
async def list_high_resolution_validation_jobs(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    result_status: str = Query(default="all", pattern="^(all|rejected|needs_more_evidence|replay_validated|ready_for_mt5_generation)$"),
    order: str = Query(default="profit_factor", pattern="^(profit_factor|expectancy|drawdown|robustness|recent)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiEnvelope:
    items = await repo.list_validation_jobs(
        symbol, SNAPSHOT_INTERVAL, result_status=result_status, order=order, limit=limit
    )
    return ApiEnvelope(data={"items": items, "result_status": result_status, "order": order})


@app.post("/api/validation/wake", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def wake_high_resolution_validation() -> ApiEnvelope:
    await high_resolution_validation.request_wake()
    return ApiEnvelope(
        data={"status": "requested"},
        message="High-resolution validation wake requested. Normal M1 replay validation runs automatically.",
    )


@app.get("/api/mt5/status", response_model=ApiEnvelope)
async def mt5_generation_status(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
) -> ApiEnvelope:
    dashboard = await repo.mt5_generation_dashboard(symbol)
    dashboard["service"] = "online"
    dashboard["version"] = APP_VERSION
    return ApiEnvelope(data=dashboard)


@app.get("/api/mt5/packages", response_model=ApiEnvelope)
async def list_mt5_packages(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    limit: int = Query(default=100, ge=1, le=200),
) -> ApiEnvelope:
    items = await repo.list_mt5_packages(symbol, limit=limit)
    return ApiEnvelope(data={"items": items})


@app.get("/api/mt5/eligibility", response_model=ApiEnvelope)
async def mt5_demo_eligibility(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    limit: int = Query(default=100, ge=1, le=200),
) -> ApiEnvelope:
    packages = await repo.list_mt5_packages(symbol, limit=limit)
    snapshot = await repo.get_latest_learning_snapshot(symbol, SNAPSHOT_INTERVAL)
    dashboard = build_demo_dashboard(packages, snapshot)
    dashboard["service"] = "online"
    dashboard["version"] = APP_VERSION
    dashboard["symbol"] = symbol
    return ApiEnvelope(data=dashboard)


@app.get("/api/mt5/packages/{package_id}/download")
async def download_mt5_package(package_id: str) -> Response:
    package = await repo.get_mt5_package(package_id)
    if not package:
        raise HTTPException(status_code=404, detail="MT5 package not found")
    package = prepare_package_for_download(package, settings.admin_token)
    archive = build_package_zip(package)
    strategy_code = str(package.get("strategy_code") or "EVE-Strategy").replace("/", "-")
    version = str(package.get("frozen_version") or "1.0").replace("/", "-")
    filename = f"{strategy_code}-MT5-v{version}.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/mt5/packages/{package_id}/source")
async def download_mt5_source(package_id: str) -> Response:
    package = await repo.get_mt5_package(package_id)
    if not package:
        raise HTTPException(status_code=404, detail="MT5 package not found")
    package = prepare_package_for_download(package, settings.admin_token)
    filename = str(package.get("file_name") or "EVE_Strategy.mq5")
    return Response(
        content=str(package.get("mq5_source") or ""),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@app.post("/api/fleet/heartbeat", response_model=ApiEnvelope)
async def mt5_fleet_heartbeat(
    request: FleetHeartbeatRequest,
    x_eve_fleet_token: Annotated[str | None, Header()] = None,
) -> ApiEnvelope:
    package = await repo.get_mt5_package(request.package_id)
    if not package or str(package.get("rule_hash") or "") != request.rule_hash:
        raise HTTPException(status_code=404, detail="EVE MT5 package not found")
    if not verify_fleet_token(settings.admin_token, request.package_id, request.rule_hash, x_eve_fleet_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Demo Fleet token")
    payload = request.model_dump()
    row = heartbeat_row(payload)
    try:
        await repo.upsert_mt5_fleet_instance(row)
    except SupabaseError as exc:
        if "mt5_fleet_instances" in str(exc):
            raise HTTPException(status_code=503, detail="Run SUPABASE_UPDATE_v3.1.sql to enable Demo Fleet") from exc
        raise
    return ApiEnvelope(data={"status": "accepted", "instance_key": row["instance_key"], "heartbeat_at": row["heartbeat_at"]})


@app.get("/api/fleet", response_model=ApiEnvelope)
async def mt5_fleet_dashboard(
    symbol: str = Query(default="XAU/USD", min_length=3, max_length=40),
    limit: int = Query(default=200, ge=1, le=500),
) -> ApiEnvelope:
    packages = await repo.list_mt5_packages(symbol, limit=200)
    try:
        rows = await repo.list_mt5_fleet_instances(limit=limit)
    except SupabaseError as exc:
        if "mt5_fleet_instances" in str(exc):
            return ApiEnvelope(data={
                "setup_required": True,
                "counts": {"online": 0, "stale": 0, "offline": 0, "detached": 0, "in_trade": 0, "attention": 0, "duplicates": 0, "total": 0},
                "items": [],
                "message": "Run SUPABASE_UPDATE_v3.1.sql once to enable live MT5 attachment detection.",
            })
        raise
    dashboard = build_fleet_dashboard(rows, packages)
    dashboard["setup_required"] = False
    dashboard["service"] = "online"
    dashboard["version"] = APP_VERSION
    return ApiEnvelope(data=dashboard)


@app.post("/api/mt5/wake", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def wake_mt5_generator() -> ApiEnvelope:
    await mt5_generator.request_wake()
    return ApiEnvelope(
        data={"status": "requested"},
        message="MT5 generator wake requested. Frozen strategies are generated automatically.",
    )


def _parse_stored_datetime(value: Any, label: str) -> datetime:
    if not value:
        raise HTTPException(status_code=409, detail=f"M1 Market Memory has no {label} timestamp")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"M1 Market Memory has an invalid {label} timestamp") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _chronological_test_dates(
    request: ComexClosingMomentumBacktestRequest | GoldH1TrendBacktestRequest | GoldH4TrendBacktestRequest | GoldSessionAnomalyBacktestRequest | LiquidityBasketBacktestRequest | LondonOpeningRangeBacktestRequest | NewYorkMorningMomentumBacktestRequest,
    state: dict[str, Any],
) -> tuple[str, str]:
    oldest = _parse_stored_datetime(state.get("oldest_stored"), "oldest-candle")
    latest = _parse_stored_datetime(state.get("latest_stored"), "latest-candle")
    if latest <= oldest:
        raise HTTPException(status_code=409, detail="M1 Market Memory date range is invalid")
    if request.test_segment == "custom":
        if request.date_from is None or request.date_to is None:
            raise HTTPException(status_code=422, detail="Custom tests require both a start date and an end date")
        start = request.date_from if request.date_from.tzinfo is not None else request.date_from.replace(tzinfo=timezone.utc)
        end = request.date_to if request.date_to.tzinfo is not None else request.date_to.replace(tzinfo=timezone.utc)
        if start < oldest and start.date() == oldest.date():
            start = oldest
        if end > latest and end.date() == latest.date():
            end = latest
    elif request.test_segment == "development":
        start = oldest
        split = oldest + (latest - oldest) * (2.0 / 3.0)
        end = split - timedelta(microseconds=1)
    elif request.test_segment == "untouched":
        # Both database filters are inclusive, so development ends one
        # microsecond before this boundary and no candle can enter both sets.
        start = oldest + (latest - oldest) * (2.0 / 3.0)
        end = latest
    else:
        start = request.date_from or oldest
        end = request.date_to or latest
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    if start < oldest or end > latest:
        raise HTTPException(status_code=422, detail="Selected dates fall outside stored M1 Market Memory")
    if end <= start:
        raise HTTPException(status_code=422, detail="Test end date must be later than its start date")
    return start.isoformat(), end.isoformat()


@app.post("/api/backtests/gold-h1-trend", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_gold_h1_trend_backtest(request: GoldH1TrendBacktestRequest) -> ApiEnvelope:
    m1_state = await repo.get_state(request.symbol, "1min")
    h1_state = await repo.get_state(request.symbol, "1h")
    d1_state = await repo.get_state(request.symbol, "1day")
    missing = [
        label
        for label, state, interval in (
            ("M1", m1_state, "1min"),
            ("H1", h1_state, "1h"),
            ("D1", d1_state, "1day"),
        )
        if not state_is_historically_ready(state, interval)
    ]
    if missing:
        raise HTTPException(status_code=409, detail=f"{' + '.join(missing)} Market Memory must be complete before this test can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")
    date_from, date_to = _chronological_test_dates(request, m1_state or {})
    segment_names = {
        "full": "Full History",
        "development": "Development First Two-Thirds",
        "untouched": "Untouched Final Third",
        "custom": "Custom Period",
    }
    strategy_version_id = await backtests.ensure_gold_h1_strategy_version()
    settings_payload = request.model_dump(mode="json")
    settings_payload.update(
        {
            "date_from": date_from,
            "date_to": date_to,
            "strategy": "gold_h1_trend",
        }
    )
    locked_development_run_id: str | None = None
    if request.test_segment == "untouched":
        recent_runs = await repo.list_backtest_runs(100)
        matching_development = next(
            (
                candidate
                for candidate in recent_runs
                if candidate.get("status") == "complete"
                and (candidate.get("settings") or {}).get("strategy") == "gold_h1_trend"
                and (candidate.get("settings") or {}).get("test_segment") == "development"
                and gold_h1_settings_match(candidate.get("settings") or {}, settings_payload)
            ),
            None,
        )
        if matching_development is None:
            raise HTTPException(
                status_code=409,
                detail="Run and complete the Development first-two-thirds test with these exact Gold H1 settings before the Untouched test",
            )
        locked_development_run_id = str(matching_development["id"])
        settings_payload["locked_development_run_id"] = locked_development_run_id
    run_name = f"Gold H1 Trend 55/20 v1 — {segment_names[request.test_segment]}"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": run_name,
            "symbol": request.symbol,
            "interval": "1min",
            "resolution": "m1_replay",
            "status": "queued",
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "Stored completed H1 and D1 signals with verified M1 execution, stop and gap replay",
                "input_interval": "1min",
                "signal_interval": "1h",
                "context_interval": "1day",
                "strategy": "gold_h1_trend",
                "test_segment": request.test_segment,
                "locked_development_run_id": locked_development_run_id,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start_gold_h1(run_id, settings_payload)
    return ApiEnvelope(
        data={
            "id": run_id,
            "status": "queued",
            "name": run_name,
            "date_from": date_from,
            "date_to": date_to,
            "test_segment": request.test_segment,
        },
        message="Gold H1 Trend 55/20 v1 replay started",
    )



@app.post("/api/backtests/gold-h4-trend", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_gold_h4_trend_backtest(request: GoldH4TrendBacktestRequest) -> ApiEnvelope:
    m1_state = await repo.get_state(request.symbol, "1min")
    h4_state = await repo.get_state(request.symbol, "4h")
    d1_state = await repo.get_state(request.symbol, "1day")
    missing = [
        label
        for label, state, interval in (
            ("M1", m1_state, "1min"),
            ("H4", h4_state, "4h"),
            ("D1", d1_state, "1day"),
        )
        if not state_is_historically_ready(state, interval)
    ]
    if missing:
        raise HTTPException(status_code=409, detail=f"{' + '.join(missing)} Market Memory must be complete before this test can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")
    date_from, date_to = _chronological_test_dates(request, m1_state or {})
    segment_names = {
        "full": "Full History",
        "development": "Development First Two-Thirds",
        "untouched": "Untouched Final Third",
        "custom": "Custom Period",
    }
    strategy_version_id = await backtests.ensure_gold_h4_strategy_version()
    settings_payload = request.model_dump(mode="json")
    settings_payload.update(
        {
            "date_from": date_from,
            "date_to": date_to,
            "strategy": "gold_h4_trend",
        }
    )
    locked_development_run_id: str | None = None
    if request.test_segment == "untouched":
        recent_runs = await repo.list_backtest_runs(100)
        matching_development = next(
            (
                candidate
                for candidate in recent_runs
                if candidate.get("status") == "complete"
                and (candidate.get("settings") or {}).get("strategy") == "gold_h4_trend"
                and (candidate.get("settings") or {}).get("test_segment") == "development"
                and gold_h4_settings_match(candidate.get("settings") or {}, settings_payload)
            ),
            None,
        )
        if matching_development is None:
            raise HTTPException(
                status_code=409,
                detail="Run and complete the Development first-two-thirds test with these exact Gold H4 settings before the Untouched test",
            )
        locked_development_run_id = str(matching_development["id"])
        settings_payload["locked_development_run_id"] = locked_development_run_id
    run_name = f"Gold H4 Trend 55/20 v1 — {segment_names[request.test_segment]}"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": run_name,
            "symbol": request.symbol,
            "interval": "1min",
            "resolution": "m1_replay",
            "status": "queued",
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "Stored completed H4 and D1 signals with verified M1 execution, stop and gap replay",
                "input_interval": "1min",
                "signal_interval": "4h",
                "context_interval": "1day",
                "strategy": "gold_h4_trend",
                "test_segment": request.test_segment,
                "locked_development_run_id": locked_development_run_id,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start_gold_h4(run_id, settings_payload)
    return ApiEnvelope(
        data={
            "id": run_id,
            "status": "queued",
            "name": run_name,
            "date_from": date_from,
            "date_to": date_to,
            "test_segment": request.test_segment,
        },
        message="Gold H4 Trend 55/20 v1 replay started",
    )


@app.post("/api/backtests/comex-closing-momentum", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_comex_closing_momentum_backtest(request: ComexClosingMomentumBacktestRequest) -> ApiEnvelope:
    state = await repo.get_state(request.symbol, "1min")
    if not state_is_historically_ready(state, "1min"):
        raise HTTPException(status_code=409, detail="M1 Market Memory must be complete before this backtest can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")
    date_from, date_to = _chronological_test_dates(request, state or {})
    segment_names = {
        "full": "Full M1 History",
        "development": "Development First Two-Thirds",
        "untouched": "Untouched Final Third",
        "custom": "Custom M1 Period",
    }
    strategy_version_id = await backtests.ensure_comex_closing_momentum_strategy_version()
    settings_payload = request.model_dump(mode="json")
    settings_payload.update(
        {
            "date_from": date_from,
            "date_to": date_to,
            "strategy": "comex_closing_momentum",
        }
    )
    locked_development_run_id: str | None = None
    if request.test_segment == "untouched":
        recent_runs = await repo.list_backtest_runs(100)
        matching_development = next(
            (
                candidate
                for candidate in recent_runs
                if candidate.get("status") == "complete"
                and (candidate.get("settings") or {}).get("strategy") == "comex_closing_momentum"
                and (candidate.get("settings") or {}).get("test_segment") == "development"
                and comex_closing_momentum_settings_match(candidate.get("settings") or {}, settings_payload)
            ),
            None,
        )
        if matching_development is None:
            raise HTTPException(
                status_code=409,
                detail="Run and complete Development with these exact COMEX settings before the Untouched test",
            )
        locked_development_run_id = str(matching_development["id"])
        settings_payload["locked_development_run_id"] = locked_development_run_id
    run_name = f"COMEX Closing Momentum v1 — {segment_names[request.test_segment]}"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": run_name,
            "symbol": request.symbol,
            "interval": "1min",
            "resolution": "m1_replay",
            "status": "queued",
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "Verified M1 reference, 13:00 entry, hard-money stop and exact 13:30 exit replay",
                "input_interval": "1min",
                "signal_interval": "1min",
                "strategy": "comex_closing_momentum",
                "test_segment": request.test_segment,
                "maximum_trades_per_day": 1,
                "locked_development_run_id": locked_development_run_id,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start_comex_closing_momentum(run_id, settings_payload)
    return ApiEnvelope(
        data={
            "id": run_id,
            "status": "queued",
            "name": run_name,
            "date_from": date_from,
            "date_to": date_to,
            "test_segment": request.test_segment,
        },
        message="COMEX Closing Momentum v1 once-a-day replay started",
    )


@app.post("/api/backtests/gold-session-anomaly", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_gold_session_anomaly_backtest(request: GoldSessionAnomalyBacktestRequest) -> ApiEnvelope:
    state = await repo.get_state(request.symbol, "1min")
    if not state_is_historically_ready(state, "1min"):
        raise HTTPException(status_code=409, detail="M1 Market Memory must be complete before this backtest can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")
    date_from, date_to = _chronological_test_dates(request, state or {})
    identity = gold_session_anomaly_identity(request.session_leg)
    segment_names = {
        "full": "Full M1 History",
        "development": "Development First Two-Thirds",
        "untouched": "Untouched Final Third",
        "custom": "Custom M1 Period",
    }
    strategy_version_id = await backtests.ensure_gold_session_anomaly_strategy_version(request.session_leg)
    settings_payload = request.model_dump(mode="json")
    settings_payload.update(
        {
            "date_from": date_from,
            "date_to": date_to,
            "strategy": identity["code"],
        }
    )
    locked_development_run_id: str | None = None
    if request.test_segment == "untouched":
        recent_runs = await repo.list_backtest_runs(100)
        matching_development = next(
            (
                candidate
                for candidate in recent_runs
                if candidate.get("status") == "complete"
                and (candidate.get("settings") or {}).get("strategy") == identity["code"]
                and (candidate.get("settings") or {}).get("test_segment") == "development"
                and ((candidate.get("reliability") or {}).get("verdict") or {}).get("code") == "promising"
                and gold_session_anomaly_settings_match(candidate.get("settings") or {}, settings_payload)
            ),
            None,
        )
        if matching_development is None:
            raise HTTPException(
                status_code=409,
                detail="This exact strategy must pass Development before EVE will unlock the untouched final third",
            )
        locked_development_run_id = str(matching_development["id"])
        settings_payload["locked_development_run_id"] = locked_development_run_id
    run_name = f"{identity['name'].removeprefix('EVE ')} — {segment_names[request.test_segment]}"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": run_name,
            "symbol": request.symbol,
            "interval": "1min",
            "resolution": "m1_replay",
            "status": "queued",
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "Verified M1 session-boundary entry, hard-money stop, costs and session exit replay",
                "input_interval": "1min",
                "signal_interval": "1min",
                "strategy": identity["code"],
                "session_leg": request.session_leg,
                "test_segment": request.test_segment,
                "maximum_trades_per_day": 1,
                "locked_development_run_id": locked_development_run_id,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start_gold_session_anomaly(run_id, settings_payload)
    return ApiEnvelope(
        data={
            "id": run_id,
            "status": "queued",
            "name": run_name,
            "date_from": date_from,
            "date_to": date_to,
            "test_segment": request.test_segment,
        },
        message=f"{identity['name'].removeprefix('EVE ')} once-a-day replay started",
    )


@app.post("/api/backtests/new-york-morning-momentum", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_new_york_morning_momentum_backtest(request: NewYorkMorningMomentumBacktestRequest) -> ApiEnvelope:
    state = await repo.get_state(request.symbol, "1min")
    if not state_is_historically_ready(state, "1min"):
        raise HTTPException(status_code=409, detail="M1 Market Memory must be complete before this backtest can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")
    date_from, date_to = _chronological_test_dates(request, state or {})
    segment_names = {
        "full": "Full M1 History",
        "development": "Development First Two-Thirds",
        "untouched": "Untouched Final Third",
        "custom": "Custom M1 Period",
    }
    strategy_version_id = await backtests.ensure_new_york_momentum_strategy_version()
    settings_payload = request.model_dump(mode="json")
    settings_payload.update(
        {
            "date_from": date_from,
            "date_to": date_to,
            "strategy": "new_york_morning_momentum",
        }
    )
    locked_development_run_id: str | None = None
    if request.test_segment == "untouched":
        recent_runs = await repo.list_backtest_runs(100)
        matching_development = next(
            (
                candidate
                for candidate in recent_runs
                if candidate.get("status") == "complete"
                and (candidate.get("settings") or {}).get("strategy") == "new_york_morning_momentum"
                and (candidate.get("settings") or {}).get("test_segment") == "development"
                and new_york_momentum_settings_match(candidate.get("settings") or {}, settings_payload)
            ),
            None,
        )
        if matching_development is None:
            raise HTTPException(
                status_code=409,
                detail="Run and complete Development with these exact once-a-day settings before the Untouched test",
            )
        locked_development_run_id = str(matching_development["id"])
        settings_payload["locked_development_run_id"] = locked_development_run_id
    run_name = f"New York Morning Momentum v1 — {segment_names[request.test_segment]}"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": run_name,
            "symbol": request.symbol,
            "interval": "1min",
            "resolution": "m1_replay",
            "status": "queued",
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "Complete M1 signal window with M1 entry, stop, gap and forced-exit replay",
                "input_interval": "1min",
                "signal_interval": "1min",
                "strategy": "new_york_morning_momentum",
                "test_segment": request.test_segment,
                "maximum_trades_per_day": 1,
                "locked_development_run_id": locked_development_run_id,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start_new_york_momentum(run_id, settings_payload)
    return ApiEnvelope(
        data={
            "id": run_id,
            "status": "queued",
            "name": run_name,
            "date_from": date_from,
            "date_to": date_to,
            "test_segment": request.test_segment,
        },
        message="New York Morning Momentum v1 once-a-day replay started",
    )


@app.post("/api/backtests/london-opening-range", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_london_opening_range_backtest(request: LondonOpeningRangeBacktestRequest) -> ApiEnvelope:
    state = await repo.get_state(request.symbol, "1min")
    if not state_is_historically_ready(state, "1min"):
        raise HTTPException(status_code=409, detail="M1 Market Memory must be complete before this backtest can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")
    date_from, date_to = _chronological_test_dates(request, state or {})
    segment_names = {
        "full": "Full M1 History",
        "development": "Development First Two-Thirds",
        "untouched": "Untouched Final Third",
        "custom": "Custom M1 Period",
    }
    strategy_version_id = await backtests.ensure_london_strategy_version()
    settings_payload = request.model_dump(mode="json")
    settings_payload.update(
        {
            "date_from": date_from,
            "date_to": date_to,
            "strategy": "london_opening_range",
        }
    )
    locked_development_run_id: str | None = None
    if request.test_segment == "untouched":
        recent_runs = await repo.list_backtest_runs(100)
        matching_development = next(
            (
                candidate
                for candidate in recent_runs
                if candidate.get("status") == "complete"
                and (candidate.get("settings") or {}).get("strategy") == "london_opening_range"
                and (candidate.get("settings") or {}).get("test_segment") == "development"
                and london_settings_match(candidate.get("settings") or {}, settings_payload)
            ),
            None,
        )
        if matching_development is None:
            raise HTTPException(
                status_code=409,
                detail="Run and complete the Development first-two-thirds test with these exact London settings before the Untouched test",
            )
        locked_development_run_id = str(matching_development["id"])
        settings_payload["locked_development_run_id"] = locked_development_run_id
    run_name = f"London Opening Range v1 — {segment_names[request.test_segment]}"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": run_name,
            "symbol": request.symbol,
            "interval": "1min",
            "resolution": "m1_replay",
            "status": "queued",
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "M5 signals reconstructed from verified M1 candles; M1 execution replay",
                "input_interval": "1min",
                "signal_interval": "5min",
                "strategy": "london_opening_range",
                "test_segment": request.test_segment,
                "locked_development_run_id": locked_development_run_id,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start_london(run_id, settings_payload)
    return ApiEnvelope(
        data={
            "id": run_id,
            "status": "queued",
            "name": run_name,
            "date_from": date_from,
            "date_to": date_to,
            "test_segment": request.test_segment,
        },
        message="London Opening Range v1 M1 replay started",
    )


@app.post("/api/backtests/liquidity-basket", response_model=ApiEnvelope, dependencies=[Depends(require_admin)])
async def start_liquidity_basket_backtest(request: LiquidityBasketBacktestRequest) -> ApiEnvelope:
    state = await repo.get_state(request.symbol, "1min")
    if not state_is_historically_ready(state, "1min"):
        raise HTTPException(status_code=409, detail="M1 Market Memory must be complete before this backtest can run")
    if await repo.has_active_backtest():
        raise HTTPException(status_code=409, detail="Another backtest is already running")
    date_from, date_to = _chronological_test_dates(request, state or {})
    segment_names = {
        "full": "Full M1 History",
        "development": "Development First Two-Thirds",
        "untouched": "Untouched Final Third",
        "custom": "Custom M1 Period",
    }
    identity = liquidity_identity(request.entry_model)
    strategy_version_id = await backtests.ensure_liquidity_strategy_version(request.entry_model)
    settings_payload = request.model_dump(mode="json")
    settings_payload.update({"date_from": date_from, "date_to": date_to, "strategy": identity["code"]})
    locked_development_run_id: str | None = None
    if request.test_segment == "untouched":
        recent_runs = await repo.list_backtest_runs(100)
        matching_development = next(
            (
                candidate
                for candidate in recent_runs
                if candidate.get("status") == "complete"
                and (candidate.get("settings") or {}).get("strategy") == identity["code"]
                and (candidate.get("settings") or {}).get("test_segment") == "development"
                and liquidity_settings_match(candidate.get("settings") or {}, settings_payload)
            ),
            None,
        )
        if matching_development is None:
            raise HTTPException(
                status_code=409,
                detail="Run and complete the Development first-two-thirds test with these exact settings before the Untouched test",
            )
        locked_development_run_id = str(matching_development["id"])
        settings_payload["locked_development_run_id"] = locked_development_run_id
    run_name = f"{identity['name'].removeprefix('EVE ')} — {segment_names[request.test_segment]}"
    run = await repo.create_backtest_run(
        {
            "strategy_version_id": strategy_version_id,
            "name": run_name,
            "symbol": request.symbol,
            "interval": "1min",
            "resolution": "m1_replay",
            "status": "queued",
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": request.starting_balance,
            "settings": settings_payload,
            "reliability": {
                "progress_percent": 0,
                "message": "Queued for Railway",
                "accuracy": "M1 high-resolution candle replay",
                "input_interval": "1min",
                "strategy": identity["code"],
                "entry_model": request.entry_model,
                "test_segment": request.test_segment,
                "locked_development_run_id": locked_development_run_id,
            },
        }
    )
    run_id = str(run["id"])
    await backtests.start_liquidity(run_id, settings_payload)
    return ApiEnvelope(
        data={
            "id": run_id,
            "status": "queued",
            "name": run_name,
            "date_from": date_from,
            "date_to": date_to,
            "test_segment": request.test_segment,
        },
        message=f"{identity['name'].removeprefix('EVE ')} M1 replay started",
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


@app.get("/api/backtests/active", response_model=ApiEnvelope)
async def list_active_backtests(limit: int = Query(default=5, ge=1, le=20)) -> ApiEnvelope:
    return ApiEnvelope(data=await repo.list_active_backtest_runs(limit))


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
