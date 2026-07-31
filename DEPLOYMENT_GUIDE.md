# EVE Algo Lab v1.7.1 — deployment guide

This is a reliability repair for the v1.7 continuous historical research worker. Existing candles, learning snapshots, research questions, discoveries and backtests are preserved.

## 1. Supabase

1. Open Supabase SQL Editor.
2. Open `SUPABASE_FIX_v1.7.1.sql` from this package.
3. Copy the complete file into a new SQL tab.
4. Press **Run**.
5. Continue only after Supabase reports success.

This small repair grants the Railway service role access to the new historical-research tables, adds a safe stale-job recovery RPC and reloads the PostgREST schema.

## 2. GitHub

1. Unzip the complete v1.7.1 package.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the existing `eve-algo-lab` GitHub repository with everything inside that folder.
4. Commit the replacement.

## 3. Railway and Netlify

Railway and Netlify should redeploy automatically from GitHub.

- Do not add or change Railway variables.
- Do not rebuild the learning foundation.
- Do not delete any Supabase data.

## 4. Verify

After Railway redeploys:

1. Open EVE Algo Lab.
2. Press **Ctrl + F5**.
3. Open **Learning centre**.
4. Within several minutes, the historical research worker should show a heartbeat and queued questions.
5. In Railway logs, searching `historical research worker` should show the worker startup line without a REST 404.
