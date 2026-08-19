const FILES = {
  "4ccb-calibrator": {
    path: "mt5/EVE_4CCB_IC_Broker_Calibrator.mq5",
    filename: "EVE_4CCB_IC_Broker_Calibrator.mq5",
    contentType: "text/plain; charset=utf-8",
  },
  "4ccb-operator-setup": {
    path: "docs/4ccb-operator-setup.md",
    filename: "4ccb-operator-setup.md",
    contentType: "text/markdown; charset=utf-8",
  },
  "4ccb-director-audit": {
    path: "docs/4ccb-director-v0.6-ic-markets-proxy-2026-08-19.md",
    filename: "4ccb-director-v0.6-ic-markets-proxy-2026-08-19.md",
    contentType: "text/markdown; charset=utf-8",
  },
};

export default async (request) => {
  const url = new URL(request.url);
  const key = (url.searchParams.get("file") || "").trim();
  const item = FILES[key];

  if (!item) {
    return Response.json(
      { ok: false, message: "Unknown EVE download." },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    );
  }

  const source = `https://raw.githubusercontent.com/michaelchesters27-pixel/eve-algo-lab/main/${item.path}`;
  const response = await fetch(source, {
    headers: { Accept: "text/plain" },
  });

  if (!response.ok) {
    return Response.json(
      { ok: false, message: "The canonical GitHub file could not be fetched." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }

  const body = await response.arrayBuffer();
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": item.contentType,
      "Content-Disposition": `attachment; filename="${item.filename}"`,
      "Cache-Control": "no-store",
      "X-EVE-Source": item.path,
    },
  });
};
