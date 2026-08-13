# EVE Command Centre v3.9

EVE is a private XAU/USD research, strategy-evolution and MT5 bot-development platform using Supabase, Railway, Netlify and Twelve Data.

## What v3.9 changes

- Adds two eastern-session hypotheses frozen before either result: **Asia Session Long v1** first and **Shanghai Day Long v1** as its predeclared backup.
- Buys one fixed 0.01-lot XAU/USD position at the exact 18:00 `America/New_York` M1 open from Sunday through Thursday and exits at the associated 15:30 `Asia/Shanghai` M1 open.
- Targets the published positive eastern-hours gold effect while avoiding the 17:00 New York rollover charge.
- Shanghai Day Long uses the official 09:00–15:30 Shanghai Gold Exchange day session if the broader eastern window fails.
- Uses New York daylight saving for entry and fixed China Standard Time for exit, skips missing entry minutes, includes spread/commission/slippage and caps total loss at 0.25% of current balance.
- Preserves the strict development gate and only unlocks the untouched final third after an exact-settings development pass.
- Archives Gold Overnight Long v1 and COMEX Day Short v1 as failed evidence rather than tuning either on the observed result.

No Supabase SQL or new Railway/Netlify variables are required for v3.9.

## What v3.8 changes

- Adds two independently identified, pre-declared gold session hypotheses before either result is seen: **Gold Overnight Long v1** and **COMEX Day Short v1**.
- Gold Overnight Long buys one fixed 0.01-lot position at the exact 13:30 New York M1 open and exits at the next eligible weekday's exact 08:20 open.
- COMEX Day Short sells one fixed 0.01-lot position at 08:20 New York and exits at 13:30 the same day.
- Both strategies allow at most one entry per weekday, never enter late, never average, never use martingale and cap total trade loss at 0.25% of current balance.
- The overnight replay includes a frozen $0.70 financing cost per 0.01 lot at 17:00 New York and a Wednesday triple charge; both replays include spread, commission, optional slippage, daylight saving and gap stops.
- Uses the same pre-declared proof gate: at least 500 trades, positive net profit and expectancy, PF 1.20, no more than 15% drawdown, and at least three profitable years.
- Keeps the untouched final third sealed unless the exact matching development run passes the gate. A merely completed or failed development run cannot unlock it.
- Archives COMEX Closing Momentum v1 as failed development evidence and makes Gold Overnight Long v1 the next current experiment.

No Supabase SQL or new Railway/Netlify variables are required for v3.8.

## What v3.7 changes

- Adds **COMEX Closing Momentum v1**, a pre-declared XAU/USD hypothesis with at most one fixed 0.01-lot trade per New York weekday.
- Uses the prior valid 13:29 New York M1 close as the spot-price proxy for the 13:30 COMEX gold settlement.
- Buys at the 13:00 New York M1 open when price is above that reference and sells when below; an equal price or missing reference skips the day.
- Force-closes at the 13:30 New York M1 open and caps any earlier loss at 0.25% of current balance.
- Includes spread, commission, optional slippage, daylight-saving conversion, gap-stop fills and a hard zero-balance limit.
- Freezes the development gate before results: at least 500 trades, positive net profit and expectancy, PF 1.20, no more than 15% drawdown, and at least three profitable calendar years.
- Keeps the untouched final third sealed unless the completed development run is reused with every rule, risk and cost input unchanged.
- Archives New York Morning Momentum v1 as a failed development hypothesis rather than tuning it after seeing the result.

No Supabase SQL or new Railway/Netlify variables are required for v3.7.

## What v3.6 changes

