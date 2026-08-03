# EVE Algo Lab v2.2 — Strategy Evolution Engine

## Added

- Dedicated autonomous Strategy Evolution worker on Railway.
- Strategy lineages seeded from the strongest Strategy Lab survivors.
- Controlled stop, target, cooldown, direction and filter-mode mutations.
- Compatible multi-discovery condition combinations.
- Direct parent-versus-child evaluation on identical chronological data.
- Validation-only development-champion selection.
- Sealed locked-test readiness audit and catastrophic-loss safety veto.
- Persistent generation history, lineage champions and mutation evidence.
- New Evolution Lab dashboard with worker monitor, current champion, lineage leaderboard and detailed mutation explorer.
- Netlify proxy routes for Evolution status, results and manual diagnostic wake.

## Anti-overfitting rule

Locked-test results are not used to choose parameter values. Evolution uses training and validation data for selection. The locked period grades readiness and can block a catastrophic child, but it does not steer the mutation search.

## Not included yet

- M1/tick replay promotion pipeline.
- Automatic MT5 EA generation.
- Demo forward testing.
- Live deployment.
