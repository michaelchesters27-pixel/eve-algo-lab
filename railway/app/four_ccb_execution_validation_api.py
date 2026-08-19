from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.four_ccb_execution_validation import (
    ENGINE_VERSION,
    STRATEGY_CODE,
    ExecutionSignal,
    ExecutionTrade,
    FourCCBH1M1ExecutionValidator,
)


class FourCCBM1ExecutionRequest(BaseModel):
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


async def _fetch_window(repo: Any, symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = await repo.fetch_candles_page(
            symbol=symbol,
            interval="1min",
            after=cursor,
            date_from=start.isoformat() if cursor is None else None,
            date_to=end.isoformat(),
            limit=1000,
        )
        if not page:
            break
        rows.extend(page)
        cursor = str(page[-1]["candle_time"])
        if len(page) < 1000:
            break
    return rows


async def _load_h1(repo: Any, symbol: str, date_from: str, date_to: str, total_rows: int, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    processed = 0
    page_number = 0
    while True:
        page = await repo.fetch_candles_page(
            symbol=symbol,
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
            await repo.update_backtest_run(
                run_id,
                reliability={
                    "engine_version": ENGINE_VERSION,
                    "strategy": STRATEGY_CODE,
                    "input_interval": "1h + 1min execution replay",
                    "progress_percent": round(min(20.0, 20.0 * processed / max(1, total_rows)), 3),
                    "message": f"Loaded {processed:,}/{total_rows:,} H1 candles",
                },
            )
        if len(page) < 1000:
            break
    return rows


async def _run_analysis(repo: Any, run_id: str, request: FourCCBM1ExecutionRequest, date_from: str, date_to: str) -> None:
    try:
        total_h1 = await repo.count_market_candles(request.symbol, "1h", date_from, date_to)
        if total_h1 < 1000:
            raise RuntimeError("Stored H1 history is too short for 4CCB M1 execution validation")

        m1_state = await repo.get_state(request.symbol, "1min")
        m1_total = await repo.count_market_candles(request.symbol, "1min")
        if m1_total <= 0:
            raise RuntimeError("No stored XAU/USD M1 candles are available. Complete M1 Market Memory before execution validation.")

        await repo.update_backtest_run(
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "input_interval": "1h + 1min execution replay",
                "progress_percent": 0.0,
                "message": f"Loading {total_h1:,} H1 candles; M1 store currently contains {m1_total:,} rows",
            },
        )

        h1_rows = await _load_h1(repo, request.symbol, date_from, date_to, total_h1, run_id)
        validator = FourCCBH1M1ExecutionValidator(h1_rows)
        signals = validator.signals()
        if not signals:
            raise RuntimeError("Frozen v0.4 rules produced no H1 signals")

        await repo.update_backtest_run(
            run_id,
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "input_interval": "1h + 1min execution replay",
                "progress_percent": 25.0,
                "message": f"Generated {len(signals)} frozen H1 signals; replaying only their execution windows on stored M1",
            },
        )

        trades: list[ExecutionTrade] = []
        unresolved = 0
        skipped_while_open = 0
        m1_rows_loaded = 0
        active_until: datetime | None = None

        for number, signal in enumerate(signals, start=1):
            if active_until is not None and signal.entry_time <= active_until:
                skipped_while_open += 1
                continue

            rows = await _fetch_window(repo, request.symbol, signal.entry_time, signal.hold_end_time)
            m1_rows_loaded += len(rows)
            trade = validator.replay_signal(signal, rows)
            if trade is None:
                unresolved += 1
            else:
                trades.append(trade)
                active_until = trade.exit_time

            if number % 5 == 0 or number == len(signals):
                current = await repo.get_backtest_run(run_id)
                if current and current.get("status") == "cancelled":
                    return
                progress = 25.0 + 65.0 * number / len(signals)
                await repo.update_backtest_run(
                    run_id,
                    reliability={
                        "engine_version": ENGINE_VERSION,
                        "strategy": STRATEGY_CODE,
                        "input_interval": "1h + 1min execution replay",
                        "progress_percent": round(min(90.0, progress), 3),
                        "message": (
                            f"M1 replay {number}/{len(signals)} signals · {len(trades)} resolved · "
                            f"{unresolved} unresolved · {skipped_while_open} skipped while position open"
                        ),
                    },
                )

        report = validator.report(
            h1_rows,
            signals,
            trades,
            unresolved,
            skipped_while_open,
            m1_rows_loaded,
            m1_state,
        )
        report["source"] = {
            "symbol": request.symbol,
            "h1_date_from": date_from,
            "h1_date_to": date_to,
            "h1_rows_scanned": len(h1_rows),
            "m1_total_rows_in_store": m1_total,
            "m1_rows_loaded_across_signal_windows": m1_rows_loaded,
        }

        baseline = report["cost_stress"]["baseline_0p05"]["overall"]
        later = report["cost_stress"]["baseline_0p05"]["2024_plus"]
        await repo.update_backtest_run(
            run_id,
            status="complete",
            total_positions=int(baseline["trades"]),
            total_baskets=int(baseline["trades"]),
            winning_baskets=int(baseline["wins"]),
            losing_baskets=int(baseline["losses"]),
            basket_win_rate=float(baseline["win_rate_pct"]),
            expectancy=float(baseline["expectancy_r"]),
            finished_at=datetime.now(timezone.utc).isoformat(),
            reliability={
                "engine_version": ENGINE_VERSION,
                "strategy": STRATEGY_CODE,
                "accuracy": "H1 signals with stored M1 execution replay; same-M1 stop/target ambiguity is resolved against the strategy by assuming stop first.",
                "input_interval": "1h + 1min execution replay",
                "progress_percent": 100.0,
                "message": (
                    f"Complete · {len(trades)} M1-replayed trades · 2024+ PF {later['profit_factor']} · "
                    f"resolved {report['data']['resolved_rate']:.1%} · {report['verdict']}"
                ),
                "research_report": report,
            },
        )
        await repo.log_event(
            "success",
            "4ccb-h1-m1-execution",
            "4CCB M1 execution validation completed",
            {
                "run_id": run_id,
                "verdict": report["verdict"],
                "signals": len(signals),
                "resolved_trades": len(trades),
                "unresolved": unresolved,
                "baseline_2024_plus_pf": later["profit_factor"],
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
                "message": f"4CCB M1 execution validation failed: {exc}",
            },
        )
        await repo.log_event("error", "4ccb-h1-m1-execution", "4CCB M1 execution validation failed", {"run_id": run_id, "error": str(exc)})


def build_four_ccb_execution_router(repo: Any, require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter()
    tasks: dict[str, asyncio.Task[Any]] = {}

    @router.post("/api/research/4ccb-h1-m1/run", dependencies=[Depends(require_admin)])
    async def start_research(request: FourCCBM1ExecutionRequest) -> dict[str, Any]:
        h1_state = await repo.get_state(request.symbol, "1h")
        if not _is_ready(h1_state):
            raise HTTPException(status_code=409, detail="Complete H1 Market Memory is required before 4CCB M1 execution validation can run")
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
            raise HTTPException(status_code=409, detail=f"4CCB M1 execution validation is already running ({active['id']})")

        date_from = str(h1_state["oldest_stored"])
        date_to = str(h1_state["latest_stored"])
        run = await repo.create_backtest_run(
            {
                "name": "4CCB H1 → M1 Execution Validation v0.5",
                "symbol": request.symbol,
                "interval": "1min",
                "resolution": "candle",
                "status": "queued",
                "date_from": date_from,
                "date_to": date_to,
                "settings": {
                    "strategy": STRATEGY_CODE,
                    "engine_version": ENGINE_VERSION,
                    "research_only": True,
                    "signal_timeframe": "H1",
                    "execution_timeframe": "M1",
                    "frozen_from": "v0.4 director audit",
                    "breakout_excess_atr_min": 0.10,
                    "cost_price_scenarios": [0.05, 0.10, 0.15],
                    "same_m1_ambiguity": "stop_first",
                    "note": "Execution validation of a reverse-engineered public-chart hypothesis; not represented as private/VIP rules.",
                },
                "reliability": {
                    "engine_version": ENGINE_VERSION,
                    "strategy": STRATEGY_CODE,
                    "progress_percent": 0.0,
                    "message": "Queued for H1 signal → M1 execution validation",
                },
            }
        )
        run_id = str(run["id"])
        task = asyncio.create_task(_run_analysis(repo, run_id, request, date_from, date_to), name=f"four-ccb-h1-m1-{run_id}")
        tasks[run_id] = task
        task.add_done_callback(lambda _: tasks.pop(run_id, None))
        return {"ok": True, "data": _public_run(run), "message": "4CCB M1 execution validation queued"}

    @router.get("/api/research/4ccb-h1-m1/status")
    async def latest_research() -> dict[str, Any]:
        recent = await repo.list_backtest_runs(100)
        run = next((candidate for candidate in recent if (candidate.get("settings") or {}).get("strategy") == STRATEGY_CODE), None)
        return {"ok": True, "data": _public_run(run) if run else None}

    @router.get("/api/research/4ccb-h1-m1/{run_id}")
    async def get_research(run_id: str) -> dict[str, Any]:
        run = await repo.get_backtest_run(run_id)
        if not run or (run.get("settings") or {}).get("strategy") != STRATEGY_CODE:
            raise HTTPException(status_code=404, detail="4CCB M1 execution validation run not found")
        return {"ok": True, "data": _public_run(run)}

    return router
