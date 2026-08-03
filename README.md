# EVE Algo Lab v2.3

EVE Algo Lab is a private XAU/USD research platform running on Supabase, Railway, Netlify and Twelve Data.

It stores M1, M5, M15, H1, H4 and D1 market history, learns automatically, researches historical relationships continuously, creates strategy candidates, evolves stronger descendants and now validates surviving strategies on stored M1 execution paths.

## v2.3 Automatic High-Resolution Validation

The autonomous Validation Lab:

1. Finds Champion, Elite and validated strategies that have not yet received M1 validation.
2. Recreates every eligible entry without same-candle look-ahead: an M5 feature snapshot can only enter on the first available M1 bar after the source M5 candle closes.
3. Replays the stop, target and maximum holding period on stored M1 candles.
4. Counts the stop first whenever one M1 candle could have reached both stop and target.
5. Tests standard, elevated and severe execution-cost assumptions.
6. Challenges nearby stop, target, holding-period and cooldown settings without choosing a new parameter from the locked period.
7. Reports yearly, monthly, weekday, session and regime behaviour.
8. Rejects weak strategies, requests more evidence for undersized samples, or marks a strategy Replay Validated.
9. Freezes an immutable SHA-256 rule version only when every MT5-readiness threshold passes.
10. Continues automatically on Railway while the browser and computer are off.

## Validation statuses

- **Rejected** — failed M1 replay, cost stress, data completeness, stability or parameter-neighbourhood safeguards.
- **Needs more evidence** — M1 result stayed positive but the high-resolution sample is too small.
- **Replay validated** — passed the core M1 replay but did not clear every final MT5-readiness threshold.
- **Ready for MT5 generation** — passed M1 replay, elevated-cost stress, parameter robustness and rule-freezing requirements.

## Important

“Ready for MT5 generation” does not mean live-ready. It means the exact rules are frozen and eligible for the next build: a versioned `.mq5` Expert Advisor, independent MT5 testing and demo forward validation.

See `DEPLOYMENT_GUIDE.md`.
