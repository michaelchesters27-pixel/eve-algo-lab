from datetime import datetime, timedelta, timezone

from app.services.learning import (
    ContextLookup,
    HORIZON_BARS,
    LOOKBACK_BARS,
    MAX_FUTURE_BARS,
    build_calendar_statistics,
    build_learning_snapshot,
    generate_calendar_discoveries,
    generate_research_questions,
    is_snapshot_anchor,
    session_name,
)


def candle(timestamp, open_price, close_price, spread=1.0):
    return {
        "candle_time": timestamp,
        "open": open_price,
        "high": max(open_price, close_price) + spread,
        "low": min(open_price, close_price) - spread,
        "close": close_price,
        "volume": 100.0,
    }


def test_learning_snapshot_contains_features_and_all_outcomes():
    start = datetime(2025, 1, 6, 0, 0, tzinfo=timezone.utc)
    bars = []
    price = 2000.0
    for index in range(LOOKBACK_BARS + 1 + MAX_FUTURE_BARS):
        open_price = price
        close_price = price + 0.25 + (index % 3) * 0.05
        bars.append(candle(start + timedelta(minutes=5 * index), open_price, close_price, spread=0.4))
        price = close_price

    current_index = LOOKBACK_BARS
    snapshot = build_learning_snapshot(
        "XAU/USD",
        bars[:current_index],
        bars[current_index],
        bars[current_index + 1:],
    )

    assert snapshot["feature_version"] == "eve-features-v1"
    assert snapshot["snapshot_interval"] == "15min"
    assert snapshot["atr_14"] > 0
    assert snapshot["alignment_score"] > 0
    assert set(snapshot["outcome_horizons"]) == set(HORIZON_BARS)
    assert snapshot["outcome_complete"] is True
    assert snapshot["outcomes"]["60"]["direction"] == "up"


def test_recent_snapshot_can_store_partial_outcomes():
    start = datetime(2025, 2, 3, 0, 0, tzinfo=timezone.utc)
    previous = [candle(start + timedelta(minutes=5 * index), 2000 + index, 2000.5 + index) for index in range(LOOKBACK_BARS)]
    current = candle(start + timedelta(minutes=5 * LOOKBACK_BARS), 2300, 2301)
    future = [candle(current["candle_time"] + timedelta(minutes=5 * (index + 1)), 2301 + index, 2301.5 + index) for index in range(6)]

    snapshot = build_learning_snapshot("XAU/USD", previous, current, future)

    assert snapshot["outcome_complete"] is False
    assert snapshot["outcome_horizons"] == [5, 15, 30]


def test_calendar_statistics_questions_and_discoveries_are_generated():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = []
    timestamp = start
    while len(rows) < 800:
        if timestamp.weekday() < 5:
            weekday_boost = 8 if timestamp.weekday() == 1 else 2
            month_boost = 5 if timestamp.month == 3 else 0
            open_price = 1500 + len(rows) * 0.5
            close_price = open_price + (2 if len(rows) % 2 == 0 else -1)
            rows.append(candle(timestamp, open_price, close_price, spread=weekday_boost + month_boost))
        timestamp += timedelta(days=1)

    statistics_rows = build_calendar_statistics("XAU/USD", rows)
    questions = generate_research_questions("XAU/USD", statistics_rows)
    discoveries = generate_calendar_discoveries("XAU/USD", statistics_rows)

    assert len([row for row in statistics_rows if row["dimension"] == "weekday"]) == 5
    assert len([row for row in statistics_rows if row["dimension"] == "month"]) == 12
    assert any("weekday" in question["question_key"] for question in questions)
    assert any(question["question_key"] == "multihorizon-alignment-60m" for question in questions)
    assert discoveries
    assert all(item["status"] == "exploratory" for item in discoveries)


def test_session_and_anchor_helpers():
    assert is_snapshot_anchor(datetime(2025, 1, 1, 12, 15, tzinfo=timezone.utc))
    assert not is_snapshot_anchor(datetime(2025, 1, 1, 12, 10, tzinfo=timezone.utc))
    assert session_name(datetime(2025, 1, 6, 1, 0, tzinfo=timezone.utc)) == "asia"

