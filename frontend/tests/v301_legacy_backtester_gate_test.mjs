import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const js = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");

test("Strategy Tester is a dedicated research workspace with both built-in strategies", () => {
  assert.match(html, /id="openLegacyBacktester"/);
  assert.match(html, /id="backtester"[^>]*hidden[^>]*aria-hidden="true"/);
  assert.match(html, /id="closeLegacyBacktester"/);
  assert.match(html, /data-workspace="tester"/);
  assert.match(html, /Liquidity Basket v1 — four positions/);
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

test("liquidity basket controls and blunt result verdict are present", () => {
  for (const id of [
    "testerStrategy", "testPeriod", "positionsPerBasket", "liquidityLookback", "basketStop", "slippagePrice", "moneyPerPrice",
    "maximumHold", "cooldownCandles", "backtestVerdict", "resultWorstBasket", "resultLosingStreak",
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(js, /backtests\/liquidity-basket/);
  assert.match(js, /renderBacktestVerdict/);
  assert.match(js, /renderBacktestEquity/);
});
