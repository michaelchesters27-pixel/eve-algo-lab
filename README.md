# EVE Command Centre v3.0.2

EVE is a private XAU/USD research and MT5 bot-development platform using Supabase, Railway, Netlify and Twelve Data.

## What changed in v3.0.2

The optional Fixed Ladder replay now has a clean separation between a new test and stored historical runs.

- Opening the tool shows a blank **Current Test** workspace.
- Last week’s result is not loaded or presented automatically.
- **View previous tests** deliberately opens the archive.
- Archived tests show their stored date, replay resolution, metrics and an **ARCHIVED TEST** warning.
- Starting a new test clears any archived selection immediately.
- Basket reports appear only for the current completed test or a specifically selected archived test.
- The M5-versus-M1 comparison is kept inside the archive.
- A dedicated active-run route restores only a genuinely queued or running test after a refresh, without fetching completed history.

## Main Command Centre

1. **Home** — one briefing, one recommended action and system health.
2. **Research** — what EVE is learning and the evidence behind it.
3. **Strategy Factory** — build rules, improve survivors and demand high-resolution proof.
4. **Bot Factory** — generated MT5 packages and compilation instructions.
5. **Demo Testing** — which bot can be tested now, later today or in a future period.
6. **Advanced** — market memory, optional legacy tools, build history and activity logs.

## Important limitation

The Legacy Fixed Ladder Backtester is not a general MQ5 execution environment. Railway runs a manually recreated Python model for `EVE_Twelve_Data_Fixed_Ladder_v2.61.mq5`. A different EA must be compiled and tested through MetaTrader 5 Strategy Tester.

## Safety

All generated EAs default to `InpEnableTrading=false`. EVE cannot yet verify that an EA is physically attached to an MT5 terminal or receive completed demo-trade telemetry. Use a demo account only.
