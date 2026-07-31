# EVE Algo Lab v1.2.0 — Fixed Ladder Backtester

## Imported

- Exact current source: `EVE_Twelve_Data_Fixed_Ladder_v2.61.mq5`
- Source SHA-256: `f033bc756b8a066b8fdfe780ca36fe82363b3b70c2e4dd4a15e7d57546d02da9`

## Added

- Railway background backtest service
- Exact v2.61 fixed-ladder rule model
- Full-history XAU/USD M5 replay
- Bid/ask modelling from configurable spread
- Configurable commission and starting balance
- Three deterministic intrabar path modes
- Position and basket result storage
- Basket-level profit factor and drawdown reporting
- Separate position-level metrics
- Recent basket table in Netlify
- Backtest progress and cancellation
- Ambiguous M5 candle count and accuracy warning
- Interrupted-run handling after Railway restart
- `backtest_baskets` Supabase migration
- Imported strategy source stored in the repository

## Preserved

- Existing Market Memory
- Historical downloader
- Automatic M5 synchronisation
- Gap scan
- Existing Railway and Netlify variables

## Tested

- Python compilation
- Ten automated unit tests
- Fixed-ladder synthetic event tests
- Frontend JavaScript syntax
- Netlify proxy JavaScript syntax
