# EVE Algo Lab

EVE Algo Lab is a private XAU/USD market-research platform deployed across Netlify, Railway and Supabase.

Version 1.5 adds the first permanent **Learning Foundation** on top of the complete M1, M5, M15, H1, H4 and D1 market memory.

## What v1.5 builds

- Compact research snapshots every 15 minutes, calculated from the underlying M5 path.
- Rolling features for candle anatomy, ATR, momentum, volatility, compression, trend, streaks and sessions.
- Completed M15, H1, H4 and D1 context aligned without using future candles.
- Forward outcome labels for 5, 15, 30, 60 and 240 minutes.
- Weekday, month and quarter intelligence from the full stored D1 history.
- A permanent research-question queue generated from the available evidence.
- An exploratory discovery library.
- Prediction-ledger storage for later live prediction grading.
- Approved-versus-challenger model control.
- Automatic incremental learning checks after the initial build succeeds.

The first learning build is deliberately user-started. After it completes, Railway checks for new M5 candles every six hours and queues an incremental update only when new experience is available.

## Important boundary

v1.5 creates the data and governance needed for learning. It does not yet claim a trained predictive AI, profitable signals or validated discoveries. Calendar observations remain exploratory until later builds test stability across years and unseen periods.

## Repository layout

- `frontend/` — Netlify dashboard and secure proxy function.
- `railway/` — FastAPI service, ingestion worker, learning worker and backtester.
- `supabase/migrations/` — complete SQL history.
- `imported-strategies/` — source strategy used by the existing backtester.
- `SUPABASE_UPDATE_v1.5.sql` — the single SQL upgrade file for this release.

## Security

Secrets remain in Railway and Netlify environment variables. No API keys or service-role keys belong in GitHub.

## Data integrity

Raw candles remain immutable source evidence. Generated learning snapshots are idempotently upserted by `(symbol, snapshot_interval, candle_time)`, so interrupted builds can resume without duplicating research experience.
