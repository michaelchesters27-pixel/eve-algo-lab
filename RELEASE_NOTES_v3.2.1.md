# EVE v3.2.1 — Liquidity Continuation

This patch adds a second, separately identified liquidity hypothesis after the original sweep-reversal development test failed.

- **New entry:** a directional M1 candle must close beyond the prior 20-candle high or low, align with EMA 50, then EVE enters in the breakout direction at the next candle open.
- **Fair comparison:** four equal 0.02-lot positions, the combined $4 profit target, $8 hard basket loss, costs and cooldown remain unchanged.
- **Account safety:** replay stops at exactly $0 and records `ACCOUNT RUIN LIMIT`; it cannot continue into a negative balance.
- **Evidence separation:** `liquidity_continuation` and `breakout_continuation` are locked into each run and untouched-period matching.
- **No live trading:** this is a historical research hypothesis, not an EA and not approval to trade real money.

No database migration or new environment variable is required.
