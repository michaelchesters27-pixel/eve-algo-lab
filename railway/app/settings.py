from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded only from Railway environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "EVE Algo Lab"
    environment: str = "production"
    log_level: str = "INFO"

    twelve_data_api_key: str = Field(min_length=8)
    twelve_data_base_url: str = "https://api.twelvedata.com"
    twelve_data_request_delay_seconds: float = Field(default=2.0, ge=0.5, le=120)
    twelve_data_batch_size: int = Field(default=5000, ge=1, le=5000)

    supabase_url: str = Field(min_length=10)
    supabase_service_role_key: str = Field(min_length=20)

    admin_token: str = Field(min_length=12)
    cors_origins: str = "*"

    default_symbol: str = "XAU/USD"
    default_interval: str = "5min"
    auto_sync_enabled: bool = True
    auto_sync_intervals: str = "1min,5min"
    auto_sync_offset_seconds: int = Field(default=22, ge=0, le=59)
    worker_poll_seconds: float = Field(default=4.0, ge=1, le=60)
    request_timeout_seconds: float = Field(default=45.0, ge=5, le=180)
    max_http_retries: int = Field(default=6, ge=1, le=12)
    exact_count_every_batches: int = Field(default=5, ge=1, le=50)

    @field_validator("supabase_url", "twelve_data_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origin_list(self) -> List[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def auto_sync_interval_list(self) -> List[str]:
        intervals: list[str] = []
        for item in self.auto_sync_intervals.split(","):
            interval = item.strip()
            if interval and interval not in intervals:
                intervals.append(interval)
        return intervals or [self.default_interval]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
