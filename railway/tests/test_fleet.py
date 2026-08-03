from datetime import datetime, timedelta, timezone

from app.services.fleet import (
    build_fleet_dashboard,
    fleet_token,
    heartbeat_row,
    verify_fleet_token,
)

UTC = timezone.utc


def package(package_id="11111111-1111-1111-1111-111111111111"):
    return {
        "id": package_id,
        "package_code": "EVE-THURSDAY-MT5-v1.0",
        "strategy_code": "EVE-THURSDAY",
        "strategy_name": "Thursday Momentum",
        "frozen_version": "1.0",
        "frozen_rules": {
            "condition_mode": "include",
            "source_conditions": [
                {"field": "weekday", "value": 4},
                {"field": "hour_utc", "value": 13},
            ],
        },
    }


def payload(package_id="11111111-1111-1111-1111-111111111111", chart_id="77"):
    return {
        "package_id": package_id,
        "strategy_code": "EVE-THURSDAY",
        "rule_hash": "a" * 64,
        "account_login": 52888663,
        "account_type": "demo",
        "broker_server": "ICMarketsSC-Demo",
        "broker_company": "Raw Trading Ltd",
        "symbol": "XAUUSD",
        "timeframe": "PERIOD_M5",
        "chart_id": chart_id,
        "trading_enabled": True,
        "algo_trading_enabled": True,
        "state": "waiting_rule_condition",
        "state_detail": "Waiting for frozen setup",
        "open_positions": 0,
        "open_profit": 0,
        "closed_profit_today": 4.67,
        "terminal_time": 1785763200,
        "last_trade_time": 1785762600,
        "client_version": "3.1",
    }


def test_fleet_token_is_package_specific():
    token = fleet_token("admin-secret-123", "pkg-1", "a" * 64)
    assert verify_fleet_token("admin-secret-123", "pkg-1", "a" * 64, token)
    assert not verify_fleet_token("admin-secret-123", "pkg-2", "a" * 64, token)


def test_heartbeat_row_is_stable_per_chart():
    now = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)
    first = heartbeat_row(payload(), now)
    second = heartbeat_row(payload(), now + timedelta(seconds=30))
    assert first["instance_key"] == second["instance_key"]
    assert first["account_type"] == "demo"
    assert first["closed_profit_today"] == 4.67


def test_fleet_dashboard_marks_online_and_masks_account():
    now = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)
    row = heartbeat_row(payload(), now - timedelta(seconds=20))
    result = build_fleet_dashboard([row], [package()], now)
    item = result["items"][0]
    assert result["counts"]["online"] == 1
    assert item["connection"] == "online"
    assert item["account_login_masked"] == "••••8663"
    assert "account_login" not in item
    assert "payload" not in item
    assert "weekday_thursday" in item["usage_tags"]
    assert "short_window" in item["usage_tags"]


def test_fleet_dashboard_detects_duplicate_attachment():
    now = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)
    one = heartbeat_row(payload(chart_id="77"), now)
    two = heartbeat_row(payload(chart_id="88"), now)
    result = build_fleet_dashboard([one, two], [package()], now)
    assert result["counts"]["duplicates"] == 2
    assert all(item["duplicate"] for item in result["items"])


def test_usage_classification_keeps_combined_weekday_and_month_labels():
    from app.services.demo_eligibility import describe_bot_usage

    usage = describe_bot_usage({
        "condition_mode": "include",
        "source_conditions": [
            {"field": "weekday", "value": 1},
            {"field": "month", "value": 1},
            {"field": "hour_utc", "value": 13},
        ],
    })
    assert "weekday_monday" in usage["usage_tags"]
    assert "month_january" in usage["usage_tags"]
    assert "seasonal" in usage["usage_tags"]
    assert "short_window" in usage["usage_tags"]
    assert "Monday bot" in usage["usage_title"]
    assert "January bot" in usage["usage_title"]


def test_fleet_dashboard_hides_old_detached_rows_from_live_screen():
    now = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)
    row = heartbeat_row({**payload(), "state": "detached"}, now - timedelta(days=2))
    result = build_fleet_dashboard([row], [package()], now)
    assert result["items"] == []
    assert result["counts"]["total"] == 0
