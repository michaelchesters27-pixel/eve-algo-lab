# EVE Command Centre v3.0

EVE is a private XAU/USD research and MT5 bot-development platform using Supabase, Railway, Netlify and Twelve Data.

## What changed in v3.0

v3.0 does not change EVE's research or trading logic. It reorganises the platform around the decisions a person needs to make.

The new primary navigation is:

1. **Home** — one briefing, one recommended action and system health.
2. **Research** — what EVE is learning and the evidence behind it.
3. **Strategy Factory** — build rules, improve survivors and demand high-resolution proof.
4. **Bot Factory** — generated MT5 packages and compilation instructions.
5. **Demo Testing** — which bot can be tested now, later today or in a future period.
6. **Advanced** — market memory, the legacy backtester, build history and activity logs.

The Home page now combines existing Railway and Supabase status into a plain-English briefing. It does not invent confidence scores or claim an MT5 bot is attached; it only reports information EVE can verify from its own data.

## Existing autonomous pipeline

- Multi-timeframe market memory: M1, M5, M15, H1, H4 and D1.
- Autonomous learning and continuous historical research.
- Strategy generation and controlled evolution.
- M1 replay, execution-cost stress and immutable rule freezing.
- MT5 `.mq5` package generation.
- Demo eligibility guidance based on frozen rules, UK/UTC time and stored M5 context.

## Safety

All generated EAs default to `InpEnableTrading=false`. EVE cannot yet verify that an EA is physically attached to an MT5 terminal or receive completed demo-trade telemetry. Use a demo account only.
