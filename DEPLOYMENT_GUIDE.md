# EVE Algo Lab v1.5 — deployment guide

Use the existing **eve-algo-lab** GitHub repository. Do not upload this package to the separate trading-bot repository.

## Step 1 — run the one Supabase update

1. Open the existing EVE Algo Lab project in Supabase.
2. Open **SQL Editor**.
3. Click **New query**.
4. Open `SUPABASE_UPDATE_v1.5.sql` from this package.
5. Copy the entire file and paste it into Supabase.
6. Click **Run**.
7. The expected result is **Success. No rows returned**.

This preserves every candle, ingestion job and backtest result. It adds the learning runs, learning state, research snapshots, calendar statistics, prediction ledger, questions, discoveries and model registry.

## Step 2 — replace the GitHub repository contents

1. Unzip `EVE-ALGO-LAB-v1.5-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the existing **eve-algo-lab** GitHub repository with everything inside that folder.
4. Commit the replacement to `main`.
5. Wait for Railway and Netlify to redeploy automatically.

## Step 3 — leave the variables alone

**No new Railway or Netlify variables are required for v1.5.**

Keep every current variable exactly as it is. Do not add or change anything for this build.

## Step 4 — start the first learning build

After both deployments are complete:

1. Open EVE Algo Lab.
2. Go to **Learning centre**.
3. Press **Build learning foundation** once.
4. Leave it running. The browser can be closed because Railway performs the work.
5. Do not repeatedly press the button.

The build is resumable. It creates 15-minute research anchors from M5 history rather than duplicating every raw candle, which keeps the research database compact.

## Step 5 — confirm completion

The Learning centre should show:

- Status **READY**.
- Progress **100%**.
- Research snapshots greater than zero.
- Outcomes labelled greater than snapshots because each snapshot can have five horizons.
- Calendar intelligence populated.
- Research questions populated.
- At least one approved foundation model.

After the first successful build, automatic incremental updates are enabled. EVE checks for new experience every six hours and queues an update only when newer M5 candles exist.
