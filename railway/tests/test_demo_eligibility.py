from datetime import datetime, timezone

from app.services.demo_eligibility import build_demo_dashboard, evaluate_package

UTC = timezone.utc


def package(conditions, *, mode="include", direction="alignment_direction", pf=1.49):
    return {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "package_code": "EVE-TEST-MT5-v1.0",
        "strategy_code": "EVE-TEST",
        "strategy_name": "Test strategy",
        "frozen_version": "1.0",
        "rule_hash": "a" * 64,
        "frozen_rules": {
            "source_conditions": conditions,
            "condition_mode": mode,
            "direction_rule": direction,
            "stop_atr": 1.0,
            "target_atr": 2.0,
            "horizon_minutes": 30,
            "cooldown_minutes": 30,
        },
        "validation_report": {
            "validation_metrics": {
                "standard_cost": {
                    "locked_test": {"profit_factor": pf, "expectancy_r": 0.2, "trades": 150}
                }
            }
        },
        "generated_at": "2026-08-03T08:00:00+00:00",
    }


def snapshot(now, *, compression_ratio=1.5, alignment_score=3, direction=1):
    return {
        "candle_time": now.isoformat(),
        "regime": "trend_up",
        "direction": direction,
        "alignment_score": alignment_score,
        "compression_ratio": compression_ratio,
        "trend_12_atr": 0.3,
        "streak": 3,
    }


def test_quarter_one_strategy_is_labelled_wait_for_period_in_august():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    item = evaluate_package(package([{"field": "quarter", "value": 1}]), snapshot(now), now)
    assert item["status"] == "waiting_for_period"
    assert item["status_label"] == "WAIT FOR PERIOD"
    assert "January–March" in item["rule_summary"]
    assert item["next_eligible_utc"].startswith("2027-01")


def test_matching_calendar_and_market_conditions_are_test_now():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    item = evaluate_package(
        package([
            {"field": "hour_utc", "value": 10},
            {"field": "compression_band", "value": "expanded"},
        ]),
        snapshot(now),
        now,
    )
    assert item["status"] == "active_now"
    assert item["status_label"] == "TEST NOW"
    assert item["source_eligible_now"] is True


def test_calendar_window_open_but_dynamic_filter_missing_is_attach_and_leave():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    item = evaluate_package(
        package([
            {"field": "hour_utc", "value": 10},
            {"field": "compression_band", "value": "expanded"},
        ]),
        snapshot(now, compression_ratio=1.0),
        now,
    )
    assert item["status"] == "attach_now_waiting_market_condition"
    assert item["status_label"] == "ATTACH AND LEAVE"
    assert "expanded" in " ".join(item["missing_conditions"])


def test_wrong_hour_is_wait_for_time():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    item = evaluate_package(package([{"field": "hour_utc", "value": 11}]), snapshot(now), now)
    assert item["status"] == "waiting_for_trading_window"
    assert item["status_label"] == "WAIT FOR TIME"
    assert item["next_eligible_utc"].startswith("2026-08-03T11:")


def test_dashboard_ranks_test_now_before_seasonal_bot():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    active = package([{"field": "hour_utc", "value": 10}], pf=1.3)
    active["id"] = "223e4567-e89b-12d3-a456-426614174000"
    active["strategy_name"] = "Available now"
    seasonal = package([{"field": "quarter", "value": 1}], pf=2.0)
    seasonal["strategy_name"] = "Higher PF but seasonal"
    dashboard = build_demo_dashboard([seasonal, active], snapshot(now), now)
    assert dashboard["recommended"]["strategy_name"] == "Available now"
    assert dashboard["counts"]["test_now"] == 1
