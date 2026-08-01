# EVE Algo Lab v2.0.0 — Strategy Idea Factory

v2.0 adds a dedicated autonomous Strategy Lab worker alongside candle ingestion, learning and continuous historical research.

## What is new

- Converts validated and promising historical findings into complete strategy candidates.
- Generates explicit context filters, direction rules, ATR stops, ATR targets and holding periods.
- Tests candidates automatically on chronological training, validation and locked unseen periods.
- Uses non-overlapping trades and conservative stop-first handling when candle data cannot prove intrabar order.
- Compares each candidate with the same unfiltered baseline logic.
- Calculates profit factor, expectancy in R, win rate, maximum drawdown, yearly stability and baseline improvement.
- Classifies candidates as rejected, promising, validated or elite.
- Runs continuously on Railway whether markets are open or closed.
- Adds a Strategy Lab dashboard and Candidate Explorer.

## Safety boundary

Strategy Lab results are research-grade specifications, not live-trading instructions. Validated and elite candidates still require M1/tick replay, broker-cost testing and forward validation before an MT5 EA is created or deployed.

## Deployment

1. Run `SUPABASE_UPDATE_v2.0.sql` once.
2. Replace the existing GitHub repository contents with this complete folder.
3. Wait for Railway and Netlify to redeploy.
4. Force-refresh EVE and open Strategy Lab.

No environment-variable changes are required.
