from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


INTERVAL_SECONDS: dict[str, int] = {
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "30min": 1800,
    "45min": 2700,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "8h": 28800,
    "1day": 86400,
}


class TwelveDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None

    def to_row(self, symbol: str, interval: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "interval": interval,
            "candle_time": self.timestamp.isoformat(),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": None if self.volume is None else str(self.volume),
            "source": "twelve_data",
            "is_complete": True,
        }


def parse_utc_datetime(value: str | int | float) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)

    cleaned = str(value).strip().replace("Z", "+00:00")
    numeric_candidate = cleaned.replace(".", "", 1)
    if numeric_candidate.isdigit():
        return datetime.fromtimestamp(float(cleaned), tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        parsed = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise TwelveDataError(f"Invalid {field} value from Twelve Data: {value!r}") from exc


class TwelveDataClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 45,
        max_retries: int = 6,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {**params, "apikey": self.api_key}
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await self.client.get(f"{self.base_url}/{endpoint.lstrip('/')}", params=request_params)
                payload = response.json()

                if response.status_code == 429 or payload.get("code") == 429:
                    delay = min(90, 5 * (2**attempt))
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500:
                    raise TwelveDataError(f"Twelve Data server error {response.status_code}")

                if response.status_code >= 400 or payload.get("status") == "error":
                    raise TwelveDataError(payload.get("message") or f"Twelve Data HTTP {response.status_code}")

                return payload
            except (httpx.HTTPError, ValueError, TwelveDataError) as exc:
                last_error = exc
                if isinstance(exc, TwelveDataError) and "Invalid" in str(exc):
                    raise
                if attempt + 1 >= self.max_retries:
                    break
                await asyncio.sleep(min(60, 2**attempt))

        raise TwelveDataError(f"Twelve Data request failed after retries: {last_error}")

    async def earliest_timestamp(self, symbol: str, interval: str) -> datetime:
        payload = await self._get(
            "earliest_timestamp",
            {"symbol": symbol, "interval": interval},
        )
        for key in ("datetime", "timestamp", "earliest_timestamp", "unix_time"):
            if key in payload and payload[key] not in (None, ""):
                return parse_utc_datetime(payload[key])
        raise TwelveDataError(f"Could not read earliest timestamp response: {payload}")

    async def time_series(
        self,
        symbol: str,
        interval: str,
        outputsize: int = 5000,
        end_date: datetime | None = None,
    ) -> list[Candle]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": min(max(outputsize, 1), 5000),
            "format": "JSON",
            "order": "desc",
            "timezone": "UTC",
        }
        if end_date is not None:
            params["end_date"] = end_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        payload = await self._get("time_series", params)
        values = payload.get("values") or []
        candles: list[Candle] = []

        for item in values:
            volume_raw = item.get("volume")
            volume = None if volume_raw in (None, "", "null") else _decimal(volume_raw, "volume")
            candle = Candle(
                timestamp=parse_utc_datetime(item["datetime"]),
                open=_decimal(item["open"], "open"),
                high=_decimal(item["high"], "high"),
                low=_decimal(item["low"], "low"),
                close=_decimal(item["close"], "close"),
                volume=volume,
            )
            if candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close, candle.high):
                raise TwelveDataError(f"Invalid OHLC relationship at {candle.timestamp.isoformat()}")
            candles.append(candle)

        candles.sort(key=lambda item: item.timestamp, reverse=True)
        return candles
