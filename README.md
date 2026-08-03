# EVE Algo Lab v2.5

EVE Algo Lab is a private XAU/USD research platform using Supabase, Railway, Netlify and Twelve Data.

## v2.5 Demo Eligibility Lab

v2.5 reads every generated EA's immutable frozen rules and labels the practical demo-testing action:

- **TEST NOW** — the current tested calendar window and latest stored M5 context are eligible.
- **ATTACH AND LEAVE** — attach to an XAUUSD M5 demo chart; the EA is waiting for its market condition.
- **WAIT FOR TIME** — the required UTC hour or session is not active yet.
- **WAIT FOR PERIOD** — the required weekday, week, month or quarter is not active.
- **MARKET CLOSED** — wait for the estimated gold-market reopen.

The Demo Lab ranks bots by practical availability first, then locked-test profit factor and expectancy. A higher-profit seasonal EA no longer outranks a sound EA that can actually be tested now.

## Existing autonomous pipeline

1. Multi-timeframe market memory: M1, M5, M15, H1, H4 and D1.
2. Autonomous learning and historical research.
3. Strategy generation and evolution.
4. M1 replay, cost stress and immutable rule freezing.
5. MT5 `.mq5` package generation.
6. Demo eligibility guidance.

## Safety

All generated EAs default to `InpEnableTrading=false`. Demo Lab cannot see whether an EA is physically attached in MT5 or whether its Inputs were changed. Use a demo account only.
