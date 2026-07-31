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
                    "accuracy": "M5 candle-path approximation",
                },
            },
        )
