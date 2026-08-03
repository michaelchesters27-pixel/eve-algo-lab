# Deploy EVE Command Centre v3.1

## 1. Run the one Supabase update

1. Open the existing EVE Algo Lab project in Supabase.
2. Open **SQL Editor**.
3. Open `SUPABASE_UPDATE_v3.1.sql` from this package.
4. Paste the full file and press **Run** once.

This creates only the Demo Fleet heartbeat table. Do not rerun old SQL files.

## 2. Deploy the complete repository

1. Unzip the v3.1 GitHub-ready package.
2. Open the inner `eve-algo-lab` folder.
3. Replace the entire contents of the existing EVE Algo Lab GitHub repository.
4. Commit the full replacement.
5. Wait for Railway and Netlify to redeploy.
6. Open EVE and press `Ctrl + F5`.

No Railway or Netlify variable changes are required.

## 3. Confirm the platform

- Home loads the Command Centre briefing.
- Research still refreshes.
- Strategy Factory shows Build, Improve and Prove.
- Bot Library groups bots by schedule.
- Demo Fleet no longer shows the SQL setup warning.
- Advanced still contains the optional legacy Fixed Ladder tool.

## 4. Make the two currently attached bots visible

Old compiled EAs cannot report because telemetry was not in their source.

For each bot, wait until it has no open position, then:

1. Find the exact package in **Bot Library**.
2. Download its fleet-ready `.mq5` or full package.
3. Compile it in MetaEditor.
4. In MT5 go to **Tools → Options → Expert Advisors**.
5. Tick **Allow WebRequest for listed URL** and add `https://evealgolab.netlify.app`.
6. Remove the old EA from the chart.
7. Attach the newly compiled EA to the same demo chart.
8. Restore the intended inputs and set `InpEnableTrading=true`.
9. Open Demo Fleet. The bot should appear online after its first heartbeat.

Do not leave old and new copies attached together; Demo Fleet will flag duplicates once both fleet-ready copies report.
