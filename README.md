# EVE Algo Lab

EVE Algo Lab is a private algo-trading research platform deployed across Netlify, Railway and Supabase.

Version 1.3 stores complete XAU/USD M5 and M1 history from Twelve Data and replays the imported `EVE_Twelve_Data_Fixed_Ladder_v2.61.mq5` strategy at two resolutions:

- **M5 approximation** for fast broad screening.
- **M1 high-resolution replay** for more reliable pending-order, stop and basket sequencing.

## Repository layout

- `frontend/` — Netlify dashboard and secure proxy function.
- `railway/` — FastAPI service, ingestion worker and backtester.
- `supabase/migrations/` — complete SQL history.
- `imported-strategies/` — source strategy used by the backtester.
- `SUPABASE_UPDATE_v1.3.sql` — the only new SQL file required when upgrading from v1.2.

## Security

Secrets remain in Railway and Netlify environment variables. No API keys or service-role keys belong in GitHub.

## Accuracy

M1 data reduces intrabar ambiguity but does not make the test tick-perfect. Results remain research evidence rather than a guarantee of future profitability.
