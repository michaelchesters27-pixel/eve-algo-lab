# EVE Algo Lab v3.3 — London Opening Range v1

## New strategy

London Opening Range v1 is an independent, falsifiable session-breakout hypothesis for XAU/USD:

- signal timeframe: M5, reconstructed only from complete stored M1 candles;
- timezone: Europe/London, with British daylight-saving time handled automatically;
- opening range: 08:00–08:30 London;
- entry: first directional M5 close at least 10% of range width outside the range, then enter at the next M5 open;
- stop: opening-range midpoint;
- target: 2R after modelled costs;
- entry cutoff: 11:30 London;
- force exit: 16:00 London;
- frequency: at most one trade per London date;
- risk: 0.25% of current balance, rounded down to broker lot step;
- protections: no martingale, no averaging down, no entry when minimum lot would exceed the risk cap.

## Tester integration

- New endpoint: `POST /api/backtests/london-opening-range`.
- Supports development first two-thirds, locked untouched final third, full-history exploration and custom dates.
- Untouched testing is blocked until a completed development run exists with identical strategy, cost and risk settings.
- Results include sessions seen, complete opening ranges, signals, size skips, trades, drawdown, expectancy, frequency, exit reasons and a blunt verdict.
- The web tester now opens on London Opening Range v1. Rejected liquidity strategies and the legacy Fixed Ladder diagnostic remain archived and selectable.

## Deployment

No database migration and no new environment variable are required.
