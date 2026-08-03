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
    auto_sync_intervals: str = "1min,5min,15min,1h,4h,1day"
    auto_sync_offset_seconds: int = Field(default=22, ge=0, le=59)
    auto_sync_stagger_seconds: int = Field(default=3, ge=0, le=30)
    worker_poll_seconds: float = Field(default=4.0, ge=1, le=60)
    request_timeout_seconds: float = Field(default=45.0, ge=5, le=180)
    max_http_retries: int = Field(default=6, ge=1, le=12)
    exact_count_every_batches: int = Field(default=5, ge=1, le=50)

    # Autonomous learning defaults require no new Railway variables. They can be
    # overridden later, but autonomous learning is active with the existing deployment.
    autonomous_learning_enabled: bool = True
    autonomous_cycle_minutes: int = Field(default=15, ge=5, le=1440)
    autonomous_research_hours: int = Field(default=6, ge=1, le=168)
    autonomous_model_hours: int = Field(default=24, ge=6, le=720)
    autonomous_startup_delay_seconds: int = Field(default=120, ge=15, le=1800)
    autonomous_model_promotion_enabled: bool = True

    # v1.7 dedicated historical research worker. Defaults are active so the
    # existing Railway deployment needs no additional variables.
    historical_research_enabled: bool = True
    historical_research_startup_delay_seconds: int = Field(default=150, ge=15, le=1800)
    historical_research_job_delay_seconds: float = Field(default=20.0, ge=2.0, le=600.0)
    historical_research_idle_seconds: float = Field(default=30.0, ge=5.0, le=900.0)
    historical_research_queue_floor: int = Field(default=60, ge=10, le=1000)
    historical_research_seed_batch: int = Field(default=250, ge=25, le=1000)
    historical_research_cache_minutes: int = Field(default=180, ge=15, le=1440)

    # v2.0 autonomous Strategy Lab. Defaults are active and require no new Railway variables.
    strategy_lab_enabled: bool = True
    strategy_lab_startup_delay_seconds: int = Field(default=240, ge=15, le=1800)
    strategy_lab_job_delay_seconds: float = Field(default=30.0, ge=2.0, le=900.0)
    strategy_lab_idle_seconds: float = Field(default=45.0, ge=5.0, le=900.0)
    strategy_lab_queue_floor: int = Field(default=12, ge=2, le=500)
    strategy_lab_cache_minutes: int = Field(default=180, ge=15, le=1440)

    # v2.2 autonomous Strategy Evolution Engine. It shares the historical
    # research dataset and runs controlled one-child-at-a-time mutations.
    strategy_evolution_enabled: bool = True
    strategy_evolution_startup_delay_seconds: int = Field(default=360, ge=30, le=3600)
    strategy_evolution_job_delay_seconds: float = Field(default=60.0, ge=5.0, le=1800.0)
    strategy_evolution_idle_seconds: float = Field(default=60.0, ge=5.0, le=1800.0)
    strategy_evolution_queue_floor: int = Field(default=20, ge=2, le=1000)
    strategy_evolution_cache_minutes: int = Field(default=180, ge=15, le=1440)

    # v2.3 automatic high-resolution validation. Strong strategies are replayed
    # on M1 data with conservative order resolution and execution-cost stress.
    high_resolution_validation_enabled: bool = True
    high_resolution_validation_startup_delay_seconds: int = Field(default=480, ge=30, le=7200)
    high_resolution_validation_job_delay_seconds: float = Field(default=90.0, ge=10.0, le=3600.0)
    high_resolution_validation_idle_seconds: float = Field(default=90.0, ge=10.0, le=3600.0)
    high_resolution_validation_queue_floor: int = Field(default=3, ge=1, le=100)

    # v2.5 automatic MT5 source generator and demo eligibility labelling. Frozen strategies are converted into
    # versioned .mq5 demo-testing packages without adding Railway variables.
    mt5_generator_enabled: bool = True
    mt5_generator_startup_delay_seconds: int = Field(default=120, ge=30, le=7200)
    mt5_generator_job_delay_seconds: float = Field(default=60.0, ge=5.0, le=3600.0)
    mt5_generator_idle_seconds: float = Field(default=90.0, ge=10.0, le=3600.0)
    mt5_generator_queue_floor: int = Field(default=1, ge=1, le=100)

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