class FakeLearningRepo:
    def __init__(self, m5_rows, d1_rows):
        self.m5_rows = m5_rows
        self.d1_rows = d1_rows
        self.run = {
            "id": "run-1",
            "status": "running",
            "cursor_time": None,
            "snapshots_written": 0,
            "outcome_labels_written": 0,
        }
        self.learning_state = {}
        self.snapshots = {}
        self.calendar = []
        self.questions = []
        self.discoveries = []
        self.events = []

    async def get_learning_state(self, symbol, interval):
        return dict(self.learning_state)

    async def get_learning_run(self, run_id):
        return dict(self.run)

    async def count_market_candles(self, symbol, interval, date_from=None, date_to=None):
        return len(self.m5_rows)

    async def fetch_candles_page(self, symbol, interval, after=None, date_from=None, date_to=None, limit=1000):
        rows = self.m5_rows if interval == "5min" else self.d1_rows
        if date_from:
            start = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            rows = [row for row in rows if row["candle_time"] >= start]
        if after:
            start = datetime.fromisoformat(str(after).replace("Z", "+00:00"))
            rows = [row for row in rows if row["candle_time"] > start]
        return [
            {**row, "candle_time": row["candle_time"].isoformat()}
            for row in rows[:limit]
        ]

    async def update_learning_run(self, run_id, **changes):
        self.run.update(changes)

    async def bulk_upsert_learning_snapshots(self, rows, chunk_size=500):
        for row in rows:
            self.snapshots[row["candle_time"]] = row

    async def replace_calendar_statistics(self, symbol, rows):
        self.calendar = list(rows)

    async def upsert_research_questions(self, rows):
        self.questions = list(rows)

    async def upsert_discoveries(self, rows):
        self.discoveries = list(rows)

    async def refresh_learning_state(self, symbol, interval):
        self.learning_state.update({
            "snapshots_count": len(self.snapshots),
            "outcome_labels_count": sum(len(row["outcome_horizons"]) for row in self.snapshots.values()),
            "last_snapshot_time": max(self.snapshots) if self.snapshots else None,
        })

    async def upsert_learning_state(self, symbol, interval, **changes):
        self.learning_state.update(changes)

    async def log_event(self, level, component, message, details=None):
        self.events.append((level, component, message, details))

    async def delete_learning_generated_data(self, symbol, interval):
        self.snapshots.clear()


async def _run_small_foundation():
    from app.services.learning import LearningService

    start = datetime(2025, 1, 6, 0, 0, tzinfo=timezone.utc)
    m5_rows = []
    price = 2000.0
    for index in range(LOOKBACK_BARS + MAX_FUTURE_BARS + 80):
        row = candle(start + timedelta(minutes=5 * index), price, price + 0.2, spread=0.3)
        m5_rows.append(row)
        price += 0.2

    d1_rows = []
    day = datetime(2020, 1, 1, tzinfo=timezone.utc)
    while len(d1_rows) < 300:
        if day.weekday() < 5:
            d1_rows.append(candle(day, 1500 + len(d1_rows), 1501 + len(d1_rows), spread=2 + day.weekday()))
        day += timedelta(days=1)

    repo = FakeLearningRepo(m5_rows, d1_rows)
    service = LearningService(repo)
    await service.build_foundation("run-1", "XAU/USD", False)
    return repo


def test_learning_service_builds_resumable_foundation():
    import asyncio

    repo = asyncio.run(_run_small_foundation())
    assert repo.run["status"] == "complete"
    assert repo.run["progress_percent"] == 100
    assert repo.learning_state["status"] == "ready"
    assert repo.learning_state["initial_build_complete"] is True
    assert len(repo.snapshots) > 10
    assert len(repo.calendar) >= 20
    assert len(repo.questions) >= 5


def test_completed_context_lookup_prevents_lookahead():
    completed = datetime(2025, 1, 1, 12, 15, tzinfo=timezone.utc)
    lookup = ContextLookup([(completed, 0.5)])
    assert lookup.at(completed - timedelta(seconds=1)) is None
    assert lookup.at(completed) == 0.5
