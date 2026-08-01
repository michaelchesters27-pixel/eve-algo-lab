# Deploy EVE Algo Lab v2.0.0

## 1. Supabase

Open the existing EVE Algo Lab project, open SQL Editor, paste the complete contents of `SUPABASE_UPDATE_v2.0.sql`, and run it once. Wait for `Success. No rows returned`.

The update preserves every existing candle, learning snapshot, discovery, model and backtest.

## 2. GitHub

Unzip the GitHub-ready package. Open the inner `eve-algo-lab` folder and replace the contents of the existing EVE Algo Lab repository with everything inside it. Commit the replacement.

## 3. Railway and Netlify

Allow the existing GitHub deployments to finish. Do not add or change any variables.

## 4. Verify

Open EVE, press `Ctrl + F5`, and select **Strategy Lab**.

After the Railway startup delay, verify:

- Strategy worker status is ACTIVE.
- Worker heartbeat shows a recent time.
- Candidates queued is above zero once validated/promising research exists.
- Completed and states-scanned counts begin rising.
- Candidate Explorer opens finished results.

The Strategy Lab runs in Railway with the browser and computer switched off.
