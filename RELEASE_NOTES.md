# EVE Algo Lab v1.3.0

## M1 Market Memory and high-resolution replay

This release adds the next completed engine to the existing EVE Algo Lab deployment.

### New

- Complete resumable XAU/USD **1-minute historical downloader**.
- Separate M1 progress, candle count, batches and gap controls on the Netlify dashboard.
- Automatic Railway synchronisation for both **M1 and M5**, each shortly after its candle closes.
- **M1 high-resolution Fixed Ladder v2.61 backtest**.
- Resolution selector: M5 approximation or M1 replay.
- Permanent resolution field on every backtest run.
- Side-by-side M5 versus M1 profit factor, net profit and drawdown comparison.
- Ambiguous-bar reporting is resolution-aware: ambiguous M5 bars versus ambiguous M1 bars.
- Supabase indexes for chronological replay across the larger M1 dataset.

### Accuracy statement

M1 replay is substantially more precise than M5 because it replays five one-minute bars inside each five-minute period. It is still not tick-perfect. A single M1 candle can contain more than one material event, so tick replay remains the final execution-validation layer.

### Preserved

- Existing 477,000+ M5 candles.
- Existing M5 backtest results.
- Fixed Ladder v2.61 imported source.
- Railway, Netlify and Supabase variables.
- Resume protection, duplicate prevention and gap scanning.
