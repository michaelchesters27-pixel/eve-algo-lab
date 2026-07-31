# EVE Algo Lab

EVE Algo Lab is a private XAU/USD market-research platform deployed across Netlify, Railway and Supabase.

Version 1.6 turns the completed Learning Foundation into a permanent **Autonomous Learning Engine**. After deployment, Railway maintains the learning database and runs research cycles without waiting for the dashboard or the user's computer.

## What v1.6 does automatically

- Checks the permanent M1, M5, M15, H1, H4 and D1 memory every 15 minutes.
- Queues incremental learning when a new 15-minute research state is available.
- Completes future-outcome labels as enough market time passes.
- Records fresh model predictions before their outcomes are known.
- Grades pending predictions when the matching outcomes become available.
- Tests the existing EVE question queue using chronological train and locked-test periods.
- Generates additional calendar, session, regime, momentum and volatility hypotheses.
- Applies sample-size, year-stability and multiple-testing controls.
- Trains a lightweight explainable challenger model on a chronological 70/15/15 split.
- Promotes a challenger only if it beats the approved baseline across every locked horizon and all promotion thresholds.
- Produces a persistent autonomous research report.

## Market-closed behaviour

Railway remains active when XAU/USD is closed. With no new candles it skips candle learning, but research, question testing, prediction grading for already-known outcomes and due challenger evaluation can still run. It does not invent candles or mark market closures as experience.

## No button routine

After v1.6 is deployed and the existing v1.5 foundation is already complete, no button press is required. The **Run diagnostic cycle now** control is optional and exists only to test the worker immediately.

## Important boundary

The autonomous engine improves the quality and accountability of EVE's research. It does not guarantee profitable trades. Findings remain conditional evidence, and model promotion requires locked unseen-data improvement.

## Repository layout

- `frontend/` — Netlify dashboard and secure proxy function.
- `railway/` — FastAPI service, ingestion, learning, autonomy and backtesting workers.
- `supabase/migrations/` — complete SQL history.
- `imported-strategies/` — source strategy used by the existing backtester.
- `SUPABASE_UPDATE_v1.6.sql` — the single SQL upgrade file for this release.

## Security and data integrity

Secrets remain in Railway and Netlify environment variables. Raw candles are never modified by the learning engine. Generated snapshots and predictions are idempotent, and every autonomous cycle has an audit record in Supabase.
