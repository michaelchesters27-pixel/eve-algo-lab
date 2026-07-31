import assert from "node:assert/strict";
import proxy from "../netlify/functions/api.mjs";

const calls = [];
globalThis.Netlify = { env: { get(name) { return name === "RAILWAY_API_URL" ? "https://railway.example" : name === "EVE_ADMIN_TOKEN" ? "test-token" : ""; } } };
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  return new Response(JSON.stringify({ ok: true, data: { items: [] } }), { status: 200, headers: { "Content-Type": "application/json" } });
};

const response = await proxy(new Request("https://eve.example/api/research/results?symbol=XAU%2FUSD&result_status=all&order=confidence&limit=150"));
assert.equal(response.status, 200);
assert.equal(calls.length, 1);
assert.equal(calls[0].url, "https://railway.example/api/research/results?symbol=XAU%2FUSD&result_status=all&order=confidence&limit=150");
console.log("Netlify proxy research/results route: PASS");
