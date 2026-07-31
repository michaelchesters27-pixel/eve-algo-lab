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
