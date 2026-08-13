# EVE Algo Lab v3.6 — New York Morning Momentum v1

## Purpose

This release tests a low-frequency alternative after the Gold H1 development run failed. The strategy can open at most one XAU/USD position per New York weekday and has no averaging, basket or re-entry logic.

## Frozen hypothesis

- require all 30 verified M1 candles from 08:30 through 08:59 `America/New_York`
- buy when the window close is above its open; sell when it is below
- enter only at the 09:00 M1 open; a missing 09:00 bar means no trade
- place the hard stop at the opposite edge of the completed 30-minute range
- risk 0.25% of current balance, rounded down to the configured lot step
- use one position, no fixed target, no re-entry and no overnight holding
- force-close any survivor at the 15:55 New York M1 open

## Locked proof gate

Development must contain at least 500 completed trades, positive net profit and expectancy, profit factor of at least 1.20, maximum drawdown no higher than 15%, and at least three profitable calendar years. Failure rejects v1; it does not authorize tuning on the same result. Only a development pass unlocks the final untouched third.

## Replay boundary

Spread, round-trip commission, optional entry/exit slippage, daylight saving and stop gaps are included. M1 data cannot reproduce exact tick ordering or broker fills, so a survivor would still require MT5 real-tick and demo forward verification.

## Deployment

No Supabase SQL changes and no new Railway or Netlify variables are required.
