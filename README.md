# EVE Algo Lab v2.0.0

EVE Algo Lab is a private XAU/USD market-research platform running on Supabase, Railway, Netlify and Twelve Data.

It permanently stores six timeframes, builds multi-timeframe learning snapshots, labels future outcomes, researches historical relationships continuously and now converts strong findings into automatically tested strategy candidates.

## v2.0 Strategy Idea Factory

The autonomous Strategy Lab:

1. Reads validated and promising historical findings.
2. Converts them into explicit bot rules.
3. Generates risk variants with ATR stops and targets.
4. Prevents overlapping research trades.
5. Tests training, validation and locked unseen periods chronologically.
6. Compares each candidate against an equivalent unfiltered baseline.
7. Rejects weak rules and retains promising, validated and elite candidates.

Candidate results include profit factor, expectancy in R, maximum drawdown, trade count, win rate, year stability and baseline improvement.

## Important

A strong Strategy Lab result is not approval for live trading. v2.0 uses conservative candle/outcome replay. M1 or tick replay, realistic broker costs and forward testing remain mandatory before MT5 implementation.

See `DEPLOYMENT_GUIDE.md`.
