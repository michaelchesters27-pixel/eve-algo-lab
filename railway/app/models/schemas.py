from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SupportedInterval = Literal["1min", "5min", "15min", "30min", "45min", "1h", "2h", "4h", "8h", "1day"]
PathMode = Literal["candle_direction", "open_high_low_close", "open_low_high_close"]
BacktestResolution = Literal["candle", "m1_replay"]


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


class FixedLadderBacktestRequest(BaseModel):
    name: str = Field(default="Fixed Ladder v2.61 — Full M5 History", min_length=3, max_length=120)
    symbol: str = Field(default="XAU/USD", min_length=3, max_length=40)
    interval: Literal["5min"] = "5min"
    resolution: BacktestResolution = "candle"
    date_from: datetime | None = None
    date_to: datetime | None = None
    starting_balance: float = Field(default=1000.0, gt=0, le=100_000_000)
    fixed_lot: float = Field(default=0.01, gt=0, le=100)
    levels_per_side: int = Field(default=8, ge=1, le=50)
    spacing_price: float = Field(default=3.0, gt=0, le=1000)
    fallback_price: float = Field(default=2.0, gt=0, le=1000)
    first_bullet_quick_cut_price: float = Field(default=0.75, ge=0, le=1000)
    break_even_trigger_price: float = Field(default=1.5, gt=0, le=1000)
    break_even_buffer_price: float = Field(default=0.15, ge=0, le=1000)
    profit_target_money: float = Field(default=5.0, gt=0, le=1_000_000)
    peak_protection_activation_money: float = Field(default=4.0, gt=0, le=1_000_000)
    peak_protection_giveback_money: float = Field(default=1.0, gt=0, le=1_000_000)
    emergency_loss_money: float = Field(default=5.0, ge=0, le=1_000_000)
    emergency_loss_percent: float = Field(default=1.0, ge=0, le=100)
    spread_price: float = Field(default=0.05, ge=0, le=100)
    commission_per_001_lot: float = Field(default=0.08, ge=0, le=1000)
    slippage_price: float = Field(default=0.0, ge=0, le=100)
    money_per_price_per_001_lot: float = Field(default=1.0, gt=0, le=10000)
    path_mode: PathMode = "candle_direction"

    @field_validator("date_to")
    @classmethod
    def validate_date_range(cls, value: datetime | None, info):
        start = info.data.get("date_from")
        if value is not None and start is not None and value <= start:
            raise ValueError("date_to must be later than date_from")
        return value


class ApiEnvelope(BaseModel):
    ok: bool = True
    data: Any = None
    message: str | None = None
