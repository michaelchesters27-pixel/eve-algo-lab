# EVE Algo Lab v3.4 — Gold H4 Trend 55/20 v1

## New strategy

Gold H4 Trend 55/20 v1 is a slower XAU/USD trend-following hypothesis:

- direction filter: latest completed D1 close versus its close 60 trading days earlier;
- entry: completed H4 close beyond the previous 55-H4 high or low in the daily direction;
- execution: first available M1 open after the H4 close;
- stop: 2 × the simple average H4 true range over the latest 20 completed H4 bars;
- exit: completed H4 close through the opposite previous 20-H4 channel;
- take profit: none;
- exposure: one position only, with no averaging or martingale;
- risk: 0.25% of current balance, rounded down to broker lot step;
- costs: spread, commission, slippage, long/short overnight financing and Wednesday triple financing;
- gaps: stop orders fill at the first available M1 open when price gaps through the stop.

## Proof gate

- New endpoint: `POST /api/backtests/gold-h4-trend`.
- Requires complete M1, H4 and D1 Market Memory.
- Supports development first two-thirds, locked untouched final third, full-history exploration and custom dates.
- Untouched testing is blocked until a completed development run exists with identical rules, risk and costs.
- A pass requires at least 100 completed trades, positive net profit and expectancy, PF ≥ 1.25 and drawdown ≤ 15%.
- A surviving untouched result still requires neighbouring-channel stress, MT5 real ticks and demo forward testing.

## Deployment

No database migration and no new environment variable are required.
