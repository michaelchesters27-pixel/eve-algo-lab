# Railway service

FastAPI with persistent engines for EVE Algo Lab:

- Multi-timeframe candle ingestion and completed-bar sync.
- Resumable Learning Foundation builds.
- Autonomous new-candle learning, prediction grading and challenger training.
- Continuous 24/7 historical research on stored past data.
- Autonomous Strategy Idea Factory.
- Controlled Strategy Evolution Engine.
- M5 approximation and M1 replay backtesting.

No new environment variables are required for v2.2. All new workers are active through safe code defaults and share the historical learning cache to reduce Railway memory use.

Local run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest -q
```

## v2.2 Evolution protocol

Evolution mutations are chosen using validation evidence only. The locked chronological period is reserved for readiness grading and a catastrophic-loss veto. Every result keeps its direct parent comparison and exact rule change.
