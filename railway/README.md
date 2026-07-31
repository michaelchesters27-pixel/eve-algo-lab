# Railway service

FastAPI API and persistent ingestion worker for EVE Algo Lab.

The worker supports `1min`, `5min`, `15min`, `1h`, `4h` and `1day` historical backfills and automatic completed-candle synchronisation.

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
