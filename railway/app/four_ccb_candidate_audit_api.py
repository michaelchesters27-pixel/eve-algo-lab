from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.four_ccb_candidate_audit import ENGINE_VERSION, STRATEGY_CODE, FourCCBH1CandidateAudit


class FourCCBH1CandidateAuditRequest(BaseModel):
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


async def _run_analysis(repo: Any, run_id: str, request: FourCCBH1CandidateAuditRequest, date_from: str, date_to: str) -> None:
    try:
        total_rows = await repo.count_market_candles(request.symbol, "1h", date_from, date_to)
        if total_rows < 1000:
            raise RuntimeError("Stored H1 history is too short for the 4CCB candidate audit")
        await repo.update_backtest_run(
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "input_interval": "1h",
                "progress_percent": 0.0,
                "message": f"Loading {total_rows:,} stored H1 candles for fixed-candidate robustness audit",
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
                "message": "Auditing four frozen candidates by year, side, session and predeclared context filters",
            },
        )
        report = await asyncio.to_thread(FourCCBH1CandidateAudit(rows).run)
        report["source"] = {
            "symbol": request.symbol,
            "interval": "1h",
            "date_from": date_from,
            "date_to": date_to,
            "rows_scanned": processed,
        }
        primary = next(item for item in report["candidates"] if item["code"] == "mb_small_ema_close_1p25_2r")
        overall = primary["overall"]
        recent = primary["2025_2026"]
        selected_filter = primary["context_filter_audit"]["selected"]
        await repo.update_backtest_run(
            run_id,
            status="complete",
            total_positions=int(overall["trades"]),
            total_baskets=int(overall["trades"]),
            winning_baskets=int(overall["wins"]),
            losing_baskets=int(overall["losses"]),
            basket_win_rate=float(overall["win_rate_pct"]),
            expectancy=float(overall["expectancy_r"]),
            finished_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "accuracy": "Fixed-rule H1 OHLC robustness audit with chronological context-filter discipline; M1/tick replay remains mandatory before execution.",
                "input_interval": "1h",
                "progress_percent": 100.0,
                "message": (
                    f"Complete · primary recent PF {recent['profit_factor']} · "
                    f"selected context {selected_filter['filter']} · later PF {selected_filter['later_2024_plus']['profit_factor']} · {report['verdict']}"
                ),
                "research_report": report,
            },
        )
        await repo.log_event(
            "success",
            "4ccb-h1-candidate-audit",
            "4CCB fixed-candidate robustness audit completed",
            {
                "run_id": run_id,
                "verdict": report["verdict"],
                "primary_recent_trades": recent["trades"],
                "primary_recent_pf": recent["profit_factor"],
                "selected_context": selected_filter["filter"],
                "selected_context_later_pf": selected_filter["later_2024_plus"]["profit_factor"],
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
                "message": f"4CCB candidate audit failed: {exc}",
            },
        )
        await repo.log_event("error", "4ccb-h1-candidate-audit", "4CCB candidate audit failed", {"run_id": run_id, "error": str(exc)})


def build_four_ccb_candidate_audit_router(repo: Any, require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter()
    tasks: dict[str, asyncio.Task[Any]] = {}

    @router.post("/api/research/4ccb-h1-audit/run", dependencies=[Depends(require_admin)])
    async def start_research(request: FourCCBH1CandidateAuditRequest) -> dict[str, Any]:
        state = await repo.get_state(request.symbol, "1h")
        if not _is_ready(state):
            raise HTTPException(status_code=409, detail="Complete H1 Market Memory is required before the 4CCB candidate audit can run")
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
            raise HTTPException(status_code=409, detail=f"4CCB candidate audit is already running ({active['id']})")

        date_from = str(state["oldest_stored"])
        date_to = str(state["latest_stored"])
        run = await repo.create_backtest_run(
            {
                "name": "4CCB H1 Fixed Candidate Robustness Audit v0.4",
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
                    "candidate_count": 4,
                    "primary_candidate": "mother bar + small bodies + EMA20/50 bias + close breakout + 1.25 ATR + 2R",
                    "context_filters_predeclared": 9,
                    "context_training_period": "2020-2023",
                    "context_confirmation_period": "2024+",
                    "note": "Fixed-candidate reverse-engineering audit; not represented as private/VIP rules.",
                },
                "reliability": {
                    "engine_version": ENGINE_VERSION,
                    "strategy": STRATEGY_CODE,
                    "progress_percent": 0.0,
                    "message": "Queued for fixed 4CCB candidate robustness audit",
                },
            }
        )
        run_id = str(run["id"])
        task = asyncio.create_task(_run_analysis(repo, run_id, request, date_from, date_to), name=f"four-ccb-h1-audit-{run_id}")
        tasks[run_id] = task
        task.add_done_callback(lambda _: tasks.pop(run_id, None))
        return {"ok": True, "data": _public_run(run), "message": "4CCB fixed-candidate audit queued"}

    @router.get("/api/research/4ccb-h1-audit/status")
    async def latest_research() -> dict[str, Any]:
        recent = await repo.list_backtest_runs(100)
        run = next((candidate for candidate in recent if (candidate.get("settings") or {}).get("strategy") == STRATEGY_CODE), None)
        return {"ok": True, "data": _public_run(run) if run else None}

    @router.get("/api/research/4ccb-h1-audit/{run_id}")
    async def get_research(run_id: str) -> dict[str, Any]:
        run = await repo.get_backtest_run(run_id)
        if not run or (run.get("settings") or {}).get("strategy") != STRATEGY_CODE:
            raise HTTPException(status_code=404, detail="4CCB candidate audit run not found")
        return {"ok": True, "data": _public_run(run)}

    return router
