from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

import httpx


class SupabaseError(RuntimeError):
    pass


class SupabaseRepository:
    """Small async PostgREST client using the Supabase service-role key."""

    def __init__(self, url: str, service_role_key: str, timeout_seconds: float = 45.0) -> None:
        self.base_url = f"{url.rstrip('/')}/rest/v1"
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        response = await self.client.request(method, f"{self.base_url}/{path.lstrip('/')}", headers=headers, **kwargs)
        if response.status_code >= 400:
            detail = response.text[:1500]
            raise SupabaseError(f"Supabase {response.status_code}: {detail}")
        return response

    async def insert(self, table: str, payload: dict[str, Any] | list[dict[str, Any]]) -> Any:
        response = await self._request(
            "POST",
            table,
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        return response.json()

    async def upsert(
        self,
        table: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        on_conflict: str,
        return_representation: bool = False,
    ) -> Any:
        prefer = "resolution=merge-duplicates,return=representation" if return_representation else "resolution=merge-duplicates,return=minimal"
        response = await self._request(
            "POST",
            f"{table}?on_conflict={quote(on_conflict, safe=',')}",
            json=payload,
            headers={"Prefer": prefer},
        )
        if not response.content:
            return None
        return response.json()

    async def update(self, table: str, filters: str, payload: dict[str, Any], return_representation: bool = False) -> Any:
        prefer = "return=representation" if return_representation else "return=minimal"
        response = await self._request(
            "PATCH",
            f"{table}?{filters}",
            json=payload,
            headers={"Prefer": prefer},
        )
        if not response.content:
            return None
        return response.json()

    async def select(self, table: str, query: str) -> list[dict[str, Any]]:
        response = await self._request("GET", f"{table}?{query}")
        return response.json()

    async def delete(self, table: str, filters: str) -> None:
        await self._request(
            "DELETE",
            f"{table}?{filters}",
            headers={"Prefer": "return=minimal"},
        )

    async def rpc(self, function_name: str, payload: dict[str, Any]) -> Any:
        response = await self._request("POST", f"rpc/{function_name}", json=payload)
        if not response.content:
            return None
        return response.json()

    async def log_event(self, level: str, component: str, message: str, details: dict[str, Any] | None = None) -> None:
        await self.insert(
            "system_events",
            {
                "level": level,
                "component": component,
                "message": message,
                "details": details or {},
            },
        )

    async def create_job(self, job_type: str, symbol: str, interval: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = await self.insert(
            "ingestion_jobs",
            {
                "job_type": job_type,
                "symbol": symbol,
                "interval": interval,
                "parameters": parameters or {},
                "status": "queued",
                "message": "Waiting for Railway worker",
            },
        )
        return rows[0]

    async def has_active_job(self, job_type: str, symbol: str, interval: str) -> bool:
        rows = await self.select(
            "ingestion_jobs",
            "select=id&job_type=eq.{}&symbol=eq.{}&interval=eq.{}&status=in.(queued,running)&limit=1".format(
                quote(job_type, safe=""), quote(symbol, safe=""), quote(interval, safe="")
            ),
        )
        return bool(rows)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        rows = await self.select("ingestion_jobs", f"select=*&id=eq.{quote(job_id, safe='')}&limit=1")
        return rows[0] if rows else None

    async def get_latest_job(
        self,
        symbol: str,
        interval: str,
        job_type: str | None = None,
    ) -> dict[str, Any] | None:
        filters = [
            "select=*",
            f"symbol=eq.{quote(symbol, safe='')}",
            f"interval=eq.{quote(interval, safe='')}",
        ]
        if job_type:
            filters.append(f"job_type=eq.{quote(job_type, safe='')}")
        filters.extend(["order=requested_at.desc", "limit=1"])
        rows = await self.select("ingestion_jobs", "&".join(filters))
        return rows[0] if rows else None

    async def cancel_job(self, job_id: str) -> dict[str, Any] | None:
        rows = await self.update(
            "ingestion_jobs",
            f"id=eq.{quote(job_id, safe='')}&status=in.(queued,running)",
            {
                "status": "cancelled",
                "message": "Cancellation requested",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
            return_representation=True,
        )
        return rows[0] if rows else None

    async def claim_next_job(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.rpc("claim_next_ingestion_job", {"p_worker_id": worker_id})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def update_job(self, job_id: str, **changes: Any) -> None:
        changes["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        await self.update("ingestion_jobs", f"id=eq.{quote(job_id, safe='')}", changes)

    async def get_state(self, symbol: str, interval: str) -> dict[str, Any] | None:
        rows = await self.select(
            "ingestion_state",
            "select=*&symbol=eq.{}&interval=eq.{}&limit=1".format(quote(symbol, safe=""), quote(interval, safe="")),
        )
        return rows[0] if rows else None

    async def upsert_state(self, symbol: str, interval: str, **changes: Any) -> None:
        # Patch existing state so omitted fields are never reset during a long resumable job.
        existing = await self.get_state(symbol, interval)
        if existing:
            filters = "symbol=eq.{}&interval=eq.{}".format(
                quote(symbol, safe=""), quote(interval, safe="")
            )
            await self.update("ingestion_state", filters, changes)
            return
        await self.insert("ingestion_state", {"symbol": symbol, "interval": interval, **changes})

    async def refresh_state(self, symbol: str, interval: str) -> None:
        await self.rpc("refresh_ingestion_state", {"p_symbol": symbol, "p_interval": interval})

    async def scan_gaps(self, symbol: str, interval: str, interval_seconds: int) -> dict[str, Any]:
        result = await self.rpc(
            "scan_market_gaps",
            {"p_symbol": symbol, "p_interval": interval, "p_interval_seconds": interval_seconds},
        )
        return result or {"total": 0, "review": 0}

    async def dashboard(self, symbol: str, interval: str) -> dict[str, Any]:
        result = await self.rpc("get_market_dashboard", {"p_symbol": symbol, "p_interval": interval})
        return result or {}

    async def reset_stale_jobs(self, stale_minutes: int = 10) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
        # A service restart can leave a running job behind. Returning stale jobs to queued makes backfill resumable.
        await self.update(
            "ingestion_jobs",
            f"status=eq.running&or=(heartbeat_at.is.null,heartbeat_at.lt.{quote(cutoff, safe=':-TZ')})",
            {
                "status": "queued",
                "worker_id": None,
                "message": "Recovered after worker restart",
            },
        )

    async def bulk_upsert_candles(self, rows: list[dict[str, Any]], chunk_size: int = 1000) -> None:
        for start in range(0, len(rows), chunk_size):
            await self.upsert(
                "market_candles",
                rows[start : start + chunk_size],
                "symbol,interval,candle_time",
            )

    async def get_strategy_by_slug(self, slug: str) -> dict[str, Any] | None:
        rows = await self.select("strategies", f"select=*&slug=eq.{quote(slug, safe='')}&limit=1")
        return rows[0] if rows else None

    async def create_strategy(self, name: str, slug: str, description: str) -> dict[str, Any]:
        rows = await self.insert(
            "strategies",
            {"name": name, "slug": slug, "description": description, "status": "testing"},
        )
        return rows[0]

    async def get_strategy_version(self, strategy_id: str, version: str) -> dict[str, Any] | None:
        rows = await self.select(
            "strategy_versions",
            "select=*&strategy_id=eq.{}&version=eq.{}&limit=1".format(
                quote(strategy_id, safe=""), quote(version, safe="")
            ),
        )
        return rows[0] if rows else None

    async def create_strategy_version(
        self,
        strategy_id: str,
        version: str,
        rules: dict[str, Any],
        source_sha256: str,
        notes: str,
    ) -> dict[str, Any]:
        rows = await self.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "version": version,
                "rules": rules,
                "source_sha256": source_sha256,
                "notes": notes,
            },
        )
        return rows[0]

    async def create_backtest_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = await self.insert("backtest_runs", payload)
        return rows[0]

    async def update_backtest_run(self, run_id: str, **changes: Any) -> None:
        await self.update("backtest_runs", f"id=eq.{quote(run_id, safe='')}", changes)

    async def get_backtest_run(self, run_id: str) -> dict[str, Any] | None:
        rows = await self.select("backtest_runs", f"select=*&id=eq.{quote(run_id, safe='')}&limit=1")
        return rows[0] if rows else None

    async def list_backtest_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(100, int(limit)))
        return await self.select("backtest_runs", f"select=*&order=created_at.desc&limit={safe_limit}")

    async def has_active_backtest(self) -> bool:
        rows = await self.select("backtest_runs", "select=id&status=in.(queued,running)&limit=1")
        return bool(rows)

    async def count_market_candles(
        self,
        symbol: str,
        interval: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        filters = [
            f"symbol=eq.{quote(symbol, safe='')}",
            f"interval=eq.{quote(interval, safe='')}",
        ]
        if date_from:
            filters.append(f"candle_time=gte.{quote(str(date_from), safe=':-TZ.')}")
        if date_to:
            filters.append(f"candle_time=lte.{quote(str(date_to), safe=':-TZ.')}")
        response = await self._request(
            "HEAD",
            f"market_candles?select=candle_time&{'&'.join(filters)}",
            headers={"Prefer": "count=exact"},
        )
        content_range = response.headers.get("content-range", "0-0/0")
        try:
            return int(content_range.rsplit("/", 1)[1])
        except (IndexError, ValueError):
            return 0

    async def fetch_candles_page(
        self,
        symbol: str,
        interval: str,
        after: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(1000, int(limit)))
        filters = [
            "select=candle_time,open,high,low,close,volume",
            f"symbol=eq.{quote(symbol, safe='')}",
            f"interval=eq.{quote(interval, safe='')}",
        ]
        if after:
            filters.append(f"candle_time=gt.{quote(str(after), safe=':-TZ.')}")
        elif date_from:
            filters.append(f"candle_time=gte.{quote(str(date_from), safe=':-TZ.')}")
        if date_to:
            filters.append(f"candle_time=lte.{quote(str(date_to), safe=':-TZ.')}")
        filters.extend(["order=candle_time.asc", f"limit={safe_limit}"])
        return await self.select("market_candles", "&".join(filters))

    async def bulk_insert_backtest_trades(self, rows: list[dict[str, Any]], chunk_size: int = 500) -> None:
        for start in range(0, len(rows), chunk_size):
            await self.insert("backtest_trades", rows[start : start + chunk_size])

    async def bulk_insert_backtest_baskets(self, rows: list[dict[str, Any]], chunk_size: int = 500) -> None:
        for start in range(0, len(rows), chunk_size):
            await self.insert("backtest_baskets", rows[start : start + chunk_size])

    async def list_backtest_baskets(self, run_id: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        return await self.select(
            "backtest_baskets",
            f"select=*&backtest_run_id=eq.{quote(run_id, safe='')}&order=opened_at.desc&limit={safe_limit}",
        )

    async def list_backtest_trades(self, run_id: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        return await self.select(
            "backtest_trades",
            f"select=*&backtest_run_id=eq.{quote(run_id, safe='')}&order=opened_at.desc&limit={safe_limit}",
        )

    async def create_learning_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = await self.insert("learning_runs", payload)
        return rows[0]

    async def has_active_learning_run(self, symbol: str, snapshot_interval: str) -> bool:
        rows = await self.select(
            "learning_runs",
            "select=id&symbol=eq.{}&snapshot_interval=eq.{}&status=in.(queued,running)&limit=1".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        return bool(rows)

    async def claim_next_learning_run(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.rpc("claim_next_learning_run", {"p_worker_id": worker_id})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def get_learning_run(self, run_id: str) -> dict[str, Any] | None:
        rows = await self.select("learning_runs", f"select=*&id=eq.{quote(run_id, safe='')}&limit=1")
        return rows[0] if rows else None

    async def list_learning_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(100, int(limit)))
        return await self.select("learning_runs", f"select=*&order=requested_at.desc&limit={safe_limit}")

    async def update_learning_run(self, run_id: str, **changes: Any) -> None:
        changes["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        await self.update("learning_runs", f"id=eq.{quote(run_id, safe='')}", changes)

    async def cancel_learning_run(self, run_id: str) -> dict[str, Any] | None:
        rows = await self.update(
            "learning_runs",
            f"id=eq.{quote(run_id, safe='')}&status=in.(queued,running)",
            {
                "status": "cancelled",
                "stage": "cancelled",
                "message": "Learning build cancellation requested",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
            return_representation=True,
        )
        return rows[0] if rows else None

    async def reset_stale_learning_runs(self, stale_minutes: int = 10) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
        await self.update(
            "learning_runs",
            f"status=eq.running&or=(heartbeat_at.is.null,heartbeat_at.lt.{quote(cutoff, safe=':-TZ')})",
            {
                "status": "queued",
                "worker_id": None,
                "message": "Recovered after Railway restart",
            },
        )

    async def get_learning_state(self, symbol: str, snapshot_interval: str) -> dict[str, Any] | None:
        rows = await self.select(
            "learning_state",
            "select=*&symbol=eq.{}&snapshot_interval=eq.{}&limit=1".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        return rows[0] if rows else None

    async def upsert_learning_state(self, symbol: str, snapshot_interval: str, **changes: Any) -> None:
        existing = await self.get_learning_state(symbol, snapshot_interval)
        if existing:
            await self.update(
                "learning_state",
                "symbol=eq.{}&snapshot_interval=eq.{}".format(
                    quote(symbol, safe=""), quote(snapshot_interval, safe="")
                ),
                changes,
            )
            return
        await self.insert(
            "learning_state",
            {"symbol": symbol, "snapshot_interval": snapshot_interval, **changes},
        )

    async def refresh_learning_state(self, symbol: str, snapshot_interval: str) -> None:
        await self.rpc(
            "refresh_learning_state",
            {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval},
        )

    async def learning_dashboard(self, symbol: str, snapshot_interval: str) -> dict[str, Any]:
        result = await self.rpc(
            "get_learning_dashboard",
            {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval},
        )
        return result or {}

    async def bulk_upsert_learning_snapshots(self, rows: list[dict[str, Any]], chunk_size: int = 500) -> None:
        for start in range(0, len(rows), chunk_size):
            await self.upsert(
                "market_learning_snapshots",
                rows[start:start + chunk_size],
                "symbol,snapshot_interval,candle_time",
            )

    async def replace_calendar_statistics(self, symbol: str, rows: list[dict[str, Any]]) -> None:
        await self.delete("calendar_statistics", f"symbol=eq.{quote(symbol, safe='')}")
        for start in range(0, len(rows), 250):
            await self.upsert(
                "calendar_statistics",
                rows[start:start + 250],
                "symbol,dimension,bucket_key",
            )

    async def upsert_research_questions(self, rows: list[dict[str, Any]]) -> None:
        # Questions are few. Upserting one at a time lets PostgreSQL apply defaults
        # while preserving fields such as a human-reviewed status.
        for row in rows:
            await self.upsert("research_questions", row, "question_key")

    async def upsert_discoveries(self, rows: list[dict[str, Any]]) -> None:
        # Preserve any later validation status while refreshing the evidence.
        for row in rows:
            await self.upsert("discoveries", row, "discovery_key")

    async def delete_learning_generated_data(self, symbol: str, snapshot_interval: str) -> None:
        await self.delete(
            "market_learning_snapshots",
            "symbol=eq.{}&snapshot_interval=eq.{}".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        await self.delete("calendar_statistics", f"symbol=eq.{quote(symbol, safe='')}")
        await self.delete("research_questions", f"symbol=eq.{quote(symbol, safe='')}")
        await self.delete("discoveries", f"symbol=eq.{quote(symbol, safe='')}")
        await self.upsert_learning_state(
            symbol,
            snapshot_interval,
            status="not_started",
            initial_build_complete=False,
            last_snapshot_time=None,
            snapshots_count=0,
            complete_outcomes_count=0,
            outcome_labels_count=0,
            calendar_stat_count=0,
            question_count=0,
            discovery_count=0,
        )

    async def fetch_learning_snapshots_page(
        self,
        symbol: str,
        snapshot_interval: str,
        after: str | None = None,
        complete_only: bool = False,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(1000, int(limit)))
        filters = [
            "select=symbol,snapshot_interval,candle_time,weekday,month,quarter,hour_utc,session,direction,compression_ratio,trend_12_atr,trend_48_atr,streak,regime,alignment_score,outcomes,outcome_complete",
            f"symbol=eq.{quote(symbol, safe='')}",
            f"snapshot_interval=eq.{quote(snapshot_interval, safe='')}",
        ]
        if after:
            filters.append(f"candle_time=gt.{quote(str(after), safe=':-TZ.')}")
        if complete_only:
            filters.append("outcome_complete=eq.true")
        filters.extend(["order=candle_time.asc", f"limit={safe_limit}"])
        return await self.select("market_learning_snapshots", "&".join(filters))

    async def get_latest_learning_snapshot(self, symbol: str, snapshot_interval: str) -> dict[str, Any] | None:
        rows = await self.select(
            "market_learning_snapshots",
            "select=*&symbol=eq.{}&snapshot_interval=eq.{}&order=candle_time.desc&limit=1".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        return rows[0] if rows else None

    async def get_learning_snapshot(self, symbol: str, snapshot_interval: str, candle_time: str) -> dict[str, Any] | None:
        rows = await self.select(
            "market_learning_snapshots",
            "select=*&symbol=eq.{}&snapshot_interval=eq.{}&candle_time=eq.{}&limit=1".format(
                quote(symbol, safe=""),
                quote(snapshot_interval, safe=""),
                quote(str(candle_time), safe=":-TZ."),
            ),
        )
        return rows[0] if rows else None

    async def list_research_questions(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        return await self.select(
            "research_questions",
            f"select=*&symbol=eq.{quote(symbol, safe='')}&status=neq.archived&order=priority.desc,generated_at.asc&limit={safe_limit}",
        )

    async def update_research_question(self, question_id: str, **changes: Any) -> None:
        await self.update("research_questions", f"id=eq.{quote(question_id, safe='')}", changes)

    async def upsert_model(self, payload: dict[str, Any]) -> None:
        await self.upsert("model_registry", payload, "model_key")

    async def get_model(self, model_key: str) -> dict[str, Any] | None:
        rows = await self.select(
            "model_registry",
            f"select=*&model_key=eq.{quote(model_key, safe='')}&limit=1",
        )
        return rows[0] if rows else None

    async def promote_model(
        self,
        symbol: str,
        snapshot_interval: str,
        new_model_key: str,
        previous_model_key: str | None,
    ) -> None:
        if previous_model_key and previous_model_key != new_model_key:
            await self.update(
                "model_registry",
                f"model_key=eq.{quote(previous_model_key, safe='')}",
                {"role": "retired", "status": "retired"},
            )
        await self.update(
            "model_registry",
            f"model_key=eq.{quote(new_model_key, safe='')}",
            {
                "role": "approved",
                "status": "ready",
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self.upsert_learning_state(
            symbol,
            snapshot_interval,
            approved_model_key=new_model_key,
            challenger_model_key=None,
            model_promotions_count=int((await self.get_learning_state(symbol, snapshot_interval) or {}).get("model_promotions_count") or 0) + 1,
        )

    async def upsert_prediction(self, payload: dict[str, Any]) -> bool:
        existing = await self.select(
            "prediction_ledger",
            "select=id&symbol=eq.{}&model_key=eq.{}&snapshot_time=eq.{}&horizon_minutes=eq.{}&limit=1".format(
                quote(str(payload["symbol"]), safe=""),
                quote(str(payload["model_key"]), safe=""),
                quote(str(payload["snapshot_time"]), safe=":-TZ."),
                int(payload["horizon_minutes"]),
            ),
        )
        if existing:
            return False
        await self.insert("prediction_ledger", payload)
        return True

    async def list_pending_predictions(self, symbol: str, limit: int = 300) -> list[dict[str, Any]]:
        safe_limit = max(1, min(1000, int(limit)))
        return await self.select(
            "prediction_ledger",
            f"select=*&symbol=eq.{quote(symbol, safe='')}&status=eq.pending&order=snapshot_time.asc&limit={safe_limit}",
        )

    async def grade_prediction(self, prediction_id: str, **changes: Any) -> None:
        changes.update({
            "status": "graded",
            "graded_at": datetime.now(timezone.utc).isoformat(),
        })
        await self.update("prediction_ledger", f"id=eq.{quote(prediction_id, safe='')}", changes)

    async def create_autonomous_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = await self.insert("autonomous_runs", payload)
        return rows[0]

    async def update_autonomous_run(self, run_id: str, **changes: Any) -> None:
        changes["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        await self.update("autonomous_runs", f"id=eq.{quote(run_id, safe='')}", changes)

    async def upsert_research_report(self, payload: dict[str, Any]) -> None:
        await self.upsert("autonomous_research_reports", payload, "symbol,report_date")

    async def refresh_autonomous_learning_state(self, symbol: str, snapshot_interval: str) -> None:
        await self.rpc(
            "refresh_autonomous_learning_state",
            {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval},
        )

    async def fail_interrupted_backtests(self) -> None:
        await self.update(
            "backtest_runs",
            "status=in.(queued,running)",
            {
                "status": "failed",
                "error": "Railway restarted before this backtest completed. Start a new run; saved historical data is unaffected.",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "reliability": {
                    "progress_percent": 0,
                    "message": "Interrupted by Railway restart",
                    "accuracy": "Backtest interrupted before completion",
                },
            },
        )
