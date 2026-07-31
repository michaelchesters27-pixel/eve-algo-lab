# Project status — v1.7.3

## Current milestone

The autonomous learning engine and 24/7 historical worker are operational. Discovery Explorer can now retrieve and display completed historical findings through the Netlify proxy.

## v1.7.3 repair

- Allows `GET /api/research/results` through the Netlify function proxy
- Allows protected `POST /api/research/wake` for diagnostics
- Fixes `Route not allowed by the Netlify proxy`
- No database migration or variable change required
- Preserves all v1.7.2 Discovery Explorer evidence views and frontend reliability fixes

# Project status — v1.7.1

## Permanent data foundation

- Complete XAU/USD M1, M5, M15, H1, H4 and D1 market memory
- Railway completed-candle sync
- Supabase permanent storage
- Gap classification and review

## Learning foundation

- 15-minute multi-timeframe research snapshots
- 5, 15, 30, 60 and 240-minute outcome labels
- Calendar, session, volatility, momentum and regime context
- Prediction ledger and controlled model registry

## Autonomous learning

- Automatic incremental learning
- Prediction creation and grading
- Challenger training on chronological holdouts
- Promotion only after locked unseen-data improvement

## Continuous historical research

- Dedicated independent Railway worker
- Runs whether markets are open or closed
- Self-refilling research queue
- One controlled experiment at a time
- Chronological validation and locked testing
- Year-stability and multiple-testing controls
- Persistent job audit trail and restart recovery
- Automatic rejected, promising and validated classification
- Dashboard heartbeat and visible work counters

## Next major engine

v1.8: **Historical Pattern Match and Ask EVE** — compare the live six-timeframe state with the closest historical states and answer structured research questions from the validated evidence base.

## Not yet claimed

- Guaranteed profitable signals
- Tick-level predictive replay
- Fully generated deployable strategies
- Live paper trading
- Live MT5 execution

### v1.7.1 reliability repair
The continuous historical research worker now uses an RPC for stale-job recovery and explicit service-role table grants, eliminating the REST 404 observed during Railway startup.
