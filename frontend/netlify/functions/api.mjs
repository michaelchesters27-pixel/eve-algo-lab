const ALLOWED = [
  /^health$/,
  /^status$/,
  /^jobs\/[0-9a-f-]+$/i,
  /^jobs\/[0-9a-f-]+\/cancel$/i,
  /^jobs\/(backfill|sync|gap-scan)$/,
  /^learning\/status$/,
  /^learning\/runs$/,
  /^learning\/build$/,
  /^learning\/runs\/[0-9a-f-]+\/cancel$/i,
  /^autonomy\/run$/,
  /^research\/results$/,
  /^research\/wake$/,
  /^research\/h1-30m\/run$/,
  /^research\/h1-30m\/status$/,
  /^research\/h1-30m\/[0-9a-f-]+$/i,
  /^strategy-lab\/status$/,
  /^strategy-lab\/candidates$/,
  /^strategy-lab\/wake$/,
  /^evolution\/status$/,
  /^evolution\/candidates$/,
  /^evolution\/wake$/,
  /^validation\/status$/,
  /^validation\/jobs$/,
  /^validation\/wake$/,
  /^mt5\/status$/,
  /^mt5\/packages$/,
  /^mt5\/eligibility$/,
  /^mt5\/packages\/[0-9a-f-]+\/(download|source)$/i,
  /^mt5\/wake$/,
  /^fleet$/,
  /^fleet\/heartbeat$/,
  /^backtests$/,
  /^backtests\/active$/,
  /^backtests\/[0-9a-f-]+$/i,
  /^backtests\/[0-9a-f-]+\/cancel$/i,
  /^backtests\/gold-h4-trend$/,
  /^backtests\/gold-h1-trend$/,
  /^backtests\/gold-session-anomaly$/,
  /^backtests\/comex-closing-momentum$/,
  /^backtests\/new-york-morning-momentum$/,
  /^backtests\/london-opening-range$/,
  /^backtests\/liquidity-basket$/,
  /^backtests\/fixed-ladder-v2-61$/,
  /^backtests\/metrics-preview$/,
];

export default async (request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type, X-EVE-FLEET-TOKEN",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      },
    });
  }

  const railwayUrl = (Netlify.env.get("RAILWAY_API_URL") || "").replace(/\/$/, "");
  const adminToken = Netlify.env.get("EVE_ADMIN_TOKEN") || "";

  if (!railwayUrl) {
    return Response.json(
      { ok: false, message: "Netlify variable RAILWAY_API_URL has not been added yet." },
      { status: 503 },
    );
  }

  const url = new URL(request.url);
  const isFleetHeartbeat = request.method === "POST" && /\/fleet\/heartbeat$/.test(url.pathname);
  if (request.method !== "GET" && !isFleetHeartbeat && !adminToken) {
    return Response.json(
      { ok: false, message: "Netlify variable EVE_ADMIN_TOKEN is missing. Set it to the same value as Railway ADMIN_TOKEN." },
      { status: 503 },
    );
  }

  let path = url.pathname
    .replace(/^\/\.netlify\/functions\/api\/?/, "")
    .replace(/^\/api\/?/, "")
    .replace(/^\/+/, "");

  if (!path) path = "status";
  if (!ALLOWED.some((pattern) => pattern.test(path))) {
    return Response.json({ ok: false, message: "Route not allowed by the Netlify proxy." }, { status: 404 });
  }

  const target = new URL(`${railwayUrl}/api/${path}`);
  if (path === "health") target.pathname = "/health";
  url.searchParams.forEach((value, key) => target.searchParams.set(key, value));

  const headers = { Accept: "application/json" };
  if (request.method !== "GET") {
    headers["Content-Type"] = "application/json";
    if (isFleetHeartbeat) {
      headers["X-EVE-FLEET-TOKEN"] = request.headers.get("X-EVE-FLEET-TOKEN") || "";
    } else {
      headers["X-EVE-ADMIN-TOKEN"] = adminToken;
    }
  }

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
    });
    const body = await response.arrayBuffer();
    return new Response(body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json",
        "Content-Disposition": response.headers.get("content-disposition") || "inline",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    return Response.json(
      { ok: false, message: `Railway connection failed: ${error.message}` },
      { status: 502 },
    );
  }
};
