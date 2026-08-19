# 4CCB H1 Bias Backtest — 2026-08-19

- Symbol: XAU/USD
- H1 candles: 41,314
- History: 2020-01-24 02:00 UTC to 2026-08-19 15:00 UTC
- Development candles: 27,542 (first two-thirds)
- Untouched candles: 13,772 (final third)
- Variants tested: 504
- Bias methods: 24-H1 momentum, 72-H1 momentum, causal H1 EMA20/EMA50 alignment, last close versus midpoint of previous 20-H1 range.
- Bias rule: every trade must agree with bias calculated before the first candle of the four-candle box.

## Development champion

Rules:
- Mode: plain 4CCB breakout
- Bias: 24-H1 momentum
- Box max: 1.5 ATR(20)
- Entry confirmation: touch of box edge
- Reward:risk: 2.0R
- Stop: opposite side of four-candle box

Development metrics:
- Trades: 844
- Wins: 321
- Losses: 523
- Win rate: 38.033%
- Net: +85.303R
- Expectancy: +0.10107R/trade
- Profit factor: 1.1639
- Max drawdown: 23.351R

## Frozen untouched test

- Trades: 346
- Wins: 124
- Losses: 222
- Win rate: 35.838%
- Net: -0.046R
- Expectancy: -0.00013R/trade
- Profit factor: 0.9998
- Max drawdown: 35.882R
- Longest losing streak: 16
- Counter-bias breakouts filtered: 411

Verdict: NO_CONFIRMED_OUT_OF_SAMPLE_EDGE.

## Full-history champion metrics

- Trades: 1,190
- Wins: 445
- Losses: 745
- Win rate: 37.395%
- Net: +85.257R
- Expectancy: +0.07164R/trade
- Profit factor: 1.1149
- Max drawdown: 35.882R

Notes: This is a reverse-engineered research family based on visible chart behaviour and does not claim to reproduce any private/VIP rule set. The untouched result is the key robustness check; the frozen development champion did not retain an edge in the final third.
