# EVE Algo Lab v1.2 — deployment guide

Your existing Market Memory data remains in Supabase. This update does not delete or redownload the 477,000+ XAU/USD M5 candles.

## Step 1 — run one Supabase SQL file

Before updating GitHub:

1. Open the `eve-algo-lab` project in Supabase.
2. Click **SQL Editor**.
3. Click **New query**.
4. Open this file from the ZIP:

```text
supabase/migrations/20260731125000_bot_backtester_v1_2.sql
```

5. Copy the complete SQL into Supabase.
6. Press **Run** once.

This creates only the `backtest_baskets` result table. Existing candles and tables are untouched.

## Step 2 — replace the GitHub repository

1. Unzip `EVE-ALGO-LAB-v1.2-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the GitHub repository with everything inside that folder.
4. Commit the replacement to `main`.

Do not upload the ZIP itself into GitHub.

Railway and Netlify should redeploy automatically.

## Step 3 — variables

No new variables are required.

Railway keeps:

```text
TWELVE_DATA_API_KEY
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
ADMIN_TOKEN
CORS_ORIGINS
DEFAULT_SYMBOL
DEFAULT_INTERVAL
```

Netlify keeps:

```text
RAILWAY_API_URL
EVE_ADMIN_TOKEN
```

`EVE_ADMIN_TOKEN` must still match Railway `ADMIN_TOKEN` exactly.

## Step 4 — check deployment

Railway root directory remains:

```text
/railway
```

Opening the Railway domain should show version `1.2.0`.

The Netlify dashboard should now contain a new section:

```text
Bot Backtester — EVE Fixed Ladder v2.61
```

## Step 5 — run the first backtest

1. Open the Netlify dashboard.
2. Scroll to **Bot Backtester**.
3. Leave the exact v2.61 rule values unchanged for the first baseline.
4. Set the starting balance you want to model.
5. Leave spread at `0.05` and commission at `$0.08 per 0.01 lot` unless you have better broker figures.
6. Press **Run full backtest** once.

Railway processes the test in the background. The browser and laptop can be closed.

The dashboard shows:

- progress through Market Memory;
- net profit;
- basket profit factor;
- maximum drawdown;
- basket win rate;
- total positions;
- total baskets;
- ending balance;
- ambiguous M5 candles;
- recent basket-by-basket outcomes.

## Important

This first result is **M5 candle-path approximation**, not tick accuracy. Do not approve the bot for live funds from this result alone. M1 replay and later tick testing must follow.

## Do not do these

- Do not restart the historical download.
- Do not delete `market_candles`.
- Do not press Run repeatedly while a backtest is active.
- Do not expose the Supabase service-role key in Netlify or GitHub.
- Do not interpret a high historical profit factor as a guarantee of future profit.
