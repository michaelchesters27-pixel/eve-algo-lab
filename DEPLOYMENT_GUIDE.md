# EVE Algo Lab v1.7 — deployment guide

Use the existing **eve-algo-lab** GitHub repository. Do not upload this package to the separate trading-bot repository.

## 1. Run the Supabase update first

1. Open the EVE Algo Lab project in Supabase.
2. Open **SQL Editor** and create a new query.
3. Open `SUPABASE_UPDATE_v1.7.sql` from this package.
4. Copy the complete file into Supabase.
5. Press **Run**.
6. Approve **Run query** if Supabase shows its normal safety warning.
7. Continue only after Supabase reports success.

This update creates new research tables and functions. It does not delete or replace candles, learning snapshots, discoveries, models or backtests.

## 2. Replace the GitHub repository contents

1. Unzip `EVE-ALGO-LAB-v1.7-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the existing **eve-algo-lab** GitHub repository with everything inside that folder.
4. Commit the replacement to `main`.
5. Wait for Railway and Netlify to redeploy automatically.
6. Open EVE and press **Ctrl + F5** once.

## 3. Do not change variables

No Railway or Netlify variables need added or changed. v1.7 defaults are active in code.

## Expected result

Within several minutes, the Learning Centre should show **24/7 Historical Research Worker** as active. The first startup may spend time loading the complete historical learning dataset. After that, the current question, heartbeat, queue and completed counts should begin moving automatically.

No button press is required. The worker operates while the browser and computer are off.
