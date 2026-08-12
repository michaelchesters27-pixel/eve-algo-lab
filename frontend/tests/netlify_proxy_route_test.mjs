import assert from "node:assert/strict";
import proxy from "../netlify/functions/api.mjs";

const calls = [];
globalThis.Netlify = { env: { get(name) { return name === "RAILWAY_API_URL" ? "https://railway.example" : name === "EVE_ADMIN_TOKEN" ? "test-token" : ""; } } };
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  return new Response(JSON.stringify({ ok: true, data: { items: [] } }), { status: 200, headers: { "Content-Type": "application/json" } });
};

let response = await proxy(new Request("https://eve.example/api/research/results?symbol=XAU%2FUSD&result_status=all&order=confidence&limit=150"));
assert.equal(response.status, 200);
assert.equal(calls[0].url, "https://railway.example/api/research/results?symbol=XAU%2FUSD&result_status=all&order=confidence&limit=150");

response = await proxy(new Request("https://eve.example/api/strategy-lab/candidates?symbol=XAU%2FUSD&result_status=all&order=profit_factor&limit=150"));
assert.equal(response.status, 200);
assert.equal(calls[1].url, "https://railway.example/api/strategy-lab/candidates?symbol=XAU%2FUSD&result_status=all&order=profit_factor&limit=150");

response = await proxy(new Request("https://eve.example/api/strategy-lab/wake", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } }));
assert.equal(response.status, 200);
assert.equal(calls[2].url, "https://railway.example/api/strategy-lab/wake");
assert.equal(calls[2].options.headers["X-EVE-ADMIN-TOKEN"], "test-token");
console.log("Netlify proxy research and Strategy Lab routes: PASS");

response = await proxy(new Request("https://eve.example/api/evolution/status?symbol=XAU%2FUSD"));
assert.equal(response.status, 200);
assert.equal(calls[3].url, "https://railway.example/api/evolution/status?symbol=XAU%2FUSD");

response = await proxy(new Request("https://eve.example/api/evolution/candidates?symbol=XAU%2FUSD&result_status=all&order=validation_improvement&limit=150"));
assert.equal(response.status, 200);
assert.equal(calls[4].url, "https://railway.example/api/evolution/candidates?symbol=XAU%2FUSD&result_status=all&order=validation_improvement&limit=150");

response = await proxy(new Request("https://eve.example/api/evolution/wake", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } }));
assert.equal(response.status, 200);
assert.equal(calls[5].url, "https://railway.example/api/evolution/wake");
assert.equal(calls[5].options.headers["X-EVE-ADMIN-TOKEN"], "test-token");
console.log("Netlify proxy Evolution routes: PASS");

response = await proxy(new Request("https://eve.example/api/validation/status?symbol=XAU%2FUSD"));
assert.equal(response.status, 200);
assert.equal(calls[6].url, "https://railway.example/api/validation/status?symbol=XAU%2FUSD");

response = await proxy(new Request("https://eve.example/api/validation/jobs?symbol=XAU%2FUSD&result_status=all&order=profit_factor&limit=150"));
assert.equal(response.status, 200);
assert.equal(calls[7].url, "https://railway.example/api/validation/jobs?symbol=XAU%2FUSD&result_status=all&order=profit_factor&limit=150");

response = await proxy(new Request("https://eve.example/api/validation/wake", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } }));
assert.equal(response.status, 200);
assert.equal(calls[8].url, "https://railway.example/api/validation/wake");
assert.equal(calls[8].options.headers["X-EVE-ADMIN-TOKEN"], "test-token");
console.log("Netlify proxy Validation Lab routes: PASS");

response = await proxy(new Request("https://eve.example/api/mt5/status?symbol=XAU%2FUSD"));
assert.equal(response.status, 200);
assert.equal(calls[9].url, "https://railway.example/api/mt5/status?symbol=XAU%2FUSD");

response = await proxy(new Request("https://eve.example/api/mt5/packages?symbol=XAU%2FUSD&limit=100"));
assert.equal(response.status, 200);
assert.equal(calls[10].url, "https://railway.example/api/mt5/packages?symbol=XAU%2FUSD&limit=100");

response = await proxy(new Request("https://eve.example/api/mt5/packages/123e4567-e89b-12d3-a456-426614174000/download"));
assert.equal(response.status, 200);
assert.equal(calls[11].url, "https://railway.example/api/mt5/packages/123e4567-e89b-12d3-a456-426614174000/download");

response = await proxy(new Request("https://eve.example/api/mt5/packages/123e4567-e89b-12d3-a456-426614174000/source"));
assert.equal(response.status, 200);
assert.equal(calls[12].url, "https://railway.example/api/mt5/packages/123e4567-e89b-12d3-a456-426614174000/source");

response = await proxy(new Request("https://eve.example/api/mt5/wake", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } }));
assert.equal(response.status, 200);
assert.equal(calls[13].url, "https://railway.example/api/mt5/wake");
assert.equal(calls[13].options.headers["X-EVE-ADMIN-TOKEN"], "test-token");
console.log("Netlify proxy MT5 Generator routes: PASS");

response = await proxy(new Request("https://eve.example/api/mt5/eligibility?symbol=XAU%2FUSD&limit=100"));
assert.equal(response.status, 200);
assert.equal(calls[14].url, "https://railway.example/api/mt5/eligibility?symbol=XAU%2FUSD&limit=100");
console.log("Netlify proxy Demo Eligibility route: PASS");

response = await proxy(new Request("https://eve.example/api/backtests/active?limit=5"));
assert.equal(response.status, 200);
assert.equal(calls.at(-1).url, "https://railway.example/api/backtests/active?limit=5");
console.log("Netlify proxy active-backtest route: PASS");

response = await proxy(new Request("https://eve.example/api/backtests/liquidity-basket", {
  method: "POST",
  body: JSON.stringify({ symbol: "XAU/USD", test_segment: "full" }),
  headers: { "Content-Type": "application/json" },
}));
assert.equal(response.status, 200);
assert.equal(calls.at(-1).url, "https://railway.example/api/backtests/liquidity-basket");
assert.equal(calls.at(-1).options.headers["X-EVE-ADMIN-TOKEN"], "test-token");
console.log("Netlify proxy Liquidity Basket route: PASS");

response = await proxy(new Request("https://eve.example/api/fleet?symbol=XAU%2FUSD&limit=200"));
assert.equal(response.status, 200);
assert.equal(calls.at(-1).url, "https://railway.example/api/fleet?symbol=XAU%2FUSD&limit=200");

response = await proxy(new Request("https://eve.example/api/fleet/heartbeat", {
  method: "POST",
  body: JSON.stringify({ package_id: "123e4567-e89b-12d3-a456-426614174000" }),
  headers: { "Content-Type": "application/json", "X-EVE-FLEET-TOKEN": "fleet-token" },
}));
assert.equal(response.status, 200);
assert.equal(calls.at(-1).url, "https://railway.example/api/fleet/heartbeat");
assert.equal(calls.at(-1).options.headers["X-EVE-FLEET-TOKEN"], "fleet-token");
assert.equal(calls.at(-1).options.headers["X-EVE-ADMIN-TOKEN"], undefined);
console.log("Netlify proxy Demo Fleet routes: PASS");
