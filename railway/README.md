# Railway service

FastAPI API with three persistent engines for EVE Algo Lab:

- Multi-timeframe candle ingestion and automatic sync.
- Resumable Learning Foundation builds and incremental updates.
- M5 approximation and M1 replay backtesting.

No new environment variables are required for v1.5.

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
