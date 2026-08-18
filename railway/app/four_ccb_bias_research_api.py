from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.four_ccb_bias_research import ENGINE_VERSION, STRATEGY_CODE, FourCCBH1BiasDiscovery


class FourCCBH1BiasResearchRequest(BaseModel):
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


async def _run_analysis(repo: Any, run_id: str, request: FourCCBH1BiasResearchRequest, date_from: str, date_to: str) -> None:
    try:
        total_rows = await repo.count_market_candles(request.symbol, "1h", date_from, date_to)
        if total_rows < 500:
            raise RuntimeError("Stored H1 history is too short for 4CCB bias discovery")
        await repo.update_backtest_run(
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "input_interval": "1h",
                "progress_percent": 0.0,
                "message": f"Loading {total_rows:,} stored H1 candles for bias-filtered 4CCB",
            },
        )

        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        processed = 0
        page_number = 0
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
            page_number += 1
            cursor = str(page[-1]["candle_time"])
            if page_number % 5 == 0 or len(page) < 1000:
                current = await repo.get_backtest_run(run_id)
                if current and current.get("status") == "cancelled":
                    return
                await repo.update_backtest_run(
                    run_id,
                    reliability={
                        "engine_version": ENGINE_VERSION,
                        "strategy": STRATEGY_CODE,
                        "input_interval": "1h",
                        "progress_percent": round(min(30.0, 30.0 * processed / max(1, total_rows)), 3),
                        "message": f"Loaded {processed:,}/{total_rows:,} H1 candles",
                    },
                )
            if len(page) < 1000:
                break

        await repo.update_backtest_run(
            run_id,
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "input_interval": "1h",
                "progress_percent": 35.0,
                "message": "Testing 504 predeclared 4CCB + bias variants on development history",
            },
        )
        report = await asyncio.to_thread(FourCCBH1BiasDiscovery(rows).run)
        report["source"] = {
            "symbol": request.symbol,
            "interval": "1h",
            "date_from": date_from,
            "date_to": date_to,
            "rows_scanned": processed,
        }
        champion = report["champion"]
        full_metrics = champion["full_history_metrics"]
        untouched_metrics = champion["untouched_metrics"]
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
                "accuracy": "Completed H1 OHLC research with causal bias and chronological development/untouched split; M1/tick replay still required for execution proof.",
                "input_interval": "1h",
                "progress_percent": 100.0,
                "message": (
                    f"Complete · {report['variant_count']} bias variants · untouched PF {untouched_metrics['profit_factor']} · "
                    f"untouched expectancy {untouched_metrics['expectancy_r']}R · {verdict}"
                ),
                "research_report": report,
            },
        )
        await repo.log_event(
            "success",
            "4ccb-h1-bias-research",
            "4CCB H1 bias discovery completed",
            {
                "run_id": run_id,
                "variant_count": report["variant_count"],
                "verdict": verdict,
                "untouched_trades": untouched_metrics["trades"],
                "untouched_profit_factor": untouched_metrics["profit_factor"],
                "untouched_expectancy_r": untouched_metrics["expectancy_r"],
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
                "message": f"4CCB bias research failed: {exc}",
            },
        )
        await repo.log_event("error", "4ccb-h1-bias-research", "4CCB H1 bias discovery failed", {"run_id": run_id, "error": str(exc)})


def build_four_ccb_bias_router(repo: Any, require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter()
    tasks: dict[str, asyncio.Task[Any]] = {}

    @router.post("/api/research/4ccb-h1-bias/run", dependencies=[Depends(require_admin)])
    async def start_research(request: FourCCBH1BiasResearchRequest) -> dict[str, Any]:
        state = await repo.get_state(request.symbol, "1h")
        if not _is_ready(state):
            raise HTTPException(status_code=409, detail="Complete H1 Market Memory is required before 4CCB bias discovery can run")
        recent = await repo.list_backtest_runs(100)
        active = next((run for run in recent if run.get("status") in {"queued", "running"} and (run.get("settings") or {}).get("strategy") == STRATEGY_CODE), None)
        if active:
            raise HTTPException(status_code=409, detail=f"4CCB H1 bias discovery is already running ({active['id']})")

        date_from = str(state["oldest_stored"])
        date_to = str(state["latest_stored"])
        run = await repo.create_backtest_run({
            "name": "4CCB H1 Bias Discovery v0.2 — Development + Untouched",
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
                "variant_count": 504,
                "bias_methods": ["momentum_24h", "momentum_72h", "ema_20_50", "range_mid_20"],
                "development_fraction": 2.0 / 3.0,
                "untouched_fraction": 1.0 / 3.0,
            },
            "reliability": {
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "progress_percent": 0.0,
                "message": "Queued for H1 4CCB bias discovery",
            },
        })
        run_id = str(run["id"])
        task = asyncio.create_task(_run_analysis(repo, run_id, request, date_from, date_to), name=f"four-ccb-h1-bias-{run_id}")
        tasks[run_id] = task
        task.add_done_callback(lambda _: tasks.pop(run_id, None))
        return {"ok": True, "data": _public_run(run), "message": "4CCB H1 bias discovery queued"}

    @router.get("/api/research/4ccb-h1-bias/status")
    async def latest_research() -> dict[str, Any]:
        recent = await repo.list_backtest_runs(100)
        run = next((candidate for candidate in recent if (candidate.get("settings") or {}).get("strategy") == STRATEGY_CODE), None)
        return {"ok": True, "data": _public_run(run) if run else None}

    @router.get("/api/research/4ccb-h1-bias/{run_id}")
    async def get_research(run_id: str) -> dict[str, Any]:
        run = await repo.get_backtest_run(run_id)
        if not run or (run.get("settings") or {}).get("strategy") != STRATEGY_CODE:
            raise HTTPException(status_code=404, detail="4CCB H1 bias research run not found")
        return {"ok": True, "data": _public_run(run)}

    return router
