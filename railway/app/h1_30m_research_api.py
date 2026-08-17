from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.h1_30m_research import ENGINE_VERSION, H1ThirtyMinuteAnalyzer, STRATEGY_CODE


class H1ThirtyMinuteResearchRequest(BaseModel):
    symbol: str = Field(default="XAU/USD", min_length=3, max_length=40)
    timezone_name: Literal["UTC", "Europe/London", "America/New_York"] = "UTC"


def _is_ready(state: dict[str, Any] | None) -> bool:
    return bool(state and state.get("status") == "complete" and state.get("oldest_stored") and state.get("latest_stored"))


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    reliability = dict(run.get("reliability") or {})
    return {
        "id": str(run.get("id") or ""),
        "name": run.get("name"),
        "symbol": run.get("symbol"),
        "status": run.get("status"),
        "date_from": run.get("date_from"),
        "date_to": run.get("date_to"),
        "created_at": run.get("created_at"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "error": run.get("error"),
        "progress_percent": reliability.get("progress_percent", 0),
        "message": reliability.get("message", ""),
        "report": reliability.get("research_report"),
        "settings": run.get("settings") or {},
    }


async def _run_analysis(repo: Any, run_id: str, request: H1ThirtyMinuteResearchRequest, date_from: str, date_to: str) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    analyzer = H1ThirtyMinuteAnalyzer(request.timezone_name)
    try:
        total_rows = await repo.count_market_candles(request.symbol, "1min", date_from, date_to)
        if total_rows < 60:
            raise RuntimeError("Stored M1 history is too short for the H1 30-minute research test")
        await repo.update_backtest_run(
            run_id,
            status="running",
            started_at=started_at,
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "accuracy": "Exact stored M1 reconstruction; no within-M1 first-hit order is guessed",
                "input_interval": "1min",
                "progress_percent": 0.0,
                "message": f"Scanning {total_rows:,} stored M1 candles",
            },
        )

        cursor: str | None = None
        processed = 0
        page_number = 0
        while True:
            page = await repo.fetch_candles_page(
                symbol=request.symbol,
                interval="1min",
                after=cursor,
                date_from=date_from if cursor is None else None,
                date_to=date_to,
                limit=1000,
            )
            if not page:
                break
            for candle in page:
                analyzer.push(candle)
            processed += len(page)
            page_number += 1
            cursor = str(page[-1]["candle_time"])

            if page_number % 10 == 0 or len(page) < 1000:
                current = await repo.get_backtest_run(run_id)
                if current and current.get("status") == "cancelled":
                    return
                progress = min(99.0, 100.0 * processed / max(1, total_rows))
                await repo.update_backtest_run(
                    run_id,
                    reliability={
                        "engine_version": ENGINE_VERSION,
                        "strategy": STRATEGY_CODE,
                        "accuracy": "Exact stored M1 reconstruction; no within-M1 first-hit order is guessed",
                        "input_interval": "1min",
                        "progress_percent": round(progress, 3),
                        "message": (
                            f"Scanned {processed:,}/{total_rows:,} M1 candles · "
                            f"{len(analyzer.observations):,} two-wick H1 observations so far"
                        ),
                    },
                )
            if len(page) < 1000:
                break

        report = analyzer.finish()
        report["source"] = {
            "symbol": request.symbol,
            "interval": "1min",
            "date_from": date_from,
            "date_to": date_to,
            "rows_scanned": processed,
        }
        qualified = int(report["data_quality"]["qualifying_two_wick_hours"])
        survived = float(report["full"]["both_extremes_survived"]["rate_pct"])
        await repo.update_backtest_run(
            run_id,
            status="complete",
            total_positions=0,
            total_baskets=qualified,
            finished_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "accuracy": "Exact stored M1 reconstruction; no within-M1 first-hit order is guessed",
                "input_interval": "1min",
                "progress_percent": 100.0,
                "message": (
                    f"Complete · {qualified:,} qualifying H1 candles · "
                    f"both first-half extremes survived {survived:.2f}% of the time"
                ),
                "research_report": report,
            },
        )
        await repo.log_event(
            "success",
            "h1-30m-research",
            "H1 30-minute range research completed",
            {
                "run_id": run_id,
                "symbol": request.symbol,
                "qualifying_hours": qualified,
                "both_extremes_survived_pct": survived,
            },
        )
    except Exception as exc:
        await repo.update_backtest_run(
            run_id,
            status="failed",
            error=str(exc),
            finished_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "progress_percent": 0.0,
                "message": f"Research failed: {exc}",
            },
        )
        await repo.log_event(
            "error",
            "h1-30m-research",
            "H1 30-minute range research failed",
            {"run_id": run_id, "error": str(exc)},
        )


def build_h1_30m_router(repo: Any, require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter()
    tasks: dict[str, asyncio.Task[Any]] = {}

    @router.post("/api/research/h1-30m/run", dependencies=[Depends(require_admin)])
    async def start_h1_30m_research(request: H1ThirtyMinuteResearchRequest) -> dict[str, Any]:
        state = await repo.get_state(request.symbol, "1min")
        if not _is_ready(state):
            raise HTTPException(status_code=409, detail="Complete M1 Market Memory is required before this research can run")

        recent = await repo.list_backtest_runs(100)
        active = next(
            (
                run
                for run in recent
                if run.get("status") in {"queued", "running"}
                and (run.get("settings") or {}).get("strategy") == STRATEGY_CODE
            ),
            None,
        )
        if active:
            raise HTTPException(status_code=409, detail=f"H1 30-minute research is already running ({active['id']})")

        date_from = str(state["oldest_stored"])
        date_to = str(state["latest_stored"])
        run = await repo.create_backtest_run(
            {
                "name": "H1 30-Minute Range Theory v1 — Full M1 History",
                "symbol": request.symbol,
                "interval": "1min",
                "resolution": "m1_replay",
                "status": "queued",
                "date_from": date_from,
                "date_to": date_to,
                "settings": {
                    "strategy": STRATEGY_CODE,
                    "engine_version": ENGINE_VERSION,
                    "timezone_name": request.timezone_name,
                    "research_only": True,
                    "trading_rules": None,
                },
                "reliability": {
                    "engine_version": ENGINE_VERSION,
                    "strategy": STRATEGY_CODE,
                    "progress_percent": 0.0,
                    "message": "Queued for exact M1 historical scan",
                },
            }
        )
        run_id = str(run["id"])
        task = asyncio.create_task(
            _run_analysis(repo, run_id, request, date_from, date_to),
            name=f"h1-30m-range-research-{run_id}",
        )
        tasks[run_id] = task
        task.add_done_callback(lambda _: tasks.pop(run_id, None))
        return {"ok": True, "data": _public_run(run), "message": "H1 30-minute range research queued"}

    @router.get("/api/research/h1-30m/status")
    async def latest_h1_30m_research() -> dict[str, Any]:
        recent = await repo.list_backtest_runs(100)
        run = next(
            (
                candidate
                for candidate in recent
                if (candidate.get("settings") or {}).get("strategy") == STRATEGY_CODE
            ),
            None,
        )
        return {"ok": True, "data": _public_run(run) if run else None}

    @router.get("/api/research/h1-30m/{run_id}")
    async def get_h1_30m_research(run_id: str) -> dict[str, Any]:
        run = await repo.get_backtest_run(run_id)
        if not run or (run.get("settings") or {}).get("strategy") != STRATEGY_CODE:
            raise HTTPException(status_code=404, detail="H1 30-minute research run not found")
        return {"ok": True, "data": _public_run(run)}

    return router
