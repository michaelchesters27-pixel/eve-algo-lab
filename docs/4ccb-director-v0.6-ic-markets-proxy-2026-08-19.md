# 4CCB Director Broker-Cost Audit v0.6 — 2026-08-19

## Decision

Verdict: **M1_BROKER_PROXY_SURVIVES_EXTREME_STRESS**

The frozen v0.4 XAU/USD H1 candidate survives a new broker-cost robustness layer built around a public-data IC Markets MetaTrader 5 Raw Spread proxy, plus deliberately wider adverse cost scenarios. The signal rules were not changed for this test.

This remains a reverse-engineered public-chart hypothesis. It is not claimed to reproduce any private/VIP 4CCB rules and it is not approved for live capital.

## Frozen trading logic — unchanged

- Instrument: XAU/USD.
- Signal timeframe: H1.
- Four-candle structure.
- Candle 1 is the mother range; candles 2–4 remain fully inside candle 1 high-low.
- Small-body / wick-heavy qualification: average body/range <=45%; at least three candles <=55% body/range.
- Common overlap >=10% of the four-candle box.
- Maximum box width: 1.25 x ATR(20).
- Causal H1 EMA20/EMA50 directional bias measured before the setup.
- Trade only in the bias direction.
- Breakout must H1-close outside the box within four H1 candles.
- Breakout close must finish >=0.10 ATR beyond the relevant box edge.
- Entry: first stored M1 open at the next H1 open.
- Stop: opposite edge of the four-candle box.
- Target: 2R.
- Maximum hold: 24 H1 bars.
- One position at a time.
- If one M1 candle touches both stop and target, assume stop first.

## Broker proxy basis

The v0.6 engine uses a **0.18 XAU price-unit all-in proxy** for an IC Markets MetaTrader 5 Raw Spread micro-lot trade.

Public IC information used:
- Raw Spread MetaTrader commission: USD $7 per standard lot round turn.
- A 0.01-lot commission is $0.035 per side; on MT5 the displayed/charged micro-lot commission is rounded to $0.04 per side, therefore $0.08 round turn.
- IC states the average Raw Spread gold spread is 1 pip.
- IC's own XAUUSD quote examples display a 0.07 price difference as a 0.7 spread. From that display convention EVE infers 1 gold pip as approximately 0.10 XAU price units.
- EVE's existing XAU model uses USD $1 P/L for a $1 XAU move at 0.01 lot, so $0.08 commission is represented as 0.08 XAU price units.
- Proxy total: 0.10 spread + 0.08 commission = 0.18 XAU price units per trade.

This conversion is deliberately labelled **PUBLIC_DATA_PROXY_NOT_ACCOUNT_TELEMETRY**. The user's actual IC Markets MT5 Symbol Specification, observed spread distribution, account currency, tick value, commission records and slippage remain the authoritative next calibration source.

## Data and execution resolution

H1:
- 41,315 candles.
- 2020-01-24 02:00 UTC to 2026-08-19 16:00 UTC.

M1 at run time:
- 2,382,620 stored rows.
- Stored coverage begins 2020-04-06 13:16 UTC.
- 103,614 M1 rows were loaded across the relevant execution windows.

Signals:
- 77 eligible H1 signals.
- 2 occurred before stored M1 coverage and were excluded from the resolution denominator.
- 3 later signals were skipped because a prior position was still open.
- 72 trades were replayed on M1.
- 0 in-coverage signals were unresolved.
- In-coverage execution resolution: 100%.

## IC MT5 Raw proxy — 0.18 XAU price units

Overall:
- Trades: 72
- Wins: 42
- Losses: 30
- Win rate: 58.333%
- Net: +44.394R
- Expectancy: +0.61659R/trade
- Profit factor: 2.4890
- Max drawdown: 4.203R
- Longest losing streak: 4
- Same-M1 stop+target ambiguity: 0

2020–2023:
- 38 trades
- Net: +21.317R
- Expectancy: +0.56098R/trade
- PF: 2.3483

2024+:
- 34 trades
- Wins: 21
- Losses: 13
- Win rate: 61.765%
- Net: +23.077R
- Expectancy: +0.67873R/trade
- PF: 2.6480
- Max drawdown: 3.130R

2025–2026:
- 17 trades
- Wins: 12
- Losses: 5
- Win rate: 70.588%
- Net: +15.281R
- Expectancy: +0.89890R/trade
- PF: 3.6689
- Max drawdown: 2.518R

## Direction split at the IC proxy

BUY:
- 46 trades
- 31 wins / 15 losses
- Net: +39.074R
- Expectancy: +0.84945R/trade
- PF: 3.5805
- Max drawdown: 4.203R

SELL:
- 26 trades
- 11 wins / 15 losses
- Net: +5.320R
- Expectancy: +0.20460R/trade
- PF: 1.3626
- Max drawdown: 7.583R

The buy side remains materially stronger. The sell side is still positive, so no post-hoc long-only rule change is justified from this dataset.

## Deliberate adverse-cost stress

At 0.25 XAU price units per trade:
- Overall: +43.242R, expectancy +0.60058R, PF 2.4230.
- 2024+: +22.354R, expectancy +0.65748R, PF 2.5531.

At 0.35 XAU price units per trade:
- Overall: +41.595R, expectancy +0.57771R, PF 2.3329.
- 2024+: +21.322R, expectancy +0.62713R, PF 2.4262.

At 0.50 XAU price units per trade:
- Overall: +39.126R, expectancy +0.54341R, PF 2.2062.
- 2024+: +19.775R, expectancy +0.58160R, PF 2.2526.
- 2025–2026: +12.859R, expectancy +0.75638R, PF 2.8327.

Every predefined v0.6 cost gate passed.

## Failure-margin scan

A separate coarse 0.01-price-unit grid was used only to find the approximate cost level at which the 2024+ robustness gate fails. It was not used to tune the strategy.

Gate: at least 20 trades, positive net R, positive expectancy and PF >=1.20.

- Last passing cost: **1.94 XAU price units/trade** — +4.915R, +0.14455R expectancy, PF 1.2042.
- First failing cost: **1.95 XAU price units/trade** — +4.811R, +0.14151R expectancy, PF 1.1994.

This is a robustness margin under the simplified fixed-cost model. It must not be interpreted as a realistic expected broker cost or as proof that live execution will match historical replay.

## Director decision

The candidate advances another gate, but the trading logic remains frozen and live-capital approval remains **NO**.

Next workstream:
1. Capture the exact IC Markets MT5 XAUUSD Symbol Specification from the user's connected terminal: point, tick size, tick value, contract size, minimum/step/maximum volume and account currency.
2. Record real demo spread observations instead of relying on the 1-pip public average; calculate median, P75, P90, P95 and worst observed spread at signal/entry times.
3. Record requested versus actual fill to measure entry and exit slippage.
4. Record actual MT5 commission and any overnight financing on completed shadow trades.
5. Feed those measured costs into the same frozen M1 replay without changing the signal definition.
6. Start a shadow/paper forward ledger for every new qualifying 4CCB setup.
7. Keep both BUY and SELL logic unchanged during the forward phase.
8. No real-money automation until the forward ledger and account-specific execution calibration support the historical result.

The project standard remains: no cherry-picking, no hidden rule changes, no promotion from headline profit alone.
