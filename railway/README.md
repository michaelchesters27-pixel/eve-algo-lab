# Railway service

FastAPI with four persistent engines for EVE Algo Lab:

- Multi-timeframe candle ingestion and completed-bar sync.
- Resumable Learning Foundation builds.
- Autonomous learning, research, prediction grading and challenger training.
- M5 approximation and M1 replay backtesting.

No new environment variables are required for v1.6. Autonomous defaults are loaded from code.

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
