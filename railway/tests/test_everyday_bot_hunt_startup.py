import asyncio

from app.services.everyday_bot_hunt_startup import seed_everyday_queue


class FakeRepo:
    def __init__(self):
        self.upserted = []
        self.events = []

    async def get_strategy_lab_state(self, symbol, snapshot_interval):
        return {"generator_generation": 2010}

    async def list_strategy_source_research(self, symbol, snapshot_interval, limit=250):
        return [{
            "id": "11111111-1111-1111-1111-111111111111",
            "job_key": "validated-source",
            "symbol": symbol,
            "snapshot_interval": snapshot_interval,
            "result_status": "validated",
            "confidence_score": 90,
            "effect_size": 8.0,
            "question": "Does Tuesday 13:00 continuation persist?",
            "test_definition": {
                "metric": "same_direction",
                "horizon_minutes": 30,
                "conditions": [
                    {"field": "weekday", "value": 2},
                    {"field": "hour_utc", "value": 13},
                ],
            },
        }]

    async def upsert_strategy_candidates(self, specs):
        self.upserted.extend(specs)

    async def log_event(self, level, component, message, details):
        self.events.append((level, component, message, details))


class FakeService:
    def __init__(self):
        self.repo = FakeRepo()


def test_startup_seed_inserts_everyday_candidates_even_without_queue_floor_logic():
    service = FakeService()
    count = asyncio.run(seed_everyday_queue(service))
    assert count > 0
    assert len(service.repo.upserted) == count
    assert all(item["rules"].get("research_track") == "everyday_bot_v1" for item in service.repo.upserted)
    assert service.repo.events
    assert service.repo.events[0][1] == "everyday-bot-hunt"
