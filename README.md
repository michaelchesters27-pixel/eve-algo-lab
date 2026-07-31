# EVE Algo Lab

EVE Algo Lab is a private XAU/USD market-research platform deployed across Netlify, Railway and Supabase.

Version 1.7 adds a dedicated **Continuous Historical Research Worker**. It runs in parallel with the existing autonomous learning engine and mines stored historical data whether XAU/USD is open or closed.

## What runs in parallel

### Live learning worker

- Syncs completed M1, M5, M15, H1, H4 and D1 candles.
- Adds new 15-minute market snapshots.
- Completes 5, 15, 30, 60 and 240-minute outcomes.
- Grades predictions and controls challenger-model training.

### 24/7 historical research worker

- Maintains a persistent queue of research questions in Supabase.
- Generates new questions automatically whenever the queue becomes low.
- Tests one question at a time against complete stored learning snapshots.
- Uses chronological training, validation and locked test periods.
- Checks year-by-year stability and applies a multiple-testing penalty.
- Rejects weak or unstable findings.
- Stores promising and validated findings in the Discovery Library.
- Continues working during trading hours, weekends and market holidays.
- Recovers queued work after Railway restarts without repeating completed jobs.

## Resource control

Historical research does not hammer Twelve Data. It operates on the data already stored in Supabase and keeps a refreshed in-memory research cache on Railway. It processes one experiment at a time with a controlled pause between experiments.

## Dashboard proof

The Learning Centre now shows:

- worker status and heartbeat;
- current historical question;
- queue size;
- completed questions;
- total historical states scanned;
- rejected, promising and validated counts;
- latest result and research generation.

## Important boundary

Continuous research is designed to discover and challenge statistical tendencies. It does not guarantee profitable trades. A result must survive unseen chronological data and stability checks before EVE labels it validated.

## Repository layout

- `frontend/` — Netlify dashboard and secure API proxy.
- `railway/` — FastAPI service, ingestion, learning, continuous research and backtesting workers.
- `supabase/migrations/` — complete SQL history.
- `imported-strategies/` — source strategy used by the existing backtester.
- `SUPABASE_UPDATE_v1.7.sql` — the single Supabase upgrade file for this release.
