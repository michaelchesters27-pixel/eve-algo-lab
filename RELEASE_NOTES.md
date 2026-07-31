# EVE Algo Lab v1.7

## Continuous Historical Research

### Added

- A dedicated Railway worker for historical research independent of market hours.
- Persistent Supabase research queue with safe job claiming and restart recovery.
- Automatic question generation across weekday, month, quarter, week-of-month, hour, session, regime, direction, alignment, compression, trend and candle-streak contexts.
- Tests across 15, 30, 60 and 240-minute outcomes.
- Research targets including excursion, absolute return, continuation, same-direction follow-through, alignment follow-through and upward-outcome probability.
- Chronological train, validation and locked-test evaluation.
- Year-stability checks and multiple-testing penalties.
- Rejected, promising and validated result classifications.
- Automatic promotion of surviving research into the existing question and discovery libraries.
- Visible worker heartbeat, current question, queue, completed tests, historical states scanned and result counts.

### Preserved

- Responsive Live Data fix from v1.6.1.
- Six-timeframe candle storage and automatic sync.
- Learning snapshots and outcome labels.
- Autonomous prediction grading and challenger-model governance.
- Existing backtesting engines and all stored Supabase data.

### Deployment

Run `SUPABASE_UPDATE_v1.7.sql` first, then replace the existing GitHub repository contents with this complete build. No variables need changed.
