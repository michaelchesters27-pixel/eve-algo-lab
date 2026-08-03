# Railway service

FastAPI with persistent engines for EVE Algo Lab:

- Multi-timeframe candle ingestion and completed-bar sync.
- Resumable Learning Foundation builds.
- Autonomous new-candle learning, prediction grading and challenger training.
- Continuous 24/7 historical research on stored past data.
- Autonomous Strategy Idea Factory.
- Controlled Strategy Evolution Engine.
- Automatic M1 validation, cost stress, parameter-neighbourhood testing and immutable rule freezing.
- Automatic MT5 `.mq5` package generation from frozen rules.
- M5 approximation and M1 replay backtesting.

No new environment variables are required for v2.4. All workers are active through safe code defaults and share the historical learning cache to reduce Railway memory use.

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

## v2.3 validation protocol

M5 feature snapshots enter only after their source candle has closed. M1 replay resolves the price path conservatively, applies three execution-cost profiles and challenges nearby parameters. The locked period is never used to select a new parameter. Only a fully passed strategy receives an immutable frozen rule hash for the MT5-generator stage.

## v2.4 MT5 EA generation

A dedicated Railway worker now converts immutable frozen strategies into versioned `.mq5` packages. Generated source is stored with its frozen rules, validation report, manifest and SHA-256. No new environment variables are required. Every generated EA defaults to trading disabled and is intended for MetaEditor compilation and demo testing only.
