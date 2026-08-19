from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

COMPONENT = "4ccb-broker-calibration"
CALIBRATION_VERSION = "0.1.0"


class BrokerCalibrationSample(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=40)
    broker_company: str = Field(default="", max_length=160)
    broker_server: str = Field(default="", max_length=160)
    account_currency: str = Field(default="", max_length=20)
    account_trade_mode: int = 0
    terminal_time: int = 0
    server_utc_offset_seconds: int = Field(default=0, ge=-86400, le=86400)

    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    spread_price: float = Field(ge=0)
    spread_points: float = Field(ge=0)

    digits: int = Field(ge=0, le=12)
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value: float = Field(ge=0)
    tick_value_profit: float = Field(ge=0)
    tick_value_loss: float = Field(ge=0)
    contract_size: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    stops_level_points: int = Field(default=0, ge=0)
    spread_float: bool = True
    swap_long: float = 0.0
    swap_short: float = 0.0

    client_version: str = Field(default="EVE-4CCB-calibrator-0.1", max_length=80)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _round(value: float | None, places: int = 8) -> float | None:
    return None if value is None else round(value, places)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    details = [dict(row.get("details") or {}) for row in rows]
    spreads = [value for item in details if (value := _finite(item.get("spread_price"))) is not None]
    spread_points = [value for item in details if (value := _finite(item.get("spread_points"))) is not None]

    latest = details[0] if details else {}
    latest_created_at = rows[0].get("created_at") if rows else None
    spec_keys = (
        "digits",
        "point",
        "tick_size",
        "tick_value",
        "tick_value_profit",
        "tick_value_loss",
        "contract_size",
        "volume_min",
        "volume_step",
        "volume_max",
    )
    signatures = {
        tuple(str(item.get(key)) for key in spec_keys)
        for item in details
        if item
    }

    return {
        "version": CALIBRATION_VERSION,
        "status": "collecting" if rows else "waiting_for_mt5",
        "samples": len(rows),
        "latest_sample_at": latest_created_at,
        "broker": {
            "company": latest.get("broker_company"),
            "server": latest.get("broker_server"),
            "account_currency": latest.get("account_currency"),
            "account_trade_mode": latest.get("account_trade_mode"),
            "server_utc_offset_seconds": latest.get("server_utc_offset_seconds"),
        },
        "symbol": latest.get("symbol"),
        "symbol_specification": {key: latest.get(key) for key in spec_keys},
        "symbol_spec_consistent_across_samples": len(signatures) <= 1 if signatures else None,
        "latest_market": {
            "bid": latest.get("bid"),
            "ask": latest.get("ask"),
            "spread_price": latest.get("spread_price"),
            "spread_points": latest.get("spread_points"),
            "spread_float": latest.get("spread_float"),
            "stops_level_points": latest.get("stops_level_points"),
            "swap_long": latest.get("swap_long"),
            "swap_short": latest.get("swap_short"),
        },
        "spread_distribution_price": {
            "min": _round(min(spreads) if spreads else None),
            "median": _round(_percentile(spreads, 0.50)),
            "p75": _round(_percentile(spreads, 0.75)),
            "p90": _round(_percentile(spreads, 0.90)),
            "p95": _round(_percentile(spreads, 0.95)),
            "max": _round(max(spreads) if spreads else None),
        },
        "spread_distribution_points": {
            "min": _round(min(spread_points) if spread_points else None, 3),
            "median": _round(_percentile(spread_points, 0.50), 3),
            "p75": _round(_percentile(spread_points, 0.75), 3),
            "p90": _round(_percentile(spread_points, 0.90), 3),
            "p95": _round(_percentile(spread_points, 0.95), 3),
            "max": _round(max(spread_points) if spread_points else None, 3),
        },
        "next_calibration_requirements": [
            "Collect spread samples across multiple trading sessions, including 4CCB signal and entry times.",
            "Record actual commission from completed 0.01-lot demo trades; do not infer it solely from the account currency.",
            "Record requested versus filled entry/exit prices so slippage can be measured directly.",
        ],
        "live_capital_approved": False,
    }


def build_four_ccb_broker_calibration_router(repo: Any, require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/research/4ccb-broker-calibration/sample", dependencies=[Depends(require_admin)])
    async def record_sample(sample: BrokerCalibrationSample) -> dict[str, Any]:
        payload = sample.model_dump()
        payload["received_at"] = datetime.now(timezone.utc).isoformat()
        await repo.log_event(
            "info",
            COMPONENT,
            "4CCB MT5 broker calibration sample",
            payload,
        )
        return {
            "ok": True,
            "message": "Broker calibration sample recorded",
            "data": {
                "version": CALIBRATION_VERSION,
                "symbol": sample.symbol,
                "spread_price": sample.spread_price,
                "spread_points": sample.spread_points,
            },
        }

    @router.get("/api/research/4ccb-broker-calibration/status")
    async def calibration_status(limit: int = 500) -> dict[str, Any]:
        safe_limit = max(1, min(2000, int(limit)))
        rows = await repo.select(
            "system_events",
            "select=created_at,details&component=eq.{}&order=created_at.desc&limit={}".format(
                quote(COMPONENT, safe=""), safe_limit
            ),
        )
        return {"ok": True, "data": _summary(rows)}

    return router
