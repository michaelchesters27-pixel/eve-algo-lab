# EVE Command Centre v3.1 — Organised Bot Library and Live Demo Fleet

## Organisation

- Replaced the long technical navigation with six focused workspaces.
- Only the selected workspace is visible, so relevant information sits directly in front of the user.
- Combined Strategy Lab, Evolution Lab and Validation Lab into one visible **Strategy Factory** with Build, Improve and Prove stages.
- Kept all underlying services, workers and stored evidence separate and operational.

## Bot Library

- Groups generated packages into everyday, Monday–Friday, short-window, monthly and seasonal categories.
- Supports combined labels such as a Monday + January + timed-window bot.
- Shows exact frozen conditions, current eligibility, next action, attach-to chart, whether it can remain attached, and London-time guidance.
- Cross-references live fleet heartbeats and marks a matching package **RUNNING IN MT5**.
- Warns the user not to attach another copy when one is already online.

## Demo Fleet

- Added authenticated best-effort MT5 heartbeat reporting.
- Shows online, stale, offline and detached EAs.
- Shows masked demo account, broker, chart, trading switches, current state, open positions and demo P/L.
- Detects duplicate attachments using strategy, account, broker, symbol and timeframe.
- Warns when the internal safety input or MT5 Algo Trading is disabled.
- Raises a prominent warning if a fleet-ready EVE EA reports from a real account.
- Removes the raw account login and original heartbeat payload from the public dashboard response.

## Generated EA downloads

- Existing and future package downloads receive the v3.1 telemetry wrapper at download time.
- Stored frozen packages remain immutable.
- Buy/sell execution calls, stops, targets, hold limits, cooldowns and frozen entry conditions are not changed.
- Telemetry stops in MT5 Strategy Tester and never participates in trade decisions.

## Database

`SUPABASE_UPDATE_v3.1.sql` adds one new table: `mt5_fleet_instances`.

No existing research, mutation, validation, candle or package table is changed or deleted.
