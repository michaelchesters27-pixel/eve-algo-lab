# EVE Algo Lab v2.4 — Automatic MT5 EA Generator

## Added

- Dedicated autonomous MT5 source-generation worker on Railway.
- Automatic queueing of immutable frozen strategies marked Ready for MT5 Generation.
- Rule translation for EVE calendar, UTC hour, session, regime, direction, alignment, compression, trend and candle-streak conditions.
- Locally calculated M5 ATR, compression, trend, regime, streak and multi-timeframe alignment features.
- Versioned `.mq5` Expert Advisor source with embedded frozen-rule SHA-256.
- Safety-first inputs: trading disabled by default, risk sizing, fixed-lot option, spread guard, slippage, daily-loss guard, one-position rule, cooldown and maximum hold.
- UK and New York daylight-saving session calculations.
- Downloadable ZIP containing `.mq5`, frozen rules, validation evidence, manifest, README and SHA-256 checksums.
- Standalone `.mq5` download.
- New MT5 Lab dashboard with worker monitor, latest package, package library and controlled handoff path.
- Binary-safe Netlify proxy support for ZIP downloads.

## Safety controls

- Only frozen strategies can be generated.
- Unsupported research fields fail safely instead of creating incomplete code.
- The frozen rule hash is embedded in the EA and package manifest.
- `InpEnableTrading` defaults to `false`.
- Every package is labelled demo-only.
- Source generation does not claim MetaEditor compilation or live readiness.

## Not included yet

- Automatic MetaEditor compilation to `.ex5`.
- Broker tick-data testing.
- Automatic demo account deployment.
- Live-money promotion.
