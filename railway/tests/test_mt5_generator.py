import json
import zipfile
from io import BytesIO

from app.services.mt5_generator import (
    build_package_zip,
    condition_expression,
    generate_mq5_source,
    generate_package_payload,
    static_validate_mq5,
)


def frozen_strategy():
    return {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "strategy_code": "EVE-ABC123DEF456",
        "rule_hash": "a" * 64,
        "symbol": "XAU/USD",
        "source_validation_job_id": "223e4567-e89b-12d3-a456-426614174000",
        "source_kind": "evolution",
        "name": "Alignment Continuation · demo candidate",
        "family": "alignment_continuation",
        "version": "1.0",
        "rules": {
            "source_conditions": [
                {"field": "hour_utc", "value": 23},
                {"field": "week_of_month", "value": 3},
                {"field": "compression_band", "value": "expanded"},
            ],
            "condition_mode": "include",
            "direction_rule": "alignment_direction",
            "stop_atr": 0.9,
            "target_atr": 2.0,
            "horizon_minutes": 30,
            "cooldown_minutes": 30,
        },
        "validation_metrics": {
            "standard_cost": {
                "locked_test": {
                    "profit_factor": 1.4,
                    "expectancy_r": 0.179,
                    "trades": 150,
                    "max_drawdown_r": 8.2,
                }
            }
        },
        "validation_evidence": {"verdict": "Passed"},
        "status": "ready_for_mt5_generation",
    }


def test_condition_expression_supports_research_fields():
    expression = condition_expression([
        {"field": "hour_utc", "value": 23},
        {"field": "session", "value": "off_session"},
    ])
    assert "f.hour_utc == 23" in expression
    assert 'f.session == "off_session"' in expression


def test_generator_embeds_frozen_rules_and_safety_lock():
    frozen = frozen_strategy()
    source = generate_mq5_source(frozen)
    assert frozen["rule_hash"] in source
    assert "InpEnableTrading             = false" in source
    assert "EVE_STOP_ATR      = 0.90000000" in source
    assert "EVE_TARGET_ATR    = 2.00000000" in source
    assert "f.hour_utc == 23" in source
    assert "f.week_of_month == 3" in source
    assert 'f.compression_band == "expanded"' in source
    assert "return SignInt(f.alignment_score);" in source
    assert not static_validate_mq5(source, frozen)


def test_package_contains_source_rules_evidence_and_checksums():
    payload = generate_package_payload(frozen_strategy())
    package = {
        **payload,
        "strategy_name": frozen_strategy()["name"],
        "frozen_version": payload["version"],
        "rule_hash": frozen_strategy()["rule_hash"],
    }
    archive = build_package_zip(package)
    with zipfile.ZipFile(BytesIO(archive)) as zf:
        names = set(zf.namelist())
        assert payload["file_name"] in names
        assert "FROZEN_RULES.json" in names
        assert "VALIDATION_REPORT.json" in names
        assert "MANIFEST.json" in names
        assert "README.txt" in names
        assert "SHA256SUMS.txt" in names
        rules = json.loads(zf.read("FROZEN_RULES.json"))
        assert rules["stop_atr"] == 0.9
        source = zf.read(payload["file_name"]).decode()
        assert payload["source_sha256"]
        assert "OnTick" in source


def test_unsupported_condition_fails_generation():
    frozen = frozen_strategy()
    frozen["rules"]["source_conditions"] = [{"field": "unknown_feature", "value": "x"}]
    try:
        generate_mq5_source(frozen)
    except ValueError as exc:
        assert "Unsupported MT5 source condition field" in str(exc)
    else:
        raise AssertionError("Unsupported condition should not generate source")
