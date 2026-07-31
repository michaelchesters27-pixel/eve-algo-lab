# EVE Algo Lab v1.1 — deployment and upgrade guide

## Your current deployed project

You already have:

- GitHub repository: `eve-algo-lab`
- Railway public service
- Netlify dashboard
- Supabase database

For this upgrade, replace the repository contents with this complete version. Railway and Netlify will redeploy automatically from GitHub.

---

## Step 1 — Replace GitHub contents

1. Unzip `EVE-ALGO-LAB-v1.1-GITHUB-READY.zip`.
2. Open the inner `eve-algo-lab` folder.
3. Replace the contents of the GitHub repository with everything inside that folder.
4. Commit the update to `main`.

Do not upload the ZIP itself into the repository.

Railway and Netlify should each start a new deployment automatically.

---

## Step 2 — Check Railway variables

The Railway service requires:

```text
TWELVE_DATA_API_KEY=your private Twelve Data key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your private service_role key
ADMIN_TOKEN=your private token of at least 12 characters
CORS_ORIGINS=*
DEFAULT_SYMBOL=XAU/USD
DEFAULT_INTERVAL=5min
TWELVE_DATA_REQUEST_DELAY_SECONDS=2
TWELVE_DATA_BATCH_SIZE=5000
EXACT_COUNT_EVERY_BATCHES=5
AUTO_SYNC_ENABLED=true
AUTO_SYNC_OFFSET_SECONDS=22
LOG_LEVEL=INFO
```

Railway root directory remains:

```text
/railway
```

The public domain remains the URL already generated in Railway.

After deployment, opening the Railway URL should return a response containing:

```json
{"name":"EVE Algo Lab","status":"online","version":"1.1.0"}
```

---

## Step 3 — Add the missing Netlify admin token

Your Netlify site already has:

```text
RAILWAY_API_URL=https://eve-algo-lab-production.up.railway.app
```

It must also have:

```text
EVE_ADMIN_TOKEN=the exact same value used for Railway ADMIN_TOKEN
```

Path in Netlify:

**Site configuration → Environment variables → Add variable**

After adding it, trigger a new Netlify deployment. The browser never receives this token; the Netlify server function uses it when sending control commands to Railway.

---

## Step 4 — Supabase

If the original `supabase/schema.sql` was already run successfully, no new table is required for v1.1.

The full `supabase/schema.sql` remains idempotent and may be run again safely. An optional repair migration is included at:

```text
supabase/migrations/20260731112000_market_memory_v1_1_repair.sql
```

That migration resets the misleading v1 state where a latest-candle sync showed 100% before the historical download had started. The v1.1 backend also repairs this automatically, so running the repair migration is optional.

---

## Step 5 — Start Market Memory

After both deployments show success:

1. Open the Netlify dashboard.
2. Confirm **Railway service — Online**.
3. The historical progress should show **0%**, even though recent live candles may already be stored.
4. Press **Start historical download**.

The job will:

- ask Twelve Data for the earliest available XAU/USD M5 timestamp;
- download backwards in batches of up to 5,000 candles;
- upsert candles into Supabase without duplicates;
- save its cursor after every batch;
- update exact database counts every five batches;
- continue if the browser or laptop is closed;
- resume after a Railway restart;
- run a chronological gap scan after completion.

The button changes to **Pause download** while the job is active. Pausing does not delete any candles. Press **Resume historical download** later to continue from the saved cursor.

---

## What v1.1 fixes

The first release allowed automatic latest-candle sync to set the historical state to `complete`, which produced the misleading screen showing 100% with almost no history stored. v1.1 separates those concepts:

- live sync keeps recent M5 candles current;
- historical completion is only true when the oldest stored candle reaches the verified earliest Twelve Data boundary.

---

## Expected duration

The exact duration depends on Twelve Data response time and Supabase insert speed. With 5,000-candle batches and the default two-second safety delay, the M5 download should normally require roughly 110–120 Twelve Data requests for an estimated 500,000–600,000 candles.

---

## Do not do these

- Do not expose the Supabase service-role key in Netlify.
- Do not put the Twelve Data key in GitHub.
- Do not set a different Netlify `EVE_ADMIN_TOKEN` from Railway `ADMIN_TOKEN`.
- Do not delete `ingestion_state` during a download.
- Do not connect this foundation directly to a live MT5 account.
