import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const js = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../styles.css", import.meta.url), "utf8");

test("only the selected workspace and selected factory stage are shown", () => {
  for (const workspace of ["home", "research", "strategy", "bot-library", "demo-fleet", "advanced"]) {
    assert.match(html, new RegExp(`data-workspace="${workspace}"`));
  }
  assert.match(js, /function showWorkspace\(/);
  assert.match(js, /section\.hidden = !visible/);
  assert.match(html, /data-factory-stage="build"/);
  assert.match(html, /data-factory-stage="improve"/);
  assert.match(html, /data-factory-stage="prove"/);
  assert.match(css, /\.workspace-section\[hidden\]/);
});

test("Bot Library is grouped by everyday, weekday, short-window and seasonal use", () => {
  for (const category of ["everyday", "weekday_monday", "weekday_tuesday", "weekday_wednesday", "weekday_thursday", "weekday_friday", "short_window", "seasonal"]) {
    assert.match(html, new RegExp(`data-bot-category="${category}"`));
  }
  assert.match(js, /item\.usage_tags/);
  assert.match(js, /WHEN THIS BOT IS FOR/);
  assert.match(js, /Can it stay attached\?/);
});

test("Demo Fleet shows actual heartbeat state and duplicate warnings", () => {
  for (const id of ["fleetOnlineCount", "fleetTradeCount", "fleetAttentionCount", "fleetDuplicateCount", "fleetList"]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(js, /api\("fleet\?symbol=XAU%2FUSD&limit=200"\)/);
  assert.match(js, /Duplicate attachment detected/);
  assert.match(js, /REAL ACCOUNT DETECTED/);
});

test("Bot Library marks packages already attached to MT5", () => {
  assert.match(js, /function fleetPresenceForPackage/);
  assert.match(js, /RUNNING IN MT5/);
  assert.match(js, /Do not attach another copy/);
  assert.match(js, /Open Demo Fleet/);
});

test("Home changes its recommended action when that bot is already attached", () => {
  assert.match(js, /recommendedAttached/);
  assert.match(js, /Open Demo Fleet to see its state/);
  assert.match(js, /download\.textContent = "Open Demo Fleet"/);
});
