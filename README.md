# EVE Command Centre v3.2

EVE is a private XAU/USD research, strategy-evolution and MT5 bot-development platform using Supabase, Railway, Netlify and Twelve Data.

## What v3.2 changes

v3.2 adds a dedicated **Strategy Tester** without changing live MT5 fleet execution.

- The first new experiment is **Liquidity Basket v1** on stored XAU/USD M1 candles.
- A signal requires a sweep of the previous liquidity high/low and a confirmed close back inside; entry occurs only at the next candle open.
- The tester opens four equal positions by default and manages them as one combined-money basket.
- Spread, commission, optional slippage, a hard basket loss, maximum hold and post-basket cooldown are modelled.
- Full-history, development first-two-thirds, untouched final-third and custom-period tests are supported.
- An untouched run is rejected unless a completed development run exists with every entry, risk and cost setting unchanged.
- Slippage and the broker's XAU/USD contract value can be calibrated instead of being hidden assumptions.
- Every completed test receives a plain-English verdict based on profit, profit factor, expectancy, evidence count and drawdown.
- Results include worst basket, longest losing run, frequency, balance path and a basket-by-basket archive.
- The source-verified Fixed Ladder v2.61 replay remains available as a legacy diagnostic inside the same page.

No Supabase SQL or new Railway/Netlify variables are required for v3.2.

## What v3.1 changed

v3.1 reorganises the product without changing the research engine beneath it.

- Six clear workspaces: **Home, Research, Strategy Factory, Bot Library, Demo Fleet and Advanced**.
- Strategy creation, mutation and high-resolution validation remain separate backend stages, but are presented as **Build → Improve → Prove**.
- Generated EAs are grouped by how they are intended to be used: everyday, weekday, short-window, monthly and seasonal bots.
- Every Bot Library card explains the exact frozen schedule, current practical eligibility, London-time guidance, chart and attachment action.
- **Demo Fleet** shows which fleet-ready EAs are genuinely attached to MT5 and still reporting.
- Bot Library marks a package **RUNNING IN MT5** when the matching live heartbeat is present, helping prevent accidental duplicate attachments.
- Duplicate EAs, disabled internal trading, disabled Algo Trading, stale heartbeats and real-account attachments are flagged.
- The Fixed Ladder replay remains an optional legacy tool under **Advanced** and does not influence current Strategy Factory or bot rankings.

## What remains unchanged

The autonomous engine keeps running as before:

- historical-data sync and gap checks;
- research questions, discovery and evidence building;
- autonomous Strategy Factory candidate creation;
- lineage mutation and parent-versus-child evolution;
- M1 validation, cost stress and robustness testing;
- frozen strategy and MT5 package generation.

A frozen EA already on demo is never silently mutated. A stronger mutation becomes a separate challenger/version and must pass the full pipeline before it can be downloaded.

## One-time v3.1 setup

Run `SUPABASE_UPDATE_v3.1.sql` once in Supabase SQL Editor. It adds only `mt5_fleet_instances`, the heartbeat table used by Demo Fleet. Existing candles, research, strategies, mutations, validation results and packages are untouched.

No new Railway or Netlify variables are required.

## Connecting an EA to Demo Fleet

Older EAs already attached to MT5 do not contain telemetry and cannot appear automatically.

1. Wait until the bot has no open trade.
2. Download the same package or `.mq5` again from **Bot Library** after v3.1 is deployed.
3. Compile the new fleet-ready source in MetaEditor.
4. In MT5 open **Tools → Options → Expert Advisors**.
5. Enable **Allow WebRequest for listed URL** and add `https://evealgolab.netlify.app`.
6. Remove the old EA from its chart, attach the new compiled EA, and restore the same demo inputs.
7. Set `InpEnableTrading=true` only on the demo account and keep Algo Trading enabled.

Telemetry is best-effort. A failed heartbeat cannot open, alter or close a position, and the EA's frozen rule hash remains unchanged.

## Important limitations

- Demo Fleet can only see fleet-ready downloads that send heartbeats.
- EVE does not automatically compile `.mq5` files; MetaEditor is still required.
- The Legacy Fixed Ladder Backtester is a Python reconstruction of one specific EA, not a general MQ5 tester.
- All generated EAs are for demo testing first. v3.1 does not promote a bot to real-money trading.
