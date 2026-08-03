# EVE Algo Lab v2.2

EVE Algo Lab is a private XAU/USD research platform running on Supabase, Railway, Netlify and Twelve Data.

It stores M1, M5, M15, H1, H4 and D1 history, maintains autonomous learning, researches past market states continuously, converts discoveries into strategy candidates and now evolves the strongest candidates through controlled parent-versus-child experiments.

## v2.2 Strategy Evolution Engine

The autonomous Evolution Lab:

1. Seeds up to 20 active lineages from the strongest Elite, Validated and Promising Strategy Lab candidates.
2. Mutates one rule at a time: ATR stop, ATR target, cooldown, direction or filter mode.
3. Combines compatible conditions from two strong lineages without creating contradictory filters.
4. Compares every child with its direct parent on the same chronological training and validation rows.
5. Selects the next development champion using validation evidence only.
6. Keeps the locked period sealed from parameter selection; it supplies a readiness grade and catastrophic-loss veto.
7. Records every generation, mutation, rejection, development champion, champion and elite result.
8. Continues on Railway while the browser and computer are off.

## Status meanings

- **Rejected** — did not improve its parent on validation, or triggered the locked-period safety veto.
- **Development** — improved validation and may seed the next generation, but locked evidence is not ready.
- **Champion** — improved validation and remained positive and stable on locked data.
- **Elite** — a champion with stronger locked-test thresholds.

## Important

This remains research-grade M5 outcome replay. No Evolution result is ready for real-money deployment until it passes M1/tick replay, realistic broker-cost stress and forward testing.

See `DEPLOYMENT_GUIDE.md`.
