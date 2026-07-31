# EVE Algo Lab v1.6 — deployment guide

Use the existing **eve-algo-lab** GitHub repository. Do not upload this package to the separate trading-bot repository.

## Step 1 — run the Supabase update

1. Open the existing EVE Algo Lab project in Supabase.
2. Open **SQL Editor** and click **New query**.
3. Open `SUPABASE_UPDATE_v1.6.sql` from this package.
4. Copy the entire file into Supabase and click **Run**.
5. The expected result is **Success. No rows returned**.

The update preserves all existing data. It adds autonomous status fields, model artifacts, cycle audit records, research reports and prediction deduplication.

## Step 2 — replace the GitHub repository contents

1. Unzip `EVE-ALGO-LAB-v1.6-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the existing **eve-algo-lab** GitHub repository with everything inside that folder.
4. Commit the replacement to `main`.
5. Wait for Railway and Netlify to redeploy automatically.

## Step 3 — do not change variables

**No new Railway or Netlify variables are required.**

The v1.6 defaults are built into the code:

- autonomous check every 15 minutes;
- research cycle every 6 hours;
- challenger training check every 24 hours;
- autonomous model promotion enabled only when locked thresholds pass.

Leave the current variables exactly as they are.

## Step 4 — confirm autonomy

Because the v1.5 Learning Foundation is already complete, do not press **Build learning foundation** again.

After Railway has been online for about two minutes:

1. Open **Learning centre**.
2. Confirm **AUTO LEARNING — ACTIVE**.
3. Confirm **LAST CYCLE** and **NEXT CYCLE** are populated.
4. The first research and challenger cycle can take time because it reads the full learning history.

The optional **Run diagnostic cycle now** button only wakes the background worker immediately. It is not part of the normal routine.

## Expected normal behaviour

- Market open: new candles are synced and learned automatically.
- Market closed: no fake candles are created; due research and model checks can continue.
- Laptop off: Railway and Supabase continue operating.
- Railway restart: existing learning and candle data remain preserved.
