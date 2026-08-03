# EVE Algo Lab v2.4

EVE Algo Lab is a private XAU/USD research and strategy-development platform running on Supabase, Railway, Netlify and Twelve Data.

It stores six timeframes of history, learns automatically, researches historical relationships, generates strategy candidates, evolves stronger descendants, validates survivors on M1 execution paths and now creates versioned MT5 Expert Advisor source packages from immutable frozen rules.

## v2.4 Automatic MT5 EA Generator

The autonomous MT5 Generator:

1. Finds frozen strategies marked `ready_for_mt5_generation`.
2. Refuses unsupported or mutable rule definitions.
3. Translates EVE's calendar, session, volatility, trend, alignment and candle-state conditions into MQL5.
4. Embeds the strategy code, frozen version and SHA-256 rule hash in the source.
5. Generates ATR-based stop, target, maximum-hold and cooldown enforcement.
6. Adds risk sizing, spread protection, one-position control, daily-loss protection and persistent cooldown state.
7. Defaults every EA to `InpEnableTrading=false`.
8. Stores the `.mq5` source, frozen rules, validation report, manifest and checksums.
9. Makes a complete ZIP and the standalone `.mq5` source downloadable from MT5 Lab.
10. Continues automatically on Railway with the browser and computer switched off.

## Important

A generated EA is **ready for MetaEditor compilation and demo testing**, not ready for live money. MetaEditor must compile the `.mq5` file into an `.ex5`, and broker-side demo forward testing must confirm that execution resembles EVE's historical expectations.

See `DEPLOYMENT_GUIDE.md`.
