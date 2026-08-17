import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const js = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");

test("Strategy Tester is a dedicated research workspace with the current volatility experiment and archived hypotheses", () => {
  assert.match(html, /id="openLegacyBacktester"/);
  assert.match(html, /id="backtester"[^>]*hidden[^>]*aria-hidden="true"/);
  assert.match(html, /id="closeLegacyBacktester"/);
  assert.match(html, /data-workspace="tester"/);
  assert.match(html, /The current experiment is <strong>Gold High-Volatility Close Momentum v1<\/strong>/);
  assert.match(html, /Gold High-Volatility Close Momentum v1 · trade only the published high-volatility subset/);
  assert.match(html, /Gold High-Volatility Close Momentum v1 — current research test/);
  assert.match(html, /Gold ETF-Hours Intraday Short v1 — failed development/);
  assert.match(html, /Gold ETF-Hours Overnight Long v1 — failed development/);
  assert.match(html, /Gold Rest-of-Day Close Momentum v1 — failed PF gate/);
  assert.match(html, /Gold Intraday Close Momentum v1 — failed development/);
  assert.match(html, /Gold Abnormal Momentum v1 — profitable but too infrequent/);
  assert.match(html, /Asia Session Long v1 — failed development/);
  assert.match(html, /Shanghai Day Long v1 — failed development/);
  assert.match(html, /Gold Overnight Long v1 — failed development/);
  assert.match(html, /COMEX Day Short v1 — failed development/);
  assert.match(html, /COMEX Closing Momentum v1 — failed development/);
  assert.match(html, /New York Morning Momentum v1 — failed development/);
  assert.match(html, /Gold H1 Trend 55\/20 v1 — failed development/);
  assert.match(html, /Gold H4 Trend 55\/20 v1 — inconclusive \(62 trades\)/);
  assert.match(html, /London Opening Range v1 — failed development/);
  assert.match(html, /Liquidity Continuation v1 — failed development/);
  assert.match(html, /Liquidity Basket v1 — failed development/);
  assert.match(html, /Fixed Ladder v2\.61 — legacy diagnostic/);
  assert.match(html, /Why an uploaded MQ5 file still needs MT5/);
});

test("tester opens clean and its archive is opt-in", () => {
  assert.match(html, /Every run starts blank/);
  assert.match(html, /id="showLegacyHistory"/);
  assert.match(html, /id="legacyHistoryPanel"[^>]*hidden/);
  assert.match(html, /No previous result is loaded automatically/);
  assert.match(js, /function clearBacktestWorkspace/);
  assert.match(js, /function setLegacyHistoryOpen/);
  assert.match(js, /ARCHIVED TEST/);
});

test("completed history is not automatically rendered as current", () => {
  assert.match(js, /restoreActiveBacktest/);
  assert.match(js, /api\("backtests\/active\?limit=5"\)/);
  assert.doesNotMatch(js, /const latest = runs\[0\][\s\S]*renderBacktest\(latest\)/);
  assert.match(js, /if \(legacyBacktesterOpen && \(activeBacktestId \|\| legacyBacktestHistoryOpen\)\) await refreshBacktests\(true\)/);
});

test("Gold session, COMEX and New York daily momentum, Gold trend, London and archived liquidity controls plus blunt verdict are present", () => {
  for (const id of [
    "testerStrategy", "testPeriod", "positionsPerBasket", "liquidityLookback", "basketStop", "slippagePrice", "moneyPerPrice",
    "maximumHold", "cooldownCandles", "minimumMoveLabel", "londonRiskPercent", "londonBreakoutBuffer", "londonRewardRisk",
    "londonMinimumLot", "londonLotStep", "londonMaximumLot", "trendRiskPercent", "trendMinimumLot", "trendLotStep",
    "trendMaximumLot", "trendLongOvernight", "trendShortOvernight", "goldSessionFixedLot", "goldSessionMaximumLoss",
    "goldSessionOvernightCost", "backtestVerdict", "resultWorstBasket", "resultLosingStreak",
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(js, /backtests\/gold-h1-trend/);
  assert.match(js, /backtests\/gold-h4-trend/);
  assert.match(js, /backtests\/gold-session-anomaly/);
  assert.match(js, /backtests\/comex-closing-momentum/);
  assert.match(js, /backtests\/new-york-morning-momentum/);
  assert.match(js, /backtests\/london-opening-range/);
  assert.match(js, /backtests\/liquidity-basket/);
  assert.match(js, /breakout_continuation/);
  assert.match(js, /MIDPOINT STOP/);
  assert.match(js, /MAX 1 TRADE\/DAY/);
  assert.match(js, /2-SIGMA TRIGGER/);
  assert.match(js, /60 PRIOR WINDOWS/);
  assert.match(js, /ABOVE-MEDIAN VOLATILITY/);
  assert.match(js, /11:30-12:00 DIRECTION/);
  assert.match(js, /PRIOR 16:00 REFERENCE/);
  assert.match(js, /15:30 FOLLOW DIRECTION/);
  assert.match(js, /15:30 ENTRY/);
  assert.match(js, /ONE TRADE EVERY COMPLETE WEEKDAY/);
  assert.match(js, /SELL 09:30 NEW YORK/);
  assert.match(js, /BUY 16:00 NEW YORK/);
  assert.match(js, /NEXT 09:30 EXIT/);
  assert.match(js, /17:00 SHORT \/ 19:00 BUY/);
  assert.match(js, /BUY 13:30 NEW YORK/);
  assert.match(js, /SELL 08:20 NEW YORK/);
  assert.match(js, /BUY 18:00 NEW YORK/);
  assert.match(js, /15:30 SHANGHAI EXIT/);
  assert.match(js, /BUY 09:00 SHANGHAI/);
  assert.match(js, /PRIOR 13:29 REFERENCE/);
  assert.match(js, /55-\$\{trendFrame\} BREAKOUT/);
  assert.match(js, /renderBacktestVerdict/);
  assert.match(js, /renderBacktestEquity/);
});
