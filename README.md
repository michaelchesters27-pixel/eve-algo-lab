# EVE Algo Lab

Private market-data, backtesting and AI-learning platform for the EVE algo-bot programme.

This repository is the complete GitHub-ready **Market Memory v1.1**. It does not alter or replace any MT5 bot. It creates the permanent historical database every bot will be tested against.

## Working in this release

- XAU/USD M5 historical downloader using Twelve Data
- Up to 5,000 candles per request
- Backward batching to the verified earliest available timestamp
- Safe pause and resume after a Railway restart or manual pause
- Duplicate-safe candle upserts into Supabase
- Exact database counts refreshed during the download
- Automatic latest-candle REST synchronisation after each M5 close
- Correct separation between live sync and historical-download completion
- Data-gap scan after the history completes
- Netlify control dashboard with Start, Pause, Resume, Sync and Gap Scan controls
- Railway API and background worker
- Supabase storage for strategy versions, backtest runs and backtest trades
- Backtest metric engine including profit factor and drawdown

## Repository layout

```text
eve-algo-lab/
├── frontend/                 Netlify dashboard and secure Railway proxy
├── railway/                  FastAPI API, worker and Twelve Data downloader
├── supabase/schema.sql       Complete idempotent database setup
├── supabase/migrations/      Version-controlled SQL
├── DEPLOYMENT_GUIDE.md       Exact deployment and upgrade steps
└── netlify.toml              Netlify monorepo configuration
```

## Security

Never put real keys into GitHub files. Twelve Data and Supabase secrets remain in Railway. The Netlify function holds only the Railway URL and the same private admin token used by Railway. None of those values are shipped to browser JavaScript.

## Next stage

The next release imports the exact current momentum-basket bot and runs its first proper historical backtest with profit factor, drawdown, basket statistics and a complete trade history.
