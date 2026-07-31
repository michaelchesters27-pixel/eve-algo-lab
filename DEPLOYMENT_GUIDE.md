# EVE Algo Lab v1.3 — deployment guide

Use the existing `eve-algo-lab` GitHub repository. Do not upload this update to the separate momentum-bot repository.

## Step 1 — run one Supabase SQL file

1. Open the existing **eve-algo-lab** project in Supabase.
2. Click **SQL Editor**.
3. Click **New query**.
4. Open `SUPABASE_UPDATE_v1.3.sql` from this package in Notepad.
5. Press **Ctrl+A**, then **Ctrl+C**.
6. Paste it into Supabase.
7. Click **Run**.
8. The expected result is **Success. No rows returned**.

This only adds performance indexes. It does not delete or replace the existing M5 history or backtest results.

## Step 2 — replace the GitHub repository contents

1. Unzip `EVE-ALGO-LAB-v1.3-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the existing **eve-algo-lab** GitHub repository with everything from that folder.
4. Commit the update to `main`.
5. Railway and Netlify will redeploy automatically.

Do not change the `eve-twelve-data-momentum-trader` repository.

## Step 3 — variables

No new mandatory variable is required. Existing variables remain:

### Railway

- `TWELVE_DATA_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ADMIN_TOKEN`
- `CORS_ORIGINS`

Optional Railway variable:

- `AUTO_SYNC_INTERVALS=1min,5min`

The code already defaults to `1min,5min`, so adding it is optional.

### Netlify

- `RAILWAY_API_URL`
- `EVE_ADMIN_TOKEN`

## Step 4 — start M1 Market Memory

1. Open the Netlify EVE Algo Lab site after both deployments finish.
2. Scroll to **M1 execution memory**.
3. Press **Download M1 history** once.
4. Leave it running. Railway continues even if the browser is closed.
5. Do not repeatedly press the button.

M1 contains roughly five times as many candles as M5, so the download and Supabase insertion will take longer.

## Step 5 — run the high-resolution replay

After M1 reaches 100%:

1. Open **Bot backtester**.
2. Select **M1 high-resolution replay**.
3. Leave the baseline settings unchanged for the first comparison.
4. Press **Run M1 high-resolution replay** once.
5. Wait for 100%.
6. Review the M5 versus M1 comparison panel.

## Important

M1 replay is higher resolution, not tick-perfect. It uses each one-minute OHLC path in chronological order. Tick history is still required where multiple material events occur inside the same M1 candle.
