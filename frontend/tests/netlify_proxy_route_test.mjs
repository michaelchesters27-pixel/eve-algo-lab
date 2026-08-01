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
