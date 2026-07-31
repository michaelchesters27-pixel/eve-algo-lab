# EVE Algo Lab v1.4.0

## Multi-timeframe Data Foundation

### New

- Permanent historical storage controls for **M15, H1, H4 and D1**.
- Unified six-timeframe dashboard covering M1 through D1.
- **Queue all missing history** action.
- Railway processes queued historical downloads sequentially.
- Automatic completed-candle synchronisation for all six timeframes.
- Small per-timeframe sync staggering to reduce simultaneous Twelve Data requests.
- Aggregate candle count, datasets-ready count, active downloads and review-gap count.
- Per-timeframe stored-from date, latest date, candle count, batches and progress.
- Improved gap output showing expected closures separately from review gaps.

### Preserved

- Existing M1 and M5 candles.
- Existing ingestion cursors and progress.
- Existing backtest runs and reports.
- M5 approximation and M1 high-resolution replay.
- Railway, Netlify and Supabase architecture.

### Deployment requirement

Run `SUPABASE_UPDATE_v1.4.sql`, deploy the complete repository replacement, and ensure Railway `AUTO_SYNC_INTERVALS` is set to `1min,5min,15min,1h,4h,1day` when that variable already exists.
