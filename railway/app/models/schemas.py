from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SupportedInterval = Literal["1min", "5min", "15min", "30min", "45min", "1h", "2h", "4h", "8h", "1day"]


class JobRequest(BaseModel):
    symbol: str = Field(default="XAU/USD", min_length=3, max_length=40)
    interval: SupportedInterval = "5min"
    force_restart: bool = False


class JobResponse(BaseModel):
    id: str
    status: str
    message: str


class MetricsPreviewRequest(BaseModel):
    net_pnls: list[float] = Field(min_length=1, max_length=100_000)
    starting_balance: float = Field(default=10_000, gt=0)


class ApiEnvelope(BaseModel):
    ok: bool = True
    data: Any = None
    message: str | None = None
