# EVE Algo Lab

Private market-data, backtesting and AI-learning platform for the EVE algo-bot programme.

This repository is a complete GitHub-ready **Foundation v1**. It does not alter or replace any current MT5 bot. It creates the permanent infrastructure every bot will be tested against.

## What is working in this release

- XAU/USD M5 historical downloader using Twelve Data
- Up to 5,000 candles per request
- Backward batching to the earliest available timestamp
- Safe resume after Railway restart
- Duplicate-safe candle upserts into Supabase
- Download progress, batch count and candle count
- Automatic latest-candle REST synchronisation after each M5 close
- Data-gap detection
- Netlify control dashboard
- Railway API and background worker
- Supabase storage for strategy versions, backtest runs and backtest trades
- Professional backtest-metrics calculator including profit factor and drawdown

## What comes next

The next release imports the exact current momentum-basket bot rules/source and runs the first real historical backtest. The existing database and dashboard remain in place.

## Repository layout

```text
eve-algo-lab/
├── frontend/                 Netlify dashboard + secure Railway proxy
├── railway/                  FastAPI API, worker and Twelve Data downloader
├── supabase/schema.sql       Complete database setup
├── DEPLOYMENT_GUIDE.md       Step-by-step deployment
└── netlify.toml              Netlify monorepo configuration
```

## Security

Never put real keys into GitHub files. All secrets are supplied through Railway and Netlify environment variables. The browser never receives the Twelve Data key, Supabase service-role key or EVE admin token.

## Important scope note

Foundation v1 creates verified candle history and the testing infrastructure. Precise historical replay of a multi-order momentum basket will eventually use M1 or tick data underneath the M5 strategy so the engine can resolve the order of entries and stops inside a candle.
