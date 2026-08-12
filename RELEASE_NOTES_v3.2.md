# EVE Command Centre v3.2 — Strategy Tester

This release makes the four-position Liquidity Basket idea measurable before an MT5 EA is built.

- Adds a dedicated Strategy Tester workspace.
- Adds a deterministic XAU/USD M1 liquidity-sweep replay with next-candle entry.
- Opens four equal positions by default and closes them on a combined basket target or hard basket loss.
- Includes spread, commission, slippage, maximum hold and cooldown controls.
- Supports full, development, untouched and custom chronological periods.
- Enforces an identical-settings development run before an untouched test can be accepted.
- Exposes slippage and XAU/USD contract-value calibration alongside spread and commission.
- Stores every run, position and basket in the existing backtest tables.
- Adds clear keep-testing, insufficient-evidence, mixed and failed verdicts.
- Shows profit factor, drawdown, win rate, worst basket, losing streak, expectancy, frequency and monthly balance path.
- Preserves the existing Fixed Ladder v2.61 diagnostic.
- Does not change live bot execution, Demo Fleet telemetry, existing packages or autonomous research workers.

No Supabase SQL or environment-variable changes are required.
