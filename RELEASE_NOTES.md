# EVE Algo Lab v1.5.0

## Learning Foundation

### New

- Resumable Railway learning worker.
- Compact 15-minute research snapshots generated from M5 history.
- Feature engine covering candle anatomy, ATR, momentum, volatility, compression, trend, streaks and sessions.
- Completed M15, H1, H4 and D1 context aligned without look-ahead.
- Forward outcome labels at 5, 15, 30, 60 and 240 minutes.
- Full-history D1 weekday, month and quarter statistics.
- EVE-generated research-question queue.
- Exploratory discovery library.
- Prediction ledger ready for future live forecast grading.
- Approved-versus-challenger model registry.
- Learning Centre dashboard.
- Automatic incremental learning after the initial user-started build.
- Recovery of interrupted learning runs after Railway restarts.

### Preserved

- All M1, M5, M15, H1, H4 and D1 candles.
- Existing gap classifications and ingestion state.
- Existing M5 approximation and M1 replay backtests.
- Existing Railway, Netlify and Supabase variables.

### Not claimed in v1.5

- No trained predictive model yet.
- No live buy or sell signals.
- No validated profitable edge.
- No autonomous strategy generator yet.

### Deployment requirement

Run `SUPABASE_UPDATE_v1.5.sql`, deploy the complete repository replacement, then press **Build learning foundation** once. No environment-variable changes are required.
