# EVE Algo Lab v3.9 — Asia Session Long v1

## Purpose

Gold Overnight Long v1 and COMEX Day Short v1 both failed their locked development tests. This release rejects them unchanged and tests two eastern-session hypotheses frozen before either result, without opening either failed strategy's untouched final third.

## Research basis

- Donati and Jung report a robust hat-shaped intraday gold pattern in which gold appreciates during eastern trading hours and depreciates through the rest of the day; their cost-inclusive simulations still retained some profitability: <https://research.cbs.dk/en/studentProjects/gold-price-dynamics-around-the-clock/>
- The Shanghai Gold Exchange documents a 20:00–02:30 night session and 09:00–15:30 day session in China Standard Time: <https://en.sge.com.cn/eng_trading_ProductsIntroduce>

## Frozen hypotheses

### Asia Session Long v1

- enter long at the exact 18:00 `America/New_York` M1 open on Sunday through Thursday
- associate that entry with the following Monday-through-Friday Shanghai session
- exit at the exact 15:30 `Asia/Shanghai` M1 open
- skip the session if the exact entry minute is absent; never enter late
- use one fixed 0.01-lot position with no averaging, martingale or re-entry
- include spread, round-trip commission and optional slippage
- cap total trade loss at 0.25% of current balance
- apply no rollover charge because entry occurs after the New York rollover and exit occurs before the next rollover

### Shanghai Day Long v1 — predeclared backup

- if the broader Asia Session Long development test fails, buy the exact 09:00 `Asia/Shanghai` M1 open Monday through Friday
- exit at the exact 15:30 `Asia/Shanghai` M1 open on the same day
- retain the same fixed lot, hard loss cap, cost model, missing-entry skip and no-re-entry rules
- this narrower official-session rule is declared before the broader eastern-session result and cannot be altered afterwards

## Locked proof gate

Development requires at least 500 completed trades, positive net profit and expectancy, profit factor of at least 1.20, maximum drawdown no higher than 15%, and at least three profitable calendar years. Only an exact-settings `promising` development verdict unlocks the untouched final third.

## Replay boundary

The replay converts every M1 timestamp independently through New York daylight saving and fixed China Standard Time. M1 cannot prove tick ordering or exact broker fills. Any survivor still requires MT5 real-tick, broker-cost and demo-forward verification.

## Deployment

No Supabase SQL changes and no new Railway or Netlify variables are required.
