# Project status

## Delivered — Market Memory v1.1

- [x] Supabase schema
- [x] Historical Twelve Data downloader
- [x] 5,000-candle backward batching
- [x] Earliest timestamp discovery
- [x] Resume cursor after restart
- [x] Manual pause and resume
- [x] Duplicate protection
- [x] Railway background worker
- [x] Latest-candle automatic sync
- [x] Live sync no longer falsely marks history 100% complete
- [x] Exact database counts during backfill
- [x] Gap scan
- [x] Netlify dashboard
- [x] Secure Netlify-to-Railway proxy
- [x] Clear warning when Netlify admin token is missing
- [x] Backtest storage tables
- [x] Profit factor and drawdown metric engine
- [x] Unit tests

## Next — Momentum backtester

- [ ] Import exact current bot source
- [ ] Reproduce pending-order and basket lifecycle
- [ ] M1/tick intrabar resolver
- [ ] Spread, commission and slippage model
- [ ] Full backtest screen and reports
- [ ] Compare old bot against current bot

## Later

- [ ] AI pattern labels and feature store
- [ ] Bot plus AI filter testing
- [ ] Explainable strategy factory
- [ ] Live paper trading
- [ ] Controlled MT5 bridge
