# 4CCB H1 Candle-Structure Backtest — 2026-08-19

- Symbol: XAU/USD
- H1 candles: 41,315
- History: 2020-01-24 02:00 UTC to 2026-08-19 16:00 UTC
- Development: first 50% (20,657 candles), ending 2023-08-01 23:00 UTC
- Validation: next 25% (10,329 candles), ending 2025-05-04 17:00 UTC
- Chronological confirmation: final 25% (10,329 candles)
- 11 visible candle-relationship hypotheses screened
- 132 structure-screen variants
- Four strongest structure families tuned across 2,016 variants

## Structural screen

The four strongest structure families on development history were:

1. small_bodies
2. mother_bar_small_bodies
3. two_bull_two_bear
4. overlap_only

Notable screen leaders:

- small_bodies + 24-H1 momentum bias, plain breakout, 1.5 ATR box, 2R, touch: 454 trades, +57.405R, PF 1.2074.
- mother_bar_small_bodies + EMA20/50 bias, plain breakout, 1.5 ATR box, 2R, touch: 75 trades, +18.564R, PF 1.4272.
- two_bull_two_bear + 72-H1 momentum bias, plain breakout, 1.5 ATR box, 2R, touch: 488 trades, +49.358R, PF 1.1631.
- baseline overlap-only + 24-H1 momentum bias: 629 trades, +55.435R, PF 1.1420.

Pure contracting-range structure was weak in development (PF 0.8984 in its best screened representative), and mother-bar alone was only modest (PF 1.0825). The combination of a mother bar with small candle bodies was materially stronger than mother-bar alone.

## Development tuning clue

The strongest development rules were dominated by `mother_bar_small_bodies` with EMA20/EMA50 bias and a candle-close breakout confirmation. Examples:

- ATR max 1.25, RR 1.5, close confirmation: 47 trades, +21.490R, PF 2.2286, expectancy +0.457R/trade.
- ATR max 1.25, RR 2.0, close confirmation: 47 trades, +21.366R, PF 1.9928, expectancy +0.455R/trade.
- ATR max 1.5, RR 2.0, close confirmation: 58 trades, +22.310R, PF 1.7811.

The first rule means: candle 1 is the mother range; candles 2-4 remain completely inside its high-low; the four candles are wick-heavy/small-bodied (average body/range <=45% and at least three bodies <=55% of their own range); trade only with causal H1 EMA20/EMA50 bias; require an H1 close outside the box; enter next H1 open; stop on the opposite side of the four-candle box.

## Validation selection

The validation winner was a broader `small_bodies` rule:

- Bias: 24-H1 momentum
- Box max: 1.5 ATR(20)
- Confirmation: touch
- RR: 2.0
- Mode: plain

Validation metrics:

- Trades: 246
- Wins: 103
- Losses: 143
- Win rate: 41.870%
- Net: +52.181R
- Expectancy: +0.21212R/trade
- Profit factor: 1.3615
- Max drawdown: 11.768R

## Chronological confirmation of the frozen validation winner

- Trades: 183
- Wins: 60
- Losses: 123
- Win rate: 32.787%
- Net: -18.378R
- Expectancy: -0.10043R/trade
- Profit factor: 0.8510
- Max drawdown: 36.121R

Verdict: **NO_ROBUST_STRUCTURE_EDGE_CONFIRMED**.

## What the test suggests about the visible 4CCB candle qualification

The data points much more strongly toward **small-bodied / wick-heavy compression** than toward simple alternating colours, simple mother bars, or mechanically contracting candle ranges. The particularly strong development cluster was **mother bar + three contained candles + small bodies + directional bias + close-confirmed breakout**. That is the most useful reverse-engineering clue from this run, but it is not yet a proven trading edge and is not claimed to reproduce any private/VIP rules.

The final-quarter failure of the broader small-body champion also shows that candle shape alone is insufficient; an additional context/level rule is likely still missing.
