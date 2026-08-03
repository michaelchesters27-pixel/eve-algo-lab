import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const js = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");

function idsFrom(markup) {
  return [...markup.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
}

test("v3.1 command centre has one clear six-item navigation", () => {
  const nav = html.match(/<nav class="nav"[\s\S]*?<\/nav>/)?.[0] || "";
  const links = [...nav.matchAll(/class="nav-link[^"]*"/g)];
  assert.equal(links.length, 6);
  for (const target of ["#home", "#research", "#strategy-factory", "#bot-library", "#demo-fleet", "#advanced"]) {
    assert.match(nav, new RegExp(`href="${target.replace("#", "\\#")}"`));
  }
});

test("home briefing includes live fleet status without duplicate ids", () => {
  for (const id of [
    "briefingGreeting", "briefingStatus", "briefingHeadline", "briefingCopy",
    "homeActionStatus", "homeActionTitle", "homeActionCopy", "homeActionDownload",
    "homeResearchCount", "homeStrategyCount", "homeValidatedCount", "homeBotCount", "homeFleetCount",
  ]) assert.match(html, new RegExp(`id="${id}"`));
  const ids = idsFrom(html);
  assert.equal(new Set(ids).size, ids.length);
});

test("command centre is derived from existing verified dashboards and fleet heartbeats", () => {
  assert.match(js, /function updateCommandCentre\(\)/);
  assert.match(js, /learningDashboard\?\.state/);
  assert.match(js, /strategyLabDashboard\?\.state/);
  assert.match(js, /validationDashboard\?\.state/);
  assert.match(js, /mt5Dashboard\?\.state/);
  assert.match(js, /demoEligibilityDashboard/);
  assert.match(js, /fleetDashboard\?\.counts/);
});
