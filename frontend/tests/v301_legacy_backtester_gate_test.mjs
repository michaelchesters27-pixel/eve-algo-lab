import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const js = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");

test("legacy Fixed Ladder backtester remains an explicit optional tool", () => {
  assert.match(html, /id="openLegacyBacktester"/);
  assert.match(html, /id="backtester"[^>]*hidden[^>]*aria-hidden="true"/);
  assert.match(html, /id="closeLegacyBacktester"/);
  assert.match(html, /One built-in strategy — no file upload/);
  assert.match(html, /does not test arbitrary MQ5 files/);
});

test("legacy workspace opens clean and archive is opt-in", () => {
  assert.match(html, /Old tests stay out of the way/);
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
