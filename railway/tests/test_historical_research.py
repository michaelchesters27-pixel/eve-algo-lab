from datetime import datetime, timedelta, timezone

from app.services.historical_research import (
    evaluate_research_spec,
    generate_research_specs,
    predicate_from_definition,
)


def test_generated_research_batch_is_deterministic_and_unique():
    first = generate_research_specs(3, 120)
    second = generate_research_specs(3, 120)
    assert len(first) == 120
    assert [item["job_key"] for item in first] == [item["job_key"] for item in second]
    assert len({item["job_key"] for item in first}) == 120
    assert all(item["status"] == "queued" for item in first)


def test_predicate_supports_derived_context_bands():
    predicate = predicate_from_definition({
        "conditions": [
            {"field": "alignment_band", "value": "strong_up"},
            {"field": "compression_band", "value": "compressed"},
            {"field": "streak_band", "value": "up3"},
        ]
    })
    assert predicate({"alignment_score": 4, "compression_ratio": 0.5, "streak": 4}) is True
    assert predicate({"alignment_score": 2, "compression_ratio": 0.5, "streak": 4}) is False


def test_locked_chronological_research_finds_stable_effect():
    rows = []
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for index in range(6000):
        timestamp = start + timedelta(hours=8 * index)
        weekday = (index % 5) + 1
        excursion = 1.6 if weekday == 1 else 1.0
        rows.append({
            "candle_time": timestamp.isoformat(),
            "weekday": weekday,
            "month": timestamp.month,
            "quarter": (timestamp.month - 1) // 3 + 1,
            "week_of_month": min(5, (timestamp.day - 1) // 7 + 1),
            "hour_utc": timestamp.hour,
            "session": "london",
            "direction": 1,
            "compression_ratio": 1.0,
            "trend_12_atr": 0.2,
            "streak": 1,
            "regime": "trend_up",
            "alignment_score": 3,
            "outcomes": {
                "60": {
                    "direction": "up",
                    "max_up_atr": excursion,
                    "max_down_atr": 0.2,
                    "close_return_pct": excursion / 10,
                    "continuation": True,
                }
            },
            "outcome_complete": True,
        })
    spec = {
        "question": "Does Monday change 60-minute excursion?",
        "test_definition": {
            "conditions": [{"field": "weekday", "value": 1}],
            "metric": "excursion",
            "horizon_minutes": 60,
        },
    }
    result = evaluate_research_spec(spec, rows, tests_considered=1000)
    assert result["result_status"] in {"promising", "validated"}
    assert result["effect_size"] > 30
    assert result["sample_count"] >= 100
    assert result["evidence"]["direction_consistent"] is True

import pytest

from app.services.supabase_repo import SupabaseRepository


@pytest.mark.asyncio
async def test_stale_historical_job_recovery_uses_rpc_not_direct_patch():
    repo = SupabaseRepository.__new__(SupabaseRepository)
    calls = []

    async def fake_rpc(name, payload):
        calls.append((name, payload))
        return 0

    repo.rpc = fake_rpc
    await repo.reset_stale_historical_research_jobs(stale_minutes=37)

    assert calls == [
        ("reset_stale_historical_research_jobs", {"p_stale_minutes": 37})
    ]

@pytest.mark.asyncio
async def test_discovery_explorer_query_filters_completed_results_safely():
    repo = SupabaseRepository.__new__(SupabaseRepository)
    calls = []

    async def fake_select(table, query):
        calls.append((table, query))
        return [{"id": "result-1", "result_status": "validated"}]

    repo.select = fake_select
    rows = await repo.list_historical_research_results(
        "XAU/USD", "15min", result_status="validated", order="stability", limit=75
    )

    assert rows[0]["result_status"] == "validated"
    assert calls[0][0] == "historical_research_jobs"
    query = calls[0][1]
    assert "status=eq.complete" in query
    assert "result_status=eq.validated" in query
    assert "order=stability_score.desc.nullslast" in query
    assert "limit=75" in query
