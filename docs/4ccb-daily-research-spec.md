# 4CCB Daily

Research-only high-frequency branch derived from the 4CCB idea.

## Goal

Test whether Gold can support a 4CCB-style system that approaches one trade per trading day without destroying the historical edge.

## Non-negotiable separation

The existing frozen 4CCB candidate is not changed by this work. `4CCB Daily` is a separate strategy family and must earn its own validation.

## Causal daily design

- XAUUSD / XAU/USD.
- H1 source candles.
- One fixed four-H1-candle box per UTC trading day; the engine never looks ahead and then chooses the best box from that day.
- Fixed box start hours screened: 00:00, 04:00, 06:00, 08:00 and 12:00 UTC.
- Causal directional bias is calculated before the first box candle using either 24-H1 momentum or H1 EMA20/EMA50.
- Execution families: next-H1-open in bias direction, bias-aligned touch breakout, bias-aligned close breakout.
- Stop is the opposite side of the four-candle box.
- Targets screened at 1R, 1.5R and 2R.
- Maximum one new trade per UTC day.
- One position at a time.
- Maximum hold 12 H1 bars.
- Initial all-in broker-cost proxy: 0.18 XAU price units per trade. This will later be replaced/refined with the live IC Markets calibration data.

## Validation gates

History is chronological: 50% development, 25% validation selection, 25% final confirmation.

For a true `4CCB Daily` pass, both validation and confirmation must have:

- at least 75 trades;
- positive expectancy and net R;
- PF >= 1.15;
- trades on at least 70% of eligible trading days.

If an edge survives but frequency is below 70%, the engine reports `EDGE_FOUND_BUT_DAILY_FREQUENCY_NOT_CONFIRMED` rather than pretending the daily objective was achieved.

This is research only. It is not approved for live capital.
