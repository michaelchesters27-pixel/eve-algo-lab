# H1 30-Minute Range Theory v1

This is a research-only EVE experiment. It does not create trades, entries, stops, targets or an MT5 EA.

## Question

At the halfway point of a complete H1 candle, when the developing candle already has both an upper wick and a lower wick, how often have the final hourly high and low already been set?

The stronger follow-up question is whether the minute-30 candle state contains useful information about which first-half boundary breaks first during minutes 30–59.

## Exact test

- Source: stored `XAU/USD` M1 Market Memory.
- Reconstruct each H1 period from 60 consecutive M1 candles.
- Exclude incomplete hours instead of filling or guessing missing minutes.
- Freeze the first 30 M1 candles.
- Require a strictly positive upper wick and lower wick on the developing H1 candle at that point.
- Record first-half high, low, range, body direction, wick sizes and close position in the range.
- Reveal only minutes 30–59.
- Classify the outcome as `high_only`, `low_only`, `both`, or `neither`.
- Record which side breaks first.
- If one M1 bar breaches both boundaries, mark first-side order as `same_minute_ambiguous`; never infer intraminute path from OHLC.

## Anti-overfitting checks

The report automatically splits qualifying observations chronologically into the first two-thirds and untouched final third. Directional condition tables report both periods separately, and the candidate list requires minimum samples in both periods and consistent directional sign before labelling a clue stable.

This is still discovery research, not proof of a tradable edge. Any promising condition should be frozen and tested as a separate strategy with costs, execution rules and untouched data before an EA is considered.

## UI

After deployment, open `/h1-30m-research.html` on the EVE Netlify site. The page can start the full-history scan, display progress, and show the saved report from the existing `backtest_runs` table.

No Supabase migration or new environment variable is required.
