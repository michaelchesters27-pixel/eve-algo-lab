from datetime import timezone

from app.services.twelve_data import parse_utc_datetime


def test_parse_twelve_data_datetime_as_utc() -> None:
    parsed = parse_utc_datetime("2026-07-31 08:30:00")
    assert parsed.tzinfo == timezone.utc
    assert parsed.isoformat() == "2026-07-31T08:30:00+00:00"
