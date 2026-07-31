# EVE Algo Lab

EVE Algo Lab is a private market-research platform deployed across Netlify, Railway and Supabase.

Version 1.4 expands the permanent XAU/USD data foundation to six research timeframes:

- **M1** — execution path and micro-patterns
- **M5** — detailed intraday structure
- **M15** — setup context and momentum transitions
- **H1** — intraday trend/range regime
- **H4** — major swing context
- **D1** — weekdays, months, seasons and long-term regimes

Every timeframe has its own resumable historical download, exact database count, stored-date coverage, latest-candle sync and gap scan. The dashboard can queue all missing history in one action; Railway processes the jobs sequentially.

The existing M5 approximation and M1 high-resolution backtester are preserved.

## Repository layout

- `frontend/` — Netlify dashboard and secure proxy function.
- `railway/` — FastAPI service, ingestion worker and backtester.
- `supabase/migrations/` — complete SQL history.
- `imported-strategies/` — source strategy used by the existing backtester.
- `SUPABASE_UPDATE_v1.4.sql` — the single SQL upgrade file for v1.4.

## Security

Secrets remain in Railway and Netlify environment variables. No API keys or service-role keys belong in GitHub.

## Data integrity

Candles are stored by `(symbol, interval, candle_time)`, which prevents duplicates across retries. Only completed bars are written. Historical downloads resume from a saved cursor after a pause or Railway restart.
