# EVE Algo Lab — deployment guide

Follow these steps in order. Do not add any secret key directly to the GitHub files.

---

## Part 1 — Create the Supabase database

1. Open your Supabase project.
2. Press **SQL Editor** in the left menu.
3. Press **New query**.
4. Open `supabase/schema.sql` from this project.
5. Copy the entire file and paste it into the Supabase query.
6. Press **Run**.
7. Wait for **Success. No rows returned**.

You need these two values later:

- **Project URL**: Supabase → Project Settings → API
- **service_role key**: Supabase → Project Settings → API → Legacy API keys or service role

The service-role key is private. It goes only into Railway.

---

## Part 2 — Put the project in GitHub

Create a new GitHub repository called:

```text
eve-algo-lab
```

Upload the **contents** of this folder to that repository. The repository homepage should show `frontend`, `railway`, `supabase`, `README.md` and `netlify.toml`.

Do not upload a second ZIP inside the repository.

---

## Part 3 — Deploy the Railway service

1. Open Railway.
2. Press **New Project**.
3. Choose **Deploy from GitHub repo**.
4. Select `eve-algo-lab`.
5. Open the new Railway service.
6. Go to **Settings**.
7. Set **Root Directory** to:

```text
/railway
```

8. Railway should detect the Dockerfile and redeploy.
9. Open **Variables** and add the following.

### Required Railway variables

```text
TWELVE_DATA_API_KEY=your real Twelve Data key
SUPABASE_URL=your Supabase project URL
SUPABASE_SERVICE_ROLE_KEY=your private Supabase service_role key
ADMIN_TOKEN=create one long private random password
CORS_ORIGINS=*
DEFAULT_SYMBOL=XAU/USD
DEFAULT_INTERVAL=5min
TWELVE_DATA_REQUEST_DELAY_SECONDS=8
TWELVE_DATA_BATCH_SIZE=5000
AUTO_SYNC_ENABLED=true
AUTO_SYNC_OFFSET_SECONDS=22
LOG_LEVEL=INFO
```

Use the same `ADMIN_TOKEN` later in Netlify.

10. Open Railway **Settings → Networking**.
11. Press **Generate Domain**.
12. Copy the full Railway URL. It will look similar to:

```text
https://eve-algo-lab-production.up.railway.app
```

13. Open that URL. You should see:

```json
{"name":"EVE Algo Lab","status":"online","version":"1.0.0"}
```

Do not start the historical download until the Netlify dashboard is deployed.

---

## Part 4 — Deploy the Netlify dashboard

1. Open Netlify.
2. Press **Add new site**.
3. Choose **Import an existing project**.
4. Select GitHub and choose `eve-algo-lab`.
5. Netlify reads the root `netlify.toml` automatically.
6. Before deploying, open **Environment variables** and add:

```text
RAILWAY_API_URL=the Railway URL copied above
EVE_ADMIN_TOKEN=the exact same ADMIN_TOKEN used on Railway
```

7. Press **Deploy**.
8. Open the Netlify site.
9. The left status should change to **Online**.

The Netlify function securely adds the admin token. It is never stored in browser JavaScript.

---

## Part 5 — Start the historical download

1. Open the Netlify dashboard.
2. Check the top left shows **Railway service — Online**.
3. Press **Start historical download**.
4. The job changes from `QUEUED` to `DOWNLOADING`.
5. Leave it running. You may close your browser or turn off your laptop. Railway continues the job.
6. The dashboard automatically refreshes every 10 seconds.

The downloader:

- asks Twelve Data for the earliest XAU/USD M5 timestamp;
- requests history in backward batches;
- stores it in Supabase;
- saves the next cursor after every batch;
- resumes from that cursor after a restart;
- merges duplicate candles safely;
- runs a gap scan when completed.

The default eight-second request delay is deliberately cautious. It can be changed in Railway later to match the API plan.

---

## Dashboard buttons

### Start historical download
Downloads the full available XAU/USD M5 history. It cannot start a duplicate job while one is active.

### Sync latest candles
Requests the newest 50 candles and safely merges them into Supabase.

### Scan gaps
Checks chronological candle spacing. Long market closures are marked separately. Short gaps are placed in the review count.

---

## Automatic operation

After the historical database is complete, Railway synchronises recent candles automatically after each M5 boundary plus 22 seconds.

The REST candle is used as the verified record. A live Twelve Data WebSocket layer is planned for the later real-time prediction and paper-trading release.

---

## How to check the database

In Supabase:

1. Press **Table Editor**.
2. Open `market_candles`.
3. Filter:
   - `symbol` equals `XAU/USD`
   - `interval` equals `5min`
4. Sort `candle_time` descending.

Other useful tables:

- `ingestion_state` — current download cursor and progress
- `ingestion_jobs` — every manual job
- `data_gaps` — missing-period review
- `system_events` — dashboard activity
- `backtest_runs` — future backtest summaries
- `backtest_trades` — future position-by-position results

---

## What not to do

- Do not paste keys into source files.
- Do not expose the Supabase service-role key in Netlify.
- Do not press force restart unless you intentionally want the cursor reset.
- Do not delete `ingestion_state` during a download.
- Do not connect this foundation directly to a live MT5 account.

---

## Next development stage

Provide the complete current momentum-basket bot file/ZIP. It will be imported as the first strategy adapter and tested against this database. The result report will include:

- gross profit and gross loss;
- net profit;
- profit factor;
- balance and equity drawdown;
- position and basket win rates;
- average win and loss;
- expectancy;
- recovery factor;
- session and hour breakdown;
- complete trade and basket history.
