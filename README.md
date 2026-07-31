# EVE Algo Lab

Private market-data, bot-backtesting and AI-learning platform for the EVE algo-bot programme.

This complete GitHub-ready release contains **Market Memory v1.1 plus Bot Backtester v1.2**. It imports the user's current MT5 source:

```text
EVE_Twelve_Data_Fixed_Ladder_v2.61.mq5
```

Source SHA-256:

```text
f033bc756b8a066b8fdfe780ca36fe82363b3b70c2e4dd4a15e7d57546d02da9
```

## Working in this release

- Existing XAU/USD M5 Market Memory and automatic live synchronisation
- Fixed Ladder v2.61 strategy registered as a permanent strategy version
- Background Railway backtest through all selected Supabase candles
- Exact v2.61 rule values:
  - 8 BUY STOPs and 8 SELL STOPs
  - 3.000 fixed spacing
  - 0.01 fixed lot by default
  - 2.000 fallback
  - first-bullet quick cut at 0.750
  - individual BE +0.150 after +1.500
  - newest unprotected bullet failure closes the basket
  - $5 target
  - basket peak protection at $4 with $1 giveback
  - immediate rearm
- Configurable starting balance, spread, commission and candle-path assumption
- Basket-level profit factor, drawdown, win rate and expectancy
- Position-level metrics retained separately
- Every position stored in `backtest_trades`
- Every completed campaign stored in `backtest_baskets`
- Recent basket report in the Netlify dashboard
- Explicit count of M5 candles where intrabar order cannot be proven
- Railway restart protection: an interrupted run is marked failed rather than left stuck

## Accuracy boundary

The strategy rules are imported from the actual v2.61 source. The first replay uses M5 OHLC candle paths, so it cannot prove the exact tick order when several levels, stops or break-even triggers occur inside the same M5 candle. Those candles are counted as ambiguous and the dashboard never presents the result as tick-accurate.

M1 replay is the next planned accuracy layer.

## Repository layout

```text
eve-algo-lab/
├── frontend/                 Netlify dashboard and secure Railway proxy
├── imported-strategies/      Exact imported MT5 source used for the model
├── railway/                  FastAPI, market worker and backtest engine
├── supabase/schema.sql       Complete fresh-project database setup
├── supabase/migrations/      One upgrade SQL for existing deployments
├── DEPLOYMENT_GUIDE.md       Exact upgrade steps
└── netlify.toml              Netlify monorepo configuration
```

## Security

Never put real keys into GitHub files. Twelve Data and Supabase secrets remain in Railway. Netlify keeps only the Railway URL and the matching private admin token in server-side environment variables.
