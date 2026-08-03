# Deploy EVE Algo Lab v2.2

## 1. Supabase

Open the existing EVE Algo Lab Supabase project and SQL Editor. Paste the complete contents of `SUPABASE_UPDATE_v2.2.sql` and run it once.

Wait for:

```text
Success. No rows returned
```

The update creates the Evolution state, lineage and child-experiment tables. It preserves all candles, learning snapshots, discoveries, Strategy Lab candidates, models and backtests.

## 2. GitHub

Unzip the GitHub-ready package. Open the inner `eve-algo-lab` folder and replace the contents of the existing EVE Algo Lab repository with everything inside it. Commit the replacement.

## 3. Railway and Netlify

Allow the existing GitHub deployments to finish.

Do not add or change Railway or Netlify variables. v2.2 is enabled through safe code defaults.

## 4. Verify

Open EVE, press `Ctrl + F5`, and select **Evolution Lab**.

Allow approximately 6–8 minutes after Railway starts. Verify:

- Evolution worker status becomes ACTIVE.
- Worker heartbeat shows a recent time.
- Active lineages becomes greater than zero when strong Strategy Lab candidates exist.
- Mutations are queued.
- Current mutation is populated.
- Completed and states-scanned counts begin increasing.
- The lineage leaderboard and evolution history populate.

The worker continues on Railway with the computer and browser switched off.
