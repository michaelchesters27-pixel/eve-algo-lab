from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.four_ccb_daily_research import ENGINE_VERSION, STRATEGY_CODE, FourCCBDailyResearch


class FourCCBDailyResearchRequest(BaseModel):
    symbol: str = Field(default="XAU/USD", min_length=3, max_length=40)


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


async def _run_analysis(repo: Any, run_id: str, request: FourCCBDailyResearchRequest, date_from: str, date_to: str) -> None:
    try:
        total_rows = await repo.count_market_candles(request.symbol, "1h", date_from, date_to)
        if total_rows < 5000:
            raise RuntimeError("Stored H1 history is too short for 4CCB Daily research")

        await repo.update_backtest_run(
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "input_interval": "1h",
                "progress_percent": 0.0,
                "message": f"Loading {total_rows:,} H1 candles for 4CCB Daily",
            },
        )

        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        processed = 0
        while True:
            page = await repo.fetch_candles_page(
                symbol=request.symbol,
                interval="1h",
                after=cursor,
                date_from=date_from if cursor is None else None,
                date_to=date_to,
                limit=1000,
            )
            if not page:
                break
            rows.extend(page)
            processed += len(page)
            cursor = str(page[-1]["candle_time"])
            if len(page) < 1000:
                break

        await repo.update_backtest_run(
            run_id,
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "input_interval": "1h",
                "progress_percent": 30.0,
                "message": "Testing fixed daily four-candle windows for both frequency and edge",
            },
        )

        report = await asyncio.to_thread(FourCCBDailyResearch(rows).run)
        report["source"] = {
            "symbol": request.symbol,
            "interval": "1h",
            "date_from": date_from,
            "date_to": date_to,
            "rows_scanned": processed,
        }
        champion = report["champion"]
        full_metrics = champion["full_history_metrics"]
        validation_metrics = champion["validation_metrics"]
        confirmation_metrics = champion["confirmation_metrics"]
        verdict = report["verdict"]

        await repo.update_backtest_run(
            run_id,
            status="complete",
            total_positions=int(full_metrics["trades"]),
            total_baskets=int(full_metrics["trades"]),
            winning_baskets=int(full_metrics["wins"]),
            losing_baskets=int(full_metrics["losses"]),
            basket_win_rate=float(full_metrics["win_rate_pct"]),
            expectancy=float(full_metrics["expectancy_r"]),
            finished_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "accuracy": "Causal H1 research with one fixed four-candle daily window, chronological validation and a 0.18 price-unit cost proxy. Research only.",
                "input_interval": "1h",
                "progress_percent": 100.0,
                "message": (
                    f"Complete · validation PF {validation_metrics['profit_factor']} / {validation_metrics['trade_days_pct']}% days · "
                    f"confirmation PF {confirmation_metrics['profit_factor']} / {confirmation_metrics['trade_days_pct']}% days · {verdict}"
                ),
                "research_report": report,
            },
        )
        await repo.log_event(
            "success",
            "4ccb-daily-research",
            "4CCB Daily research completed",
            {
                "run_id": run_id,
                "verdict": verdict,
                "validation_profit_factor": validation_metrics["profit_factor"],
                "validation_trade_days_pct": validation_metrics["trade_days_pct"],
                "confirmation_profit_factor": confirmation_metrics["profit_factor"],
                "confirmation_trade_days_pct": confirmation_metrics["trade_days_pct"],
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
                "message": f"4CCB Daily research failed: {exc}",
            },
        )
        await repo.log_event(
            "error",
            "4ccb-daily-research",
            "4CCB Daily research failed",
            {"run_id": run_id, "error": str(exc)},
        )


def build_four_ccb_daily_router(repo: Any, require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter()
    tasks: dict[str, asyncio.Task[Any]] = {}

    @router.post("/api/research/4ccb-daily/run", dependencies=[Depends(require_admin)])
    async def start_research(request: FourCCBDailyResearchRequest) -> dict[str, Any]:
        state = await repo.get_state(request.symbol, "1h")
        if not _is_ready(state):
            raise HTTPException(status_code=409, detail="Complete H1 Market Memory is required before 4CCB Daily can run")
        recent = await repo.list_backtest_runs(100)
        active = next(
            (
                run for run in recent
                if run.get("status") in {"queued", "running"}
                and (run.get("settings") or {}).get("strategy") == STRATEGY_CODE
            ),
            None,
        )
        if active:
            raise HTTPException(status_code=409, detail=f"4CCB Daily research is already running ({active['id']})")

        date_from = str(state["oldest_stored"])
        date_to = str(state["latest_stored"])
        run = await repo.create_backtest_run(
            {
                "name": "4CCB Daily v0.1 Research",
                "symbol": request.symbol,
                "interval": "1h",
                "resolution": "candle",
                "status": "queued",
                "date_from": date_from,
                "date_to": date_to,
                "settings": {
                    "strategy": STRATEGY_CODE,
                    "engine_version": ENGINE_VERSION,
                    "research_only": True,
                    "timeframe": "H1",
                    "goal": "approach one trade per trading day without sacrificing out-of-sample edge",
                    "maximum_new_trades_per_day": 1,
                    "one_position_at_a_time": True,
                    "cost_proxy_price_units_per_trade": 0.18,
                    "note": "Separate from the frozen 4CCB candidate; no frozen-rule changes are permitted here.",
                },
                "reliability": {
                    "engine_version": ENGINE_VERSION,
                    "strategy": STRATEGY_CODE,
                    "progress_percent": 0.0,
                    "message": "Queued for 4CCB Daily research",
                },
            }
        )
        run_id = str(run["id"])
        task = asyncio.create_task(
            _run_analysis(repo, run_id, request, date_from, date_to),
            name=f"four-ccb-daily-{run_id}",
        )
        tasks[run_id] = task
        task.add_done_callback(lambda _: tasks.pop(run_id, None))
        return {"ok": True, "data": _public_run(run), "message": "4CCB Daily research queued"}

    @router.get("/api/research/4ccb-daily/status")
    async def latest_research() -> dict[str, Any]:
        recent = await repo.list_backtest_runs(100)
        run = next(
            (candidate for candidate in recent if (candidate.get("settings") or {}).get("strategy") == STRATEGY_CODE),
            None,
        )
        return {"ok": True, "data": _public_run(run) if run else None}

    @router.get("/api/research/4ccb-daily/{run_id}")
    async def get_research(run_id: str) -> dict[str, Any]:
        run = await repo.get_backtest_run(run_id)
        if not run or (run.get("settings") or {}).get("strategy") != STRATEGY_CODE:
            raise HTTPException(status_code=404, detail="4CCB Daily research run not found")
        return {"ok": True, "data": _public_run(run)}

    return router
