# EVE Algo Lab v2.3 — Automatic High-Resolution Validation Pipeline

## Added

- Dedicated autonomous M1 validation worker on Railway.
- Automatic queueing of Champion, Elite and validated strategies.
- Look-ahead-safe M5-snapshot to M1-entry protocol.
- Conservative M1 stop-versus-target resolution.
- Standard, elevated and severe execution-cost stress profiles.
- Nearby stop, target, holding-period and cooldown robustness challenges.
- Chronological validation and locked-test M1 reporting.
- Year, month, weekday, session and regime breakdowns.
- Immutable SHA-256 rule freezing for strategies that become Ready for MT5 Generation.
- New Validation Lab dashboard with worker monitor, automatic promotion path, best-ready strategy and detailed result explorer.
- Netlify proxy routes for validation status, results and diagnostic wake.

## Anti-overfitting controls

- The exact evolved rule set is replayed first.
- Nearby parameters are challenged; v2.3 does not optimise them against the locked period.
- A single M1 bar that can touch both stop and target is recorded as a stop.
- Entries are placed only after the source M5 candle has closed.
- Frozen rule versions are immutable and identified by SHA-256.

## Not included yet

- Automatic `.mq5` Expert Advisor generation.
- Broker tick-data testing.
- Demo forward testing.
- Live deployment.
