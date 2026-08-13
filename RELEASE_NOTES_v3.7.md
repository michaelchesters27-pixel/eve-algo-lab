# EVE Algo Lab v3.7 — COMEX Closing Momentum v1

## Purpose

This release tests a separate, research-backed closing-momentum hypothesis after New York Morning Momentum v1 failed development. The strategy can open at most one XAU/USD position per New York weekday and has no averaging, basket, martingale or re-entry logic.

## Frozen hypothesis

- record the prior valid 13:29 `America/New_York` M1 close as a spot proxy for the 13:30 COMEX gold settlement
- at the next eligible weekday's 13:00 M1 open, buy if price is above that reference and sell if it is below
- skip the day when the prior reference is missing or the two prices are equal
- use one fixed 0.01-lot position and no late entry or same-day re-entry
- cap the trade at 0.25% of current balance with a hard money stop
- force-close any survivor at the 13:30 New York M1 open
- never hold overnight

## Locked proof gate

Development must contain at least 500 completed trades, positive net profit and expectancy, profit factor of at least 1.20, maximum drawdown no higher than 15%, and at least three profitable calendar years. Failure rejects v1; it does not authorize tuning on the same result. Only a development pass unlocks the final untouched third.

## Replay boundary

Spread, round-trip commission, optional entry/exit slippage, daylight saving and stop gaps are included. The stored spot price is only a proxy for the futures settlement, and M1 data cannot reproduce exact tick ordering or broker fills. A survivor would still require MT5 real-tick, adverse-cost and demo forward verification.

## Deployment

No Supabase SQL changes and no new Railway or Netlify variables are required.
