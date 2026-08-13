# EVE Algo Lab v3.5 — Gold H1 Trend 55/20 v1

## Purpose

The H4 version showed positive development evidence but produced only 62 completed trades, below EVE's locked 100-trade proof threshold. Version 3.5 tests the pre-declared H1 follow-up without opening or learning from the untouched final third.

## Exact hypothesis

- latest completed D1 close versus 60 trading days earlier sets direction
- completed H1 close beyond the previous 55-H1 high or low triggers a signal
- entry at the first available M1 open
- one position only, risking 0.25% of current balance
- hard stop at 2 × simple H1 ATR(20)
- no fixed take profit
- exit after a completed H1 close through the opposite previous 20-H1 channel

## Replay realism

The M1 replay includes spread, commission, optional slippage, overnight long/short financing, Wednesday triple financing and weekend gap fills. Any survivor still requires MT5 real-tick and demo verification with actual IC Markets swap values.

## Proof gate

Development must produce at least 100 trades, positive net profit and expectancy, PF of at least 1.25 and maximum drawdown no higher than 15%. Only then may the exact frozen settings be tested on the untouched final third.

## Deployment

No Supabase SQL changes and no new Railway or Netlify variables are required.
