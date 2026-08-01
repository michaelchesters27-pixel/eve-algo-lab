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
  /^strategy-lab\/status$/,
  /^strategy-lab\/candidates$/,
  /^strategy-lab\/wake$/,
  /^backtests$/,
  /^backtests\/[0-9a-f-]+$/i,
  /^backtests\/[0-9a-f-]+\/cancel$/i,
  /^backtests\/fixed-ladder-v2-61$/,
  /^backtests\/metrics-preview$/,
];

export default async (request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
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

  if (request.method !== "GET" && !adminToken) {
    return Response.json(
      { ok: false, message: "Netlify variable EVE_ADMIN_TOKEN is missing. Set it to the same value as Railway ADMIN_TOKEN." },
      { status: 503 },
    );
  }

  const url = new URL(request.url);
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
    headers["X-EVE-ADMIN-TOKEN"] = adminToken;
  }

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json",
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
