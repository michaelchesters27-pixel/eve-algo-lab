from app.services.twelve_data import INTERVAL_SECONDS
from app.settings import Settings


TARGET_INTERVALS = ["1min", "5min", "15min", "1h", "4h", "1day"]


def test_research_timeframes_are_supported() -> None:
    assert all(interval in INTERVAL_SECONDS for interval in TARGET_INTERVALS)
    assert [INTERVAL_SECONDS[item] for item in TARGET_INTERVALS] == [60, 300, 900, 3600, 14400, 86400]


def test_default_auto_sync_covers_full_data_foundation() -> None:
    settings = Settings(
        twelve_data_api_key="test-api-key",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-key-long-enough",
        admin_token="admin-token-long-enough",
    )
    assert settings.auto_sync_interval_list == TARGET_INTERVALS
    assert settings.auto_sync_stagger_seconds == 3