- Adds **New York Morning Momentum v1**, a deliberately simple XAU/USD intraday hypothesis with at most one trade per New York weekday.
- Uses every verified M1 candle from 08:30–09:00 `America/New_York`, follows that window's direction at the 09:00 open, and skips the day if any signal minute is missing or the window is a doji.
- Risks 0.25% of current balance, rounds size down to the broker lot step, places a hard stop at the opposite edge of the morning range, and force-closes at 15:55 New York.
- Includes spread, commission, optional slippage, daylight-saving-time conversion, gap-stop fills, and a hard zero-balance limit.
- Freezes the development gate before results: at least 500 trades, positive net profit and expectancy, PF 1.20, no more than 15% drawdown, and at least three profitable calendar years.
- Keeps the untouched final third sealed unless the completed development run is reused with every rule, risk and cost input unchanged.

No Supabase SQL or new Railway/Netlify variables are required for v3.6.

## What v3.5 changes

- Adds **Gold H1 Trend 55/20 v1**, the pre-declared higher-frequency follow-up after the H4 development test produced only 62 trades.
- Preserves the same daily-direction filter, one-position risk model, 55-bar breakout, 2 × ATR(20) stop and opposite 20-bar channel exit on completed H1 candles.
- Uses stored H1 and D1 candles for decisions and verified M1 candles for entry, stop, gap and cost replay.
- Keeps the H4 result archived as inconclusive and leaves its untouched final third sealed.
- Applies the same strict gate: at least 100 trades, PF 1.25, positive expectancy and no more than 15% drawdown.

No Supabase SQL or new Railway/Netlify variables are required for v3.5.

## What v3.4 changes

- Adds **Gold H4 Trend 55/20 v1**, the first multi-day price-trend hypothesis in the Strategy Tester.
- Uses stored completed H4 and D1 candles for decisions, then verified M1 candles for entry, stop, gap and cost replay.
- Trades a 55-H4 breakout only when the latest completed daily close agrees with its direction versus 60 trading days earlier.
- Risks 0.25% of current balance on one position, uses a 2 × H4 ATR(20) hard stop, has no fixed target and exits on the opposite 20-H4 channel.
- Includes spread, commission, slippage, conservative long/short overnight financing, Wednesday triple financing and weekend gap fills.
- Requires at least 100 trades, PF 1.25, positive expectancy and no more than 15% drawdown before the untouched final third can be considered a pass.
- Freezes every signal, risk and cost input between development and untouched tests.

No Supabase SQL or new Railway/Netlify variables are required for v3.4.

## What v3.3 changes

- Adds **London Opening Range v1**, a separate XAU/USD hypothesis after both four-position liquidity experiments failed development testing.
- Builds the 08:00–08:30 Europe/London range from six complete M5 candles reconstructed from verified M1 history, including daylight-saving-time changes.
- Requires the first directional M5 close at least 10% of the range width beyond the boundary and enters only at the next M5 open.
- Trades one position per London day, risks 0.25% of current balance, stops at the range midpoint, targets 2R and force-closes at 16:00 London.
- Rounds position size down to the broker lot step and skips a signal when the minimum lot would breach the risk cap.
- Includes spread, commission and optional slippage, stores every completed trade, and applies the same locked development-to-untouched proof gate used by EVE's Strategy Tester.
- Uses a $10,000 research balance by default so 0.25% sizing can be represented with a 0.01 minimum XAU/USD lot. This is a simulator balance, not a recommendation to fund an account.

No Supabase SQL or new Railway/Netlify variables are required for v3.3.

## What v3.2.1 changes

- Adds **Liquidity Continuation v1**, a genuinely different entry hypothesis that follows a confirmed close beyond prior M1 liquidity instead of fading the sweep.
- Keeps the same four 0.02-lot positions, combined $4 target and $8 basket loss limit so the entry rule is compared fairly.
- Stops a liquidity replay permanently when account equity reaches zero; ending balance and drawdown can no longer become impossible negative values above 100% loss.
- Stores continuation runs under their own strategy identity, so they cannot be mixed with the rejected Liquidity Basket v1 development evidence.
- Makes Liquidity Continuation v1 the default Strategy Tester selection while retaining the failed sweep-reversal run in the archive.

No Supabase SQL or new Railway/Netlify variables are required for v3.2.1.

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
