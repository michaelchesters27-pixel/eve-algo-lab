# Deploy EVE Command Centre v3.0.2

1. Unzip the v3.0.2 GitHub-ready package.
2. Open the inner `eve-algo-lab` folder.
3. Replace the full contents of the existing EVE Algo Lab GitHub repository.
4. Wait for Railway and Netlify to redeploy.
5. Open EVE and press `Ctrl + F5`.
6. Open **Advanced**.
7. Click **Legacy Fixed Ladder backtester**. It should open with a blank Current Test panel.
8. Click **View previous tests** only when you deliberately want the archive.

## Do not change

- Do not run Supabase SQL.
- Do not add or change Railway variables.
- Do not add or change Netlify variables.
- Do not rebuild the learning foundation.

v3.0.2 changes the legacy backtest workflow and adds one read-only active-run endpoint. Existing data is retained.
