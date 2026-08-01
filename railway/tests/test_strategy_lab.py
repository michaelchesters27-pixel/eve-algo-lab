from datetime import datetime, timedelta, timezone

from app.services.strategy_lab import evaluate_candidate, generate_candidate_specs


def source_job():
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "job_key": "history-direction-test",
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "question": "Does bullish direction improve continuation?",
        "result_status": "validated",
        "effect_size": 20.0,
        "test_definition": {
            "conditions": [{"field": "direction", "value": 1}],
            "metric": "continuation",
            "horizon_minutes": 60,
        },
    }


def make_rows(count=4000):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        bullish = index % 3 == 0
        direction = 1 if bullish else -1
        rows.append({
            "candle_time": (start + timedelta(minutes=15 * index)).isoformat(),
            "close": 2000.0,
            "atr_14": 10.0,
            "direction": direction,
            "alignment_score": direction,
            "outcomes": {
                "60": {
                    "close_return_pct": 1.0 if bullish else 0.5,
                    "max_up_atr": 2.5 if bullish else 1.2,
                    "max_down_atr": 0.2 if bullish else 0.2,
                    "direction": "up",
                }
            },
        })
    return rows


def test_generate_candidate_specs_are_complete_and_unique():
    specs = generate_candidate_specs([source_job()], generation=1)
    assert len(specs) == 2
    assert len({item["candidate_key"] for item in specs}) == len(specs)
    for item in specs:
        assert item["rules"]["stop_atr"] > 0
        assert item["rules"]["target_atr"] > 0
        assert item["status"] == "queued"


def test_strategy_candidate_uses_locked_chronological_data_and_beats_baseline():
    candidate = generate_candidate_specs([source_job()], generation=2)[0]
    candidate["id"] = "22222222-2222-2222-2222-222222222222"
    result = evaluate_candidate(candidate, make_rows())
    assert result["rows_scanned"] == 4000
    assert result["trades_total"] >= 80
    assert result["profit_factor"] > 1.15
    assert result["expectancy_r"] > 0
    assert result["profit_factor"] > result["baseline_profit_factor"]
    assert result["result_status"] in {"validated", "elite"}
    assert result["evidence"]["chronological_split"]["test_rows"] > 0
    assert result["evidence"]["caveats"]
