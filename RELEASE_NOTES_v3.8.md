# EVE Algo Lab v3.8 — Gold Session Anomaly v1

## Purpose

This release tests the published gold return split between the overnight period and the COMEX day session. Both directions were written down before either development result: overnight long first, then the independently frozen day short if the first hypothesis fails.

## Research basis

- A 2018 *Journal of Economics and Finance* study reported significantly positive overnight and significantly negative daytime returns across COMEX gold futures, London spot fixes and gold-related assets: <https://econpapers.repec.org/RePEc%3Aspr%3Ajecfin%3Av%3A42%3Ay%3A2018%3Ai%3A3%3Ad%3A10.1007_s12197-017-9403-0>
- A 2014 *Applied Economics Letters* paper found the same split in COMEX front-month futures from 1985–2012, although the effect weakened over time: <https://www.tandfonline.com/doi/full/10.1080/13504851.2014.922661>
- CME's documented historic gold floor session was 08:20–13:30 New York time, which defines the frozen split: <https://www.cmegroup.com/tools-information/lookups/advisories/market-regulation/SER-5803.html>

## Frozen hypotheses

### Gold Overnight Long v1

- buy one fixed 0.01-lot XAU/USD position at the exact 13:30 `America/New_York` M1 open
- close at the next eligible weekday's exact 08:20 New York M1 open
- charge $0.70 per 0.01 lot at each eligible 17:00 rollover, with Wednesday charged three times

### COMEX Day Short v1

- sell one fixed 0.01-lot XAU/USD position at the exact 08:20 New York M1 open
- close at the exact 13:30 New York M1 open on the same weekday
- never hold the position overnight

Both legs skip a missing entry minute, prohibit late entry and same-day re-entry, include spread, commission and optional slippage, and cap total loss at 0.25% of current balance. There is no averaging, basket recovery or martingale.

## Locked proof sequence

Development must contain at least 500 completed trades, positive net profit and expectancy, profit factor of at least 1.20, maximum drawdown no higher than 15%, and at least three profitable calendar years. The API unlocks the untouched final third only when an exact-settings development run has a `promising` verdict; completion alone is not enough.

## Replay boundary

New York daylight saving, weekday/weekend boundaries, financing, spread, commission, slippage and stop gaps are replayed from verified M1 candles. M1 data cannot prove tick ordering or reproduce exact broker fills. The overnight financing value is a frozen conservative proxy; any survivor still requires broker-calibrated MT5 real-tick and demo-forward verification.

## Deployment

No Supabase SQL changes and no new Railway or Netlify variables are required.
