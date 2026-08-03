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
            "select=symbol,snapshot_interval,candle_time,close,atr_14,weekday,month,quarter,week_of_month,hour_utc,session,direction,compression_ratio,trend_12_atr,trend_48_atr,streak,regime,alignment_score,outcomes,outcome_complete",
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

    async def get_historical_research_state(self, symbol: str, snapshot_interval: str) -> dict[str, Any] | None:
        rows = await self.select(
            "historical_research_state",
            "select=*&symbol=eq.{}&snapshot_interval=eq.{}&limit=1".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        return rows[0] if rows else None

    async def upsert_historical_research_state(self, symbol: str, snapshot_interval: str, **changes: Any) -> None:
        existing = await self.get_historical_research_state(symbol, snapshot_interval)
        if existing:
            await self.update(
                "historical_research_state",
                "symbol=eq.{}&snapshot_interval=eq.{}".format(
                    quote(symbol, safe=""), quote(snapshot_interval, safe="")
                ),
                changes,
            )
            return
        await self.insert(
            "historical_research_state",
            {"symbol": symbol, "snapshot_interval": snapshot_interval, **changes},
        )

    async def upsert_historical_research_jobs(self, rows: list[dict[str, Any]]) -> None:
        # Ignore duplicate job keys. Never reset an already tested hypothesis back
        # to queued when a later deterministic generation creates a collision.
        for start in range(0, len(rows), 250):
            await self._request(
                "POST",
                "historical_research_jobs?on_conflict=job_key",
                json=rows[start:start + 250],
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            )

    async def claim_next_historical_research_job(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.rpc("claim_next_historical_research_job", {"p_worker_id": worker_id})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def complete_historical_research_job(self, job_id: str, result: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.update(
            "historical_research_jobs",
            f"id=eq.{quote(job_id, safe='')}",
            {
                "status": "complete",
                "result_status": result.get("result_status"),
                "rows_scanned": int(result.get("rows_scanned") or 0),
                "sample_count": int(result.get("sample_count") or 0),
                "effect_size": result.get("effect_size"),
                "confidence_score": result.get("confidence_score"),
                "stability_score": result.get("stability_score"),
                "summary": result.get("summary"),
                "evidence": result.get("evidence") or {},
                "finished_at": now,
                "heartbeat_at": now,
                "error": None,
            },
        )

    async def fail_historical_research_job(self, job_id: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.update(
            "historical_research_jobs",
            f"id=eq.{quote(job_id, safe='')}",
            {
                "status": "failed",
                "finished_at": now,
                "heartbeat_at": now,
                "error": str(error)[:4000],
            },
        )

    async def reset_stale_historical_research_jobs(self, stale_minutes: int = 20) -> None:
        # Use a security-definer RPC rather than a direct PostgREST PATCH.
        # Newly-created RLS tables can be absent from the REST schema cache for a
        # short period after deployment; the RPC remains reliable and prevents
        # the historical worker from dying during startup.
        await self.rpc(
            "reset_stale_historical_research_jobs",
            {"p_stale_minutes": int(stale_minutes)},
        )

    async def refresh_historical_research_state(self, symbol: str, snapshot_interval: str) -> None:
        await self.rpc(
            "refresh_historical_research_state",
            {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval},
        )

    async def historical_research_dashboard(self, symbol: str, snapshot_interval: str) -> dict[str, Any]:
        result = await self.rpc(
            "get_historical_research_dashboard",
            {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval},
        )
        return result or {}

    async def list_historical_research_results(
        self,
        symbol: str,
        snapshot_interval: str,
        result_status: str = "all",
        order: str = "confidence",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        order_map = {
            "confidence": "confidence_score.desc.nullslast,finished_at.desc.nullslast",
            "stability": "stability_score.desc.nullslast,confidence_score.desc.nullslast",
            "sample": "sample_count.desc,confidence_score.desc.nullslast",
            "recent": "finished_at.desc.nullslast",
            "effect": "effect_size.desc.nullslast,confidence_score.desc.nullslast",
        }
        order_clause = order_map.get(order, order_map["confidence"])
        filters = [
            "select=id,job_key,generation,question,rationale,test_definition,result_status,rows_scanned,sample_count,effect_size,confidence_score,stability_score,summary,evidence,requested_at,started_at,finished_at",
            f"symbol=eq.{quote(symbol, safe='')}",
            f"snapshot_interval=eq.{quote(snapshot_interval, safe='')}",
            "status=eq.complete",
        ]
        if result_status in {"validated", "promising", "rejected"}:
            filters.append(f"result_status=eq.{result_status}")
        filters.extend([f"order={order_clause}", f"limit={safe_limit}"])
        return await self.select("historical_research_jobs", "&".join(filters))

    async def get_strategy_lab_state(self, symbol: str, snapshot_interval: str) -> dict[str, Any] | None:
        rows = await self.select(
            "strategy_lab_state",
            "select=*&symbol=eq.{}&snapshot_interval=eq.{}&limit=1".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        return rows[0] if rows else None

    async def upsert_strategy_lab_state(self, symbol: str, snapshot_interval: str, **changes: Any) -> None:
        existing = await self.get_strategy_lab_state(symbol, snapshot_interval)
        if existing:
            await self.update(
                "strategy_lab_state",
                "symbol=eq.{}&snapshot_interval=eq.{}".format(
                    quote(symbol, safe=""), quote(snapshot_interval, safe="")
                ),
                changes,
            )
            return
        await self.insert("strategy_lab_state", {"symbol": symbol, "snapshot_interval": snapshot_interval, **changes})

    async def refresh_strategy_lab_state(self, symbol: str, snapshot_interval: str) -> None:
        await self.rpc("refresh_strategy_lab_state", {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval})

    async def strategy_lab_dashboard(self, symbol: str, snapshot_interval: str) -> dict[str, Any]:
        result = await self.rpc("get_strategy_lab_dashboard", {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval})
        return result or {}

    async def list_strategy_source_research(self, symbol: str, snapshot_interval: str, limit: int = 250) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        return await self.select(
            "historical_research_jobs",
            "select=id,job_key,symbol,snapshot_interval,question,test_definition,result_status,effect_size,confidence_score,stability_score,evidence"
            f"&symbol=eq.{quote(symbol, safe='')}&snapshot_interval=eq.{quote(snapshot_interval, safe='')}"
            f"&status=eq.complete&result_status=in.(validated,promising)&order=confidence_score.desc.nullslast&limit={safe_limit}",
        )

    async def upsert_strategy_candidates(self, rows: list[dict[str, Any]]) -> None:
        # Candidate keys are immutable experiment identities. Ignore duplicates so
        # a queue refill can never reset a completed candidate back to queued.
        for start in range(0, len(rows), 250):
            await self._request(
                "POST",
                "strategy_candidates?on_conflict=candidate_key",
                json=rows[start:start + 250],
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            )

    async def claim_next_strategy_candidate(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.rpc("claim_next_strategy_candidate", {"p_worker_id": worker_id})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def complete_strategy_candidate(self, candidate_id: str, result: dict[str, Any]) -> None:
        await self.update(
            "strategy_candidates", f"id=eq.{quote(candidate_id, safe='')}",
            {"status": "complete", "finished_at": datetime.now(timezone.utc).isoformat(), "heartbeat_at": datetime.now(timezone.utc).isoformat(), "error": None, **result},
        )

    async def fail_strategy_candidate(self, candidate_id: str, error: str) -> None:
        await self.update(
            "strategy_candidates", f"id=eq.{quote(candidate_id, safe='')}",
            {"status": "failed", "finished_at": datetime.now(timezone.utc).isoformat(), "heartbeat_at": datetime.now(timezone.utc).isoformat(), "error": error[:4000]},
        )

    async def list_strategy_candidates(
        self, symbol: str, snapshot_interval: str, result_status: str = "all", order: str = "profit_factor", limit: int = 100
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        order_map = {
            "profit_factor": "profit_factor.desc.nullslast,expectancy_r.desc.nullslast",
            "expectancy": "expectancy_r.desc.nullslast,profit_factor.desc.nullslast",
            "drawdown": "max_drawdown_r.asc.nullslast,profit_factor.desc.nullslast",
            "trades": "trades_total.desc,profit_factor.desc.nullslast",
            "recent": "finished_at.desc.nullslast",
        }
        filters = [
            "select=id,candidate_key,generation,source_question,name,family,hypothesis,rules,backtest_config,result_status,rows_scanned,trades_total,profit_factor,expectancy_r,max_drawdown_r,win_rate,stability_score,baseline_profit_factor,improvement_score,metrics,evidence,requested_at,started_at,finished_at",
            f"symbol=eq.{quote(symbol, safe='')}",
            f"snapshot_interval=eq.{quote(snapshot_interval, safe='')}",
            "status=eq.complete",
        ]
        if result_status in {"elite", "validated", "promising", "rejected"}:
            filters.append(f"result_status=eq.{result_status}")
        filters.extend([f"order={order_map.get(order, order_map['profit_factor'])}", f"limit={safe_limit}"])
        return await self.select("strategy_candidates", "&".join(filters))

    async def get_strategy_evolution_state(self, symbol: str, snapshot_interval: str) -> dict[str, Any] | None:
        rows = await self.select(
            "strategy_evolution_state",
            "select=*&symbol=eq.{}&snapshot_interval=eq.{}&limit=1".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        return rows[0] if rows else None

    async def upsert_strategy_evolution_state(self, symbol: str, snapshot_interval: str, **changes: Any) -> None:
        existing = await self.get_strategy_evolution_state(symbol, snapshot_interval)
        if existing:
            await self.update(
                "strategy_evolution_state",
                "symbol=eq.{}&snapshot_interval=eq.{}".format(
                    quote(symbol, safe=""), quote(snapshot_interval, safe="")
                ),
                changes,
            )
            return
        await self.insert(
            "strategy_evolution_state",
            {"symbol": symbol, "snapshot_interval": snapshot_interval, **changes},
        )

    async def refresh_strategy_evolution_state(self, symbol: str, snapshot_interval: str) -> None:
        await self.rpc("refresh_strategy_evolution_state", {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval})

    async def strategy_evolution_dashboard(self, symbol: str, snapshot_interval: str) -> dict[str, Any]:
        result = await self.rpc("get_strategy_evolution_dashboard", {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval})
        return result or {}

    async def list_evolution_seed_strategies(
        self, symbol: str, snapshot_interval: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(50, int(limit)))
        rows = await self.select(
            "strategy_candidates",
            "select=id,candidate_key,symbol,snapshot_interval,name,family,rules,result_status,trades_total,profit_factor,expectancy_r,max_drawdown_r,stability_score,metrics,evidence,finished_at"
            f"&symbol=eq.{quote(symbol, safe='')}&snapshot_interval=eq.{quote(snapshot_interval, safe='')}"
            "&status=eq.complete&result_status=in.(elite,validated,promising)&trades_total=gte.50"
            "&order=profit_factor.desc.nullslast,expectancy_r.desc.nullslast&limit=50",
        )
        rank = {"elite": 3, "validated": 2, "promising": 1}
        return sorted(
            rows,
            key=lambda item: (
                rank.get(str(item.get("result_status")), 0),
                float(item.get("profit_factor") or 0),
                float(item.get("expectancy_r") or 0),
            ),
            reverse=True,
        )[:safe_limit]

    async def upsert_strategy_lineages(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), 100):
            await self._request(
                "POST",
                "strategy_lineages?on_conflict=lineage_key",
                json=rows[start:start + 100],
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            )

    async def list_strategy_lineages(
        self, symbol: str, snapshot_interval: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(100, int(limit)))
        return await self.select(
            "strategy_lineages",
            "select=*"
            f"&symbol=eq.{quote(symbol, safe='')}&snapshot_interval=eq.{quote(snapshot_interval, safe='')}"
            "&status=eq.active"
            f"&order=champion_validation_score.desc.nullslast,champion_profit_factor.desc.nullslast,updated_at.desc&limit={safe_limit}",
        )

    async def upsert_evolution_candidates(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), 200):
            await self._request(
                "POST",
                "strategy_evolution_candidates?on_conflict=child_key",
                json=rows[start:start + 200],
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            )

    async def claim_next_evolution_candidate(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.rpc("claim_next_evolution_candidate", {"p_worker_id": worker_id})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def complete_evolution_candidate(self, candidate_id: str, result: dict[str, Any]) -> None:
        await self.update(
            "strategy_evolution_candidates", f"id=eq.{quote(candidate_id, safe='')}",
            {
                "status": "complete",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                **result,
            },
        )

    async def fail_evolution_candidate(self, candidate_id: str, error: str) -> None:
        await self.update(
            "strategy_evolution_candidates", f"id=eq.{quote(candidate_id, safe='')}",
            {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "error": error[:4000],
            },
        )

    async def record_evolution_lineage_result(
        self, *, lineage_id: str, candidate_id: str, promoted: bool, generation: int,
        result_status: str, name: str, rules: dict[str, Any], metrics: dict[str, Any],
        profit_factor: float, expectancy_r: float, max_drawdown_r: float, trades: int,
        validation_score: float, summary: str,
    ) -> None:
        await self.rpc(
            "record_evolution_lineage_result",
            {
                "p_lineage_id": lineage_id,
                "p_candidate_id": candidate_id,
                "p_promoted": promoted,
                "p_generation": generation,
                "p_result_status": result_status,
                "p_name": name,
                "p_rules": rules,
                "p_metrics": metrics,
                "p_profit_factor": profit_factor,
                "p_expectancy_r": expectancy_r,
                "p_max_drawdown_r": max_drawdown_r,
                "p_trades": trades,
                "p_validation_score": validation_score,
                "p_summary": summary,
            },
        )

    async def list_evolution_candidates(
        self, symbol: str, snapshot_interval: str, result_status: str = "all",
        order: str = "validation_improvement", limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        order_map = {
            "validation_improvement": "validation_improvement.desc.nullslast,profit_factor.desc.nullslast",
            "profit_factor": "profit_factor.desc.nullslast,expectancy_r.desc.nullslast",
            "expectancy": "expectancy_r.desc.nullslast,profit_factor.desc.nullslast",
            "drawdown": "max_drawdown_r.asc.nullslast,profit_factor.desc.nullslast",
            "generation": "generation.desc,finished_at.desc.nullslast",
            "recent": "finished_at.desc.nullslast",
        }
        filters = [
            "select=id,child_key,lineage_id,generation,mutation_type,parent_kind,name,hypothesis,parent_rules,rules,changes,selection_config,result_status,selection_passed,promoted_for_next_generation,locked_test_passed,rows_scanned,trades_total,profit_factor,expectancy_r,max_drawdown_r,win_rate,stability_score,validation_score,parent_validation_score,validation_improvement,metrics,parent_comparison,evidence,requested_at,started_at,finished_at",
            f"symbol=eq.{quote(symbol, safe='')}",
            f"snapshot_interval=eq.{quote(snapshot_interval, safe='')}",
            "status=eq.complete",
        ]
        if result_status in {"elite", "champion", "development", "rejected"}:
            filters.append(f"result_status=eq.{result_status}")
        filters.extend([f"order={order_map.get(order, order_map['validation_improvement'])}", f"limit={safe_limit}"])
        return await self.select("strategy_evolution_candidates", "&".join(filters))

    async def get_validation_state(self, symbol: str, snapshot_interval: str) -> dict[str, Any] | None:
        rows = await self.select(
            "strategy_validation_state",
            "select=*&symbol=eq.{}&snapshot_interval=eq.{}&limit=1".format(
                quote(symbol, safe=""), quote(snapshot_interval, safe="")
            ),
        )
        return rows[0] if rows else None

    async def upsert_validation_state(self, symbol: str, snapshot_interval: str, **changes: Any) -> None:
        existing = await self.get_validation_state(symbol, snapshot_interval)
        if existing:
            await self.update(
                "strategy_validation_state",
                "symbol=eq.{}&snapshot_interval=eq.{}".format(
                    quote(symbol, safe=""), quote(snapshot_interval, safe="")
                ),
                changes,
            )
            return
        await self.insert(
            "strategy_validation_state",
            {"symbol": symbol, "snapshot_interval": snapshot_interval, **changes},
        )

    async def refresh_validation_state(self, symbol: str, snapshot_interval: str) -> None:
        await self.rpc("refresh_strategy_validation_state", {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval})

    async def validation_dashboard(self, symbol: str, snapshot_interval: str) -> dict[str, Any]:
        result = await self.rpc("get_strategy_validation_dashboard", {"p_symbol": symbol, "p_snapshot_interval": snapshot_interval})
        return result or {}

    async def list_validation_seed_candidates(
        self, symbol: str, snapshot_interval: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(50, int(limit)))
        existing = await self.select(
            "strategy_validation_jobs",
            "select=source_kind,source_strategy_candidate_id,source_evolution_candidate_id"
            f"&symbol=eq.{quote(symbol, safe='')}&snapshot_interval=eq.{quote(snapshot_interval, safe='')}",
        )
        used_strategy = {str(item.get("source_strategy_candidate_id")) for item in existing if item.get("source_strategy_candidate_id")}
        used_evolution = {str(item.get("source_evolution_candidate_id")) for item in existing if item.get("source_evolution_candidate_id")}

        evolution = await self.select(
            "strategy_evolution_candidates",
            "select=id,lineage_id,symbol,snapshot_interval,name,rules,result_status,profit_factor,expectancy_r,max_drawdown_r,trades_total,metrics,evidence,finished_at"
            f"&symbol=eq.{quote(symbol, safe='')}&snapshot_interval=eq.{quote(snapshot_interval, safe='')}"
            "&status=eq.complete&result_status=in.(champion,elite)&selection_passed=eq.true&locked_test_passed=eq.true"
            "&order=result_status.desc,profit_factor.desc.nullslast,expectancy_r.desc.nullslast&limit=50",
        )
        strategy = await self.select(
            "strategy_candidates",
            "select=id,symbol,snapshot_interval,name,family,rules,result_status,profit_factor,expectancy_r,max_drawdown_r,trades_total,metrics,evidence,finished_at"
            f"&symbol=eq.{quote(symbol, safe='')}&snapshot_interval=eq.{quote(snapshot_interval, safe='')}"
            "&status=eq.complete&result_status=in.(elite,validated)&trades_total=gte.50"
            "&order=result_status.desc,profit_factor.desc.nullslast,expectancy_r.desc.nullslast&limit=50",
        )
        seeds: list[dict[str, Any]] = []
        for item in evolution:
            if str(item.get("id")) in used_evolution:
                continue
            seeds.append({**item, "source_kind": "evolution", "family": "evolved_strategy"})
        for item in strategy:
            if str(item.get("id")) in used_strategy:
                continue
            seeds.append({**item, "source_kind": "strategy"})
        rank = {"elite": 4, "champion": 3, "validated": 2}
        seeds.sort(
            key=lambda item: (
                rank.get(str(item.get("result_status")), 0),
                float(item.get("profit_factor") or 0),
                float(item.get("expectancy_r") or 0),
            ),
            reverse=True,
        )
        return seeds[:safe_limit]

    async def upsert_validation_jobs(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), 100):
            await self._request(
                "POST",
                "strategy_validation_jobs?on_conflict=validation_key",
                json=rows[start:start + 100],
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            )

    async def reset_stale_validation_jobs(self, stale_minutes: int = 20) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
        await self.update(
            "strategy_validation_jobs",
            f"status=eq.running&or=(heartbeat_at.is.null,heartbeat_at.lt.{quote(cutoff, safe=':-TZ')})",
            {
                "status": "queued",
                "worker_id": None,
                "error": "Recovered after Railway restart",
            },
        )

    async def claim_next_validation_job(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.rpc("claim_next_validation_job", {"p_worker_id": worker_id})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def update_validation_job(self, job_id: str, **changes: Any) -> None:
        await self.update("strategy_validation_jobs", f"id=eq.{quote(job_id, safe='')}", changes)

    async def complete_validation_job(self, job_id: str, result: dict[str, Any]) -> None:
        await self.update(
            "strategy_validation_jobs",
            f"id=eq.{quote(job_id, safe='')}",
            {
                "status": "complete",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                **result,
            },
        )

    async def fail_validation_job(self, job_id: str, error: str) -> None:
        await self.update(
            "strategy_validation_jobs",
            f"id=eq.{quote(job_id, safe='')}",
            {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "error": error[:4000],
            },
        )

    async def freeze_validated_strategy(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        rule_hash = str(result.get("rules_hash") or "")
        if not rule_hash:
            raise ValueError("Cannot freeze a strategy without a rule hash")
        strategy_code = f"EVE-{rule_hash[:12].upper()}"
        source_id = job.get("source_evolution_candidate_id") or job.get("source_strategy_candidate_id")
        payload = {
            "strategy_code": strategy_code,
            "rule_hash": rule_hash,
            "symbol": job.get("symbol") or "XAU/USD",
            "source_validation_job_id": job.get("id"),
            "source_kind": job.get("source_kind") or "evolution",
            "source_id": source_id,
            "name": job.get("name") or strategy_code,
            "family": job.get("family") or "unknown",
            "version": "1.0",
            "rules": result.get("frozen_rules") or job.get("rules") or {},
            "validation_metrics": result.get("metrics") or {},
            "validation_evidence": result.get("evidence") or {},
            "status": "ready_for_mt5_generation",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Frozen rules are immutable. A duplicate rule hash is ignored rather
        # than merged so a later worker cannot silently rewrite a passed version.
        await self._request(
            "POST",
            "frozen_strategies?on_conflict=rule_hash",
            json=payload,
            headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
        )

    async def list_validation_jobs(
        self, symbol: str, snapshot_interval: str, result_status: str = "all",
        order: str = "profit_factor", limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        order_map = {
            "profit_factor": "profit_factor.desc.nullslast,expectancy_r.desc.nullslast",
            "expectancy": "expectancy_r.desc.nullslast,profit_factor.desc.nullslast",
            "drawdown": "max_drawdown_r.asc.nullslast,profit_factor.desc.nullslast",
            "robustness": "robust_profile_ratio.desc.nullslast,profit_factor.desc.nullslast",
            "recent": "finished_at.desc.nullslast",
        }
        filters = [
            "select=id,validation_key,source_kind,source_strategy_candidate_id,source_evolution_candidate_id,source_lineage_id,name,family,rules,source_result_status,source_profit_factor,source_expectancy_r,source_metrics,result_status,rows_scanned,m1_windows_scanned,trades_total,profit_factor,expectancy_r,max_drawdown_r,win_rate,year_stability,resolved_rate,robust_profile_ratio,rules_hash,frozen_rules,metrics,evidence,requested_at,started_at,finished_at",
            f"symbol=eq.{quote(symbol, safe='')}",
            f"snapshot_interval=eq.{quote(snapshot_interval, safe='')}",
            "status=eq.complete",
        ]
        if result_status in {"rejected", "needs_more_evidence", "replay_validated", "ready_for_mt5_generation"}:
            filters.append(f"result_status=eq.{result_status}")
        filters.extend([f"order={order_map.get(order, order_map['profit_factor'])}", f"limit={safe_limit}"])
        return await self.select("strategy_validation_jobs", "&".join(filters))

    async def get_mt5_generation_state(self, symbol: str) -> dict[str, Any] | None:
        rows = await self.select(
            "mt5_generation_state",
            f"select=*&symbol=eq.{quote(symbol, safe='')}&limit=1",
        )
        return rows[0] if rows else None

    async def upsert_mt5_generation_state(self, symbol: str, **changes: Any) -> None:
        existing = await self.get_mt5_generation_state(symbol)
        if existing:
            await self.update("mt5_generation_state", f"symbol=eq.{quote(symbol, safe='')}", changes)
            return
        await self.insert("mt5_generation_state", {"symbol": symbol, **changes})

    async def refresh_mt5_generation_state(self, symbol: str) -> None:
        await self.rpc("refresh_mt5_generation_state", {"p_symbol": symbol})

    async def mt5_generation_dashboard(self, symbol: str) -> dict[str, Any]:
        result = await self.rpc("get_mt5_generation_dashboard", {"p_symbol": symbol})
        return result or {}

    async def list_mt5_generation_seeds(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(100, int(limit)))
        existing = await self.select(
            "mt5_generation_jobs",
            f"select=frozen_strategy_id&symbol=eq.{quote(symbol, safe='')}",
        )
        used = {str(item.get("frozen_strategy_id")) for item in existing if item.get("frozen_strategy_id")}
        rows = await self.select(
            "frozen_strategies",
            "select=id,strategy_code,rule_hash,symbol,source_validation_job_id,source_kind,source_id,name,family,version,rules,validation_metrics,validation_evidence,status,frozen_at,updated_at"
            f"&symbol=eq.{quote(symbol, safe='')}&status=eq.ready_for_mt5_generation"
            "&order=frozen_at.asc&limit=100",
        )
        return [item for item in rows if str(item.get("id")) not in used][:safe_limit]

    async def upsert_mt5_generation_jobs(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), 100):
            await self._request(
                "POST",
                "mt5_generation_jobs?on_conflict=generation_key",
                json=rows[start:start + 100],
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            )

    async def reset_stale_mt5_generation_jobs(self, stale_minutes: int = 20) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
        await self.update(
            "mt5_generation_jobs",
            f"status=eq.running&or=(heartbeat_at.is.null,heartbeat_at.lt.{quote(cutoff, safe=':-TZ')})",
            {"status": "queued", "worker_id": None, "error": "Recovered after Railway restart"},
        )

    async def claim_next_mt5_generation_job(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.rpc("claim_next_mt5_generation_job", {"p_worker_id": worker_id})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def get_frozen_strategy(self, frozen_id: str) -> dict[str, Any] | None:
        rows = await self.select(
            "frozen_strategies",
            f"select=*&id=eq.{quote(frozen_id, safe='')}&limit=1",
        )
        return rows[0] if rows else None

    async def create_mt5_package(
        self, job: dict[str, Any], frozen: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        record = {
            "package_code": payload.get("package_code"),
            "symbol": frozen.get("symbol") or "XAU/USD",
            "frozen_strategy_id": frozen.get("id"),
            "source_generation_job_id": job.get("id"),
            "strategy_code": payload.get("strategy_code"),
            "strategy_name": frozen.get("name"),
            "frozen_version": payload.get("version") or "1.0",
            "rule_hash": frozen.get("rule_hash"),
            "file_name": payload.get("file_name"),
            "mq5_source": payload.get("mq5_source"),
            "readme_text": payload.get("readme_text"),
            "frozen_rules": payload.get("frozen_rules") or {},
            "validation_report": payload.get("validation_report") or {},
            "manifest": payload.get("manifest") or {},
            "source_sha256": payload.get("source_sha256"),
            "static_validation": payload.get("static_validation") or {},
            "status": payload.get("status") or "ready_for_metaeditor_compile",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = await self._request(
            "POST",
            "mt5_packages?on_conflict=frozen_strategy_id",
            json=record,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        if isinstance(result, list) and result:
            return result[0]
        existing = await self.select(
            "mt5_packages",
            f"select=*&frozen_strategy_id=eq.{quote(str(frozen.get('id')), safe='')}&limit=1",
        )
        if not existing:
            raise RuntimeError("MT5 package could not be stored")
        return existing[0]

    async def complete_mt5_generation_job(
        self, job_id: str, *, package_id: Any, file_name: str, source_sha256: str,
        result_status: str, evidence: dict[str, Any],
    ) -> None:
        await self.update(
            "mt5_generation_jobs",
            f"id=eq.{quote(job_id, safe='')}",
            {
                "status": "complete",
                "result_status": result_status,
                "package_id": package_id,
                "file_name": file_name,
                "source_sha256": source_sha256,
                "evidence": evidence,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            },
        )

    async def fail_mt5_generation_job(self, job_id: str, error: str) -> None:
        await self.update(
            "mt5_generation_jobs",
            f"id=eq.{quote(job_id, safe='')}",
            {
                "status": "failed",
                "result_status": "static_validation_failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "error": error[:4000],
            },
        )

    async def mark_frozen_strategy_mt5_generated(self, frozen_id: str) -> None:
        await self.update(
            "frozen_strategies",
            f"id=eq.{quote(frozen_id, safe='')}",
            {"status": "mt5_generated", "updated_at": datetime.now(timezone.utc).isoformat()},
        )

    async def get_mt5_package(self, package_id: str) -> dict[str, Any] | None:
        rows = await self.select(
            "mt5_packages",
            f"select=*&id=eq.{quote(package_id, safe='')}&limit=1",
        )
        return rows[0] if rows else None

    async def list_mt5_packages(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(200, int(limit)))
        return await self.select(
            "mt5_packages",
            "select=id,package_code,symbol,frozen_strategy_id,source_generation_job_id,strategy_code,strategy_name,frozen_version,rule_hash,file_name,source_sha256,static_validation,status,manifest,validation_report,generated_at,updated_at"
            f"&symbol=eq.{quote(symbol, safe='')}&order=generated_at.desc&limit={safe_limit}",
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
