# 4CCB Director Audit v0.4 — 2026-08-19

## Status

Verdict: **PROMOTE_TO_EXECUTION_VALIDATION**

This is a reverse-engineered public-chart research hypothesis. It is not claimed to reproduce any private/VIP rules.

Data: 41,315 XAU/USD H1 candles, 2020-01-24 02:00 UTC through 2026-08-19 16:00 UTC.

## Frozen primary candidate

- H1 only.
- Four-candle structure.
- Candle 1 is the mother range; candles 2-4 must remain fully inside candle 1 high-low.
- Small-body / wick-heavy qualification: average body/range <= 45%, with at least three of the four candles <= 55% body/range.
- Four-candle box must retain >= 10% common price overlap.
- Maximum four-candle box width: 1.25 x ATR(20).
- Directional bias: causal H1 EMA20 versus EMA50 at the start of the four-candle structure.
- Trade only in the bias direction.
- Breakout must be confirmed by an H1 close outside the four-candle box within the following four H1 candles.
- Entry: next H1 open.
- Stop: opposite side of the four-candle box.
- Target: 2R.
- Maximum hold: 24 H1 bars.

## Primary candidate results

Overall:
- Trades: 95
- Wins: 48
- Losses: 47
- Win rate: 50.526%
- Net: +40.514R
- Expectancy: +0.42647R/trade
- Profit factor: 1.8780
- Max drawdown: 5.290R
- Longest losing streak: 4
- Profitable calendar years: 7 of 7 (2020-2026)

Year by year:
- 2020: 19 trades, +4.847R, PF 1.4365
- 2021: 12 trades, +9.212R, PF 3.9731
- 2022: 11 trades, +3.972R, PF 1.7483
- 2023: 11 trades, +9.283R, PF 3.3024
- 2024: 21 trades, +7.110R, PF 1.6401
- 2025: 7 trades, +4.098R, PF 2.2752
- 2026 YTD: 14 trades, +1.993R, PF 1.2407

Recent 2025-2026:
- Trades: 21
- Wins: 10
- Losses: 11
- Net: +6.091R
- Expectancy: +0.29004R/trade
- Profit factor: 1.5299
- Max drawdown: 5.290R

## Predeclared context-filter test

Nine context filters were declared before the run. Selection was performed using only 2020-2023, then the winning filter was frozen and checked on 2024+.

Selected filter: **breakout close excess >= 0.10 x ATR(20)** beyond the box boundary.

2020-2023 selection period:
- Trades: 40
- Wins: 23
- Losses: 17
- Net: +26.140R
- Expectancy: +0.65349R/trade
- Profit factor: 2.6931
- Max drawdown: 4.048R

Frozen 2024+ confirmation:
- Trades: 34
- Wins: 17
- Losses: 17
- Net: +12.418R
- Expectancy: +0.36524R/trade
- Profit factor: 1.7133
- Max drawdown: 5.290R

The 0.20 ATR breakout-excess threshold also looked strong in both periods, but it was not the selected winner. It must remain a challenger rather than being substituted after seeing later results.

## Diagnostics that require independent validation

### Long/short asymmetry

Primary BUY trades:
- 58 trades
- 35 wins / 23 losses
- +40.427R
- Expectancy +0.69702R
- PF 2.7837
- Max DD 4.048R

Primary SELL trades:
- 37 trades
- 13 wins / 24 losses
- +0.087R
- Expectancy +0.00236R
- PF 1.0037
- Max DD 12.077R

Nearly all historical edge came from buys. This was discovered diagnostically on the full sample, so long-only must be validated independently before becoming a rule.

### Breakout timing

- First eligible H1 breakout bar: 22 trades, +14.906R, PF 2.6452
- Second: 30 trades, +8.112R, PF 1.5020
- Third: 19 trades, +16.183R, PF 4.0203
- Fourth: 24 trades, +1.314R, PF 1.0844

The fourth-hour breakout appears weak, but this is diagnostic and requires independent validation before exclusion.

### Session diagnostics

- 00-06 UTC: 45 trades, +22.988R, PF 2.0357
- 07-12 UTC: 20 trades, +8.988R, PF 2.0795
- 13-16 UTC: 5 trades, -0.096R, PF 0.9534
- 17-21 UTC: 7 trades, -4.300R, PF 0.3161
- 22-23 UTC: 18 trades, +12.934R, PF 2.7805

Sample sizes are small in several session buckets. No session exclusion is promoted from this diagnostic alone.

## Benchmark comparison

The broad small-body + 24H momentum + touch-breakout benchmark had 883 trades and PF 1.1675 over full history, but failed badly in recent history:
- 2025-2026: 228 trades, -6.658R, PF 0.9555
- 2026 YTD alone: -27.007R, PF 0.6392

This confirms the mother-bar containment, close confirmation and EMA context materially improve robustness versus the generic four-small-candle idea.

## Phase v0.5 gate

Do not deploy live yet. The next phase is execution validation:

1. Replay the frozen rule on lower-timeframe data to resolve intrabar stop/target order and next-open execution accurately.
2. Stress test realistic spread and slippage at 1x, 2x and 3x assumptions.
3. Independently test the long-only diagnostic without using full-history performance as a selection shortcut.
4. Independently test breakout-delay and session exclusions using walk-forward splits.
5. Freeze one final rule set.
6. Shadow/paper trade before any capital is exposed.

The candidate only advances to live automation if it survives these gates.
