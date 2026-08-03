# Deploy EVE Algo Lab v2.4

## 1. Supabase

Open the existing EVE Algo Lab Supabase project and SQL Editor. Paste the complete contents of `SUPABASE_UPDATE_v2.4.sql` and run it once.

Wait for:

```text
Success. No rows returned
```

The update creates MT5 generation state, jobs and package tables. It preserves all candles, learning snapshots, discoveries, strategies, evolution results, validation evidence, frozen rules and backtests.

## 2. GitHub

Unzip the GitHub-ready package. Open the inner `eve-algo-lab` folder and replace the contents of the existing EVE Algo Lab repository with everything inside it. Commit the replacement.

## 3. Railway and Netlify

Allow the existing GitHub deployments to finish.

Do not add or change Railway or Netlify variables. v2.4 is enabled through code defaults.

## 4. Verify

Open EVE, press `Ctrl + F5`, and select **MT5 Lab**.

Allow approximately 3–5 minutes after Railway starts. Verify:

- MT5 Generator status becomes ACTIVE or GENERATING.
- Worker heartbeat shows a recent time.
- Frozen strategies are queued automatically.
- A generated package appears in the package library.
- The ZIP and standalone `.mq5` download buttons work.
- The downloaded ZIP contains the EA source, frozen rules, validation report, manifest, README and checksums.

The Wake button is only a diagnostic trigger.

## 5. After download

Do not use the EA on a live account.

Open MetaEditor, compile the `.mq5` source, attach it to an XAUUSD M5 chart on an MT5 demo account, verify the UTC offset and inputs, then enable trading only on demo.
