# Deploy EVE Algo Lab v2.3

## 1. Supabase

Open the existing EVE Algo Lab Supabase project and SQL Editor. Paste the complete contents of `SUPABASE_UPDATE_v2.3.sql` and run it once.

Wait for:

```text
Success. No rows returned
```

The update creates Validation Lab state, job and frozen-strategy tables. It preserves all candles, learning snapshots, discoveries, Strategy Lab candidates, evolution lineages, models and backtests.

## 2. GitHub

Unzip the GitHub-ready package. Open the inner `eve-algo-lab` folder and replace the contents of the existing EVE Algo Lab repository with everything inside it. Commit the replacement.

## 3. Railway and Netlify

Allow the existing GitHub deployments to finish.

Do not add or change Railway or Netlify variables. v2.3 is enabled through code defaults.

## 4. Verify

Open EVE, press `Ctrl + F5`, and select **Validation Lab**.

Allow approximately 8–10 minutes after Railway starts. Verify:

- Validation worker status becomes ACTIVE.
- Worker heartbeat shows a recent time.
- Surviving strategies are queued automatically.
- Current strategy changes to an M1 replay progress message.
- M1 windows scanned and completed counts increase.
- Completed results appear as Rejected, Needs Evidence, Replay Validated or Ready for MT5.
- A Ready strategy shows frozen rules and a rule hash.

The worker continues on Railway with the computer and browser switched off. The Wake button is only a diagnostic trigger.
