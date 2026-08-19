# 4CCB Director Execution Audit v0.5.1 — 2026-08-19

## Decision

Verdict: **M1_EXECUTION_SURVIVES_COST_STRESS**

The frozen v0.4 candidate has passed the first high-resolution execution gate. This is still a reverse-engineered public-chart hypothesis and is not claimed to reproduce private/VIP rules. Historical data has already informed earlier research, so this is an execution-robustness result rather than a pristine unseen discovery test.

## Frozen rule entering M1 validation

- Instrument: XAU/USD.
- Signal timeframe: H1.
- Four-candle structure.
- Candle 1 is the mother range; candles 2-4 remain fully inside candle 1 high-low.
- Small-body / wick-heavy qualification: average body/range <=45%; at least three candles <=55% body/range.
- Common overlap >=10% of the four-candle box.
- Maximum box width: 1.25 x ATR(20).
- Causal H1 EMA20/EMA50 directional bias measured before the setup.
- Trade only in the bias direction.
- Breakout must H1-close outside the box within four H1 candles.
- Breakout close must finish >=0.10 ATR beyond the relevant box edge. This filter was selected on 2020-2023 in v0.4 and frozen before later-history confirmation.
- Entry: first stored M1 open at the next H1 open.
- Stop: opposite edge of the four-candle box.
- Target: 2R.
- Maximum hold: 24 H1 bars.
- One position at a time.
- If one M1 candle touches both stop and target, assume stop first.

## Data coverage

H1:
- 41,315 candles.
- 2020-01-24 02:00 UTC to 2026-08-19 16:00 UTC.

M1:
- 2,382,602 stored rows at run time.
- Stored coverage: 2020-04-06 13:16 UTC to 2026-08-19 17:33 UTC.
- 103,614 M1 rows loaded across relevant execution windows.

Signals:
- 77 eligible H1 signals after the frozen 0.10 ATR breakout-close filter.
- 2 signals occurred before stored M1 coverage and were excluded from the execution-resolution denominator.
- 3 later signals were skipped because a prior position was still open.
- 72 trades were M1 replayed.
- 0 signals were unresolved inside stored M1 coverage.
- In-coverage execution resolution: 100%.

The first v0.5 run incorrectly counted the two pre-April-2020 signals as unresolved M1 data and printed a failure verdict despite strong performance. v0.5.1 corrected that classification: periods outside the database's M1 coverage are coverage exclusions, not missing execution data.

## Baseline cost stress — 0.05 XAU price units per trade

Overall:
- Trades: 72
- Wins: 42
- Losses: 30
- Win rate: 58.333%
- Net: +46.534R
- Expectancy: +0.64631R/trade
- Profit factor: 2.6187
- Max drawdown: 4.079R
- Longest losing streak: 4
- Same-M1 stop+target ambiguity: 0

2020-2023:
- Trades: 38
- Net: +22.116R
- Expectancy: +0.58201R/trade
- PF: 2.4296

2024+:
- Trades: 34
- Wins: 21
- Losses: 13
- Win rate: 61.765%
- Net: +24.418R
- Expectancy: +0.71818R/trade
- PF: 2.8389
- Max drawdown: 3.036R

2025-2026:
- Trades: 17
- Wins: 12
- Losses: 5
- Win rate: 70.588%
- Net: +16.266R
- Expectancy: +0.95680R/trade
- PF: 4.1270
- Max drawdown: 2.144R

Year by year at baseline cost:
- 2020: 14 trades, +3.870R, PF 1.4785
- 2021: 9 trades, +6.253R, PF 3.9949
- 2022: 7 trades, +5.684R, PF 3.5026
- 2023: 8 trades, +6.309R, PF 3.0875
- 2024: 17 trades, +8.153R, PF 2.0094
- 2025: 5 trades, +3.259R, PF 2.5860
- 2026 YTD: 12 trades, +13.007R, PF 5.1333

Every covered calendar year was profitable.

## Double cost — 0.10 XAU price units per trade

Overall:
- 72 trades
- +45.711R
- Expectancy +0.63488R
- PF 2.5677

2024+:
- 34 trades
- +23.902R
- Expectancy +0.70301R
- PF 2.7631

2025-2026:
- 17 trades
- +15.887R
- PF 3.9403

## Triple cost — 0.15 XAU price units per trade

Overall:
- 72 trades
- +44.888R
- Expectancy +0.62345R
- PF 2.5181

2024+:
- 34 trades
- +23.386R
- Expectancy +0.68783R
- PF 2.6903

2025-2026:
- 17 trades
- +15.508R
- PF 3.7670

All three 2024+ cost gates passed.

## Buy/sell behaviour under M1 replay

Baseline BUY:
- 46 trades
- 31 wins / 15 losses
- +40.524R
- Expectancy +0.88097R
- PF 3.7904
- Max DD 4.079R

Baseline SELL:
- 26 trades
- 11 wins / 15 losses
- +6.010R
- Expectancy +0.23115R
- PF 1.4225
- Max DD 7.162R

The buy side remains substantially stronger, but unlike the earlier H1-only diagnostic, the sell side is positive after M1 execution replay. Therefore no long-only retrofit is justified from the current evidence.

## Why M1 replay matters

The H1-only simulator must pessimistically choose a stop whenever an H1 candle contains both the stop and target. The M1 run found zero cases where one individual M1 candle touched both stop and target. The stronger M1 result is therefore consistent with the H1 simulator having been overly pessimistic about some intrahour ordering. This is an execution-resolution improvement, not permission to relax the strategy rules.

## Director decision

The candidate advances. It does **not** go live yet.

Next gates:
1. Replace arbitrary price-unit cost stress with an IC Markets / MT5 calibrated model: actual XAUUSD spread distribution, commission, symbol point/tick values and slippage assumptions.
2. Run a stricter adverse-cost stress above 0.15 price units as a failure-margin test.
3. Preserve both buy and sell rules for now; do not optimise away the weaker sell side after seeing the result.
4. Freeze the strategy logic after broker-cost calibration.
5. Build a signal-only shadow/paper phase that records every future qualifying setup without changing rules.
6. No real-capital automation until forward results confirm the historical edge.

The standard from here is no cherry-picking, no same-sample rule changes, and no promotion based on headline profit alone.
