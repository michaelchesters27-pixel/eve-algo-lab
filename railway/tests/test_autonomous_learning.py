from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.autonomy import (
    MODEL_HORIZONS,
    brier_score_for_prediction,
    build_challenger,
    discover_hypotheses,
    predict_context_model,
    prediction_payload,
    test_named_question as evaluate_named_question,
)


def synthetic_rows(count: int = 12000):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        timestamp = start + timedelta(minutes=15 * index)
        bullish_context = index % 4 in (0, 1, 2)
        regime = "trend_up" if bullish_context else "range"
        direction = 1 if bullish_context else -1
        alignment = 4 if bullish_context else -1
        # Strong deterministic context edge plus a small rotating noise component.
        if bullish_context:
            actual = "down" if index % 17 == 0 else "up"
        else:
            actual = "up" if index % 5 == 0 else "down"
        session = "london" if timestamp.hour in range(8, 13) else "off_session"
        excursion = 3.0 if session == "london" else 1.4
        outcomes = {}
        for horizon in (*MODEL_HORIZONS, 30):
            outcomes[str(horizon)] = {
                "direction": actual,
                "close_return_pct": 0.2 if actual == "up" else -0.2,
                "max_up_atr": excursion if actual == "up" else 0.4,
                "max_down_atr": excursion if actual == "down" else 0.4,
                "continuation": (actual == "up" and direction > 0) or (actual == "down" and direction < 0),
            }
        rows.append({
            "symbol": "XAU/USD",
            "snapshot_interval": "15min",
            "candle_time": timestamp.isoformat(),
            "weekday": timestamp.isoweekday(),
            "month": timestamp.month,
            "hour_utc": timestamp.hour,
            "session": session,
            "direction": direction,
            "compression_ratio": 0.6 if index % 7 == 0 else 1.0,
            "trend_12_atr": 0.3 if bullish_context else -0.05,
            "trend_48_atr": 0.2 if bullish_context else -0.02,
            "streak": 3 if bullish_context else -1,
            "regime": regime,
            "alignment_score": alignment,
            "outcomes": outcomes,
            "outcome_complete": True,
        })
    return rows


def test_challenger_uses_chronological_holdouts_and_beats_baseline():
    challenger = build_challenger(synthetic_rows(40000))
    assert challenger["training_rows"] == 28000
    assert challenger["validation_rows"] == 6000
    assert challenger["test_rows"] == 6000
    assert challenger["metrics"]["average_test_brier_gain"] > 0
    assert challenger["promotable"] is True


def test_prediction_payload_is_calibrated_and_explainable():
    rows = synthetic_rows()
    challenger = build_challenger(rows)
    snapshot = rows[-1]
    model_row = {"model_key": challenger["model_key"], "artifact": challenger["artifact"]}
    payload = prediction_payload(model_row, snapshot, 60, "shadow")
    probability_total = payload["probability_up"] + payload["probability_down"] + payload["probability_flat"]
    assert abs(probability_total - 1.0) < 1e-9
    assert payload["explanation"]["historical_bucket_sample"] >= 50
    assert payload["predicted_direction"] in {"up", "down", "flat"}


def test_named_question_and_autonomous_discovery_apply_locked_testing():
    rows = synthetic_rows()
    question = {
        "question_key": "three-candle-momentum-continuation",
        "question": "Do three candles continue?",
    }
    result = evaluate_named_question(question, rows)
    assert result["sample_count"] >= 150
    assert result["status"] in {"promising", "answered"}
    tests, findings = discover_hypotheses(rows)
    assert tests > 50
    assert findings
    assert all(item["evidence"]["multiple_testing_penalty_applied"] for item in findings)


def test_brier_score_rewards_correct_probability():
    prediction = {
        "probability_up": 0.8,
        "probability_down": 0.1,
        "probability_flat": 0.1,
    }
    assert brier_score_for_prediction(prediction, "up") < brier_score_for_prediction(prediction, "down")
