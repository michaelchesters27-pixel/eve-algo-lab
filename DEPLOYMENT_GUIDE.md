# EVE Algo Lab v1.4 — deployment guide

Use the existing **eve-algo-lab** GitHub repository. Do not upload this package to the separate trading-bot repository.

## Step 1 — run the one Supabase update

1. Open the existing EVE Algo Lab project in Supabase.
2. Open **SQL Editor**.
3. Click **New query**.
4. Open `SUPABASE_UPDATE_v1.4.sql` from this package.
5. Copy the entire file and paste it into Supabase.
6. Click **Run**.
7. The expected result is **Success. No rows returned**.

This preserves every existing M1/M5 candle and backtest result. It adds supporting indexes and improves gap reporting so expected market closures are separated from gaps requiring review.

## Step 2 — replace the GitHub repository contents

1. Unzip `EVE-ALGO-LAB-v1.4-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the existing **eve-algo-lab** GitHub repository with everything inside that folder.
4. Commit the replacement to `main`.
5. Railway and Netlify should redeploy automatically.

## Step 3 — update the Railway sync variable

Open Railway → EVE Algo Lab service → **Variables**.

If `AUTO_SYNC_INTERVALS` already exists, change it to exactly:

```text
1min,5min,15min,1h,4h,1day
```

Add this optional variable to stagger requests that share a candle boundary:

```text
AUTO_SYNC_STAGGER_SECONDS=3
```

Keep the existing variables unchanged:

- `TWELVE_DATA_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ADMIN_TOKEN`
- `CORS_ORIGINS`

Netlify still uses:

- `RAILWAY_API_URL`
- `EVE_ADMIN_TOKEN`

## Step 4 — queue the remaining history

After both deployments finish:

1. Open EVE Algo Lab.
2. Go to **Data foundation**.
3. Press **Queue all missing history** once.
4. Because M1 and M5 are already complete, EVE should queue **M15, H1, H4 and D1**.
5. Leave it running. Railway processes the downloads one at a time even when the browser is closed.
6. Do not repeatedly press the button.

Higher timeframes contain far fewer rows than M1, although H1 and D1 may reach farther back if Twelve Data provides older history.

## Step 5 — verify completion

For each timeframe, confirm:

- Status shows **COMPLETE**.
- Progress shows **100%**.
- **Stored from** and **Latest** contain dates.
- The candle count is greater than zero.
- The automatic post-download gap scan has completed.

The top summary reaches **6 / 6 datasets ready** when the full foundation is complete.
