# EVE Algo Lab v1.1.0 — Market Memory

## Fixed

- Automatic latest-candle sync no longer marks the full historical database 100% complete.
- A previously misleading v1 state is repaired automatically by the status API and next live sync.
- Railway restarts immediately return an interrupted running backfill to the queue.
- A forming M5 candle removed from the first provider batch no longer causes a false end-of-history result.
- A gap-scan failure cannot undo a successfully completed historical download.
- Backfill completion now requires verified historical boundaries.
- Netlify gives a precise message when `EVE_ADMIN_TOKEN` is missing.

## Added

- Manual Pause button.
- Resume from the exact saved cursor.
- Exact Supabase candle counts every five batches.
- Dedicated backfill-job status on the dashboard.
- Defensive duplicate removal within provider responses.
- Improved Twelve Data response validation and permanent-error handling.
- Version-controlled Supabase migrations.

## Tested

- Python compilation
- Seven automated unit tests
- Frontend JavaScript syntax
- Netlify function JavaScript syntax
- FastAPI application import with production-style environment variables
