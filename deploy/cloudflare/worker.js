// Cloudflare edge for the hosted Findaro: the public hostnames point here, and this forwards to the origin
// server, so the origin's address never appears in DNS. The origin only serves requests carrying EDGE_SECRET
// (Caddy checks it) and redirects everything else back to the public hostnames.
//
// Vars (set at deploy time, see deploy.sh): PUBLIC_SITE, PUBLIC_API, ORIGIN_SITE, ORIGIN_API (hostnames).
// Secret: EDGE_SECRET (`wrangler secret put EDGE_SECRET`).

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const toOrigin = { [env.PUBLIC_SITE]: env.ORIGIN_SITE, [env.PUBLIC_API]: env.ORIGIN_API };
    const toPublic = { [env.ORIGIN_SITE]: env.PUBLIC_SITE, [env.ORIGIN_API]: env.PUBLIC_API };
    const origin = toOrigin[url.hostname];
    if (!origin) return new Response("Not found", { status: 404 });
    url.protocol = "https:";
    url.hostname = origin;
    url.port = "";

    const headers = new Headers(request.headers);
    headers.set("X-Findaro-Edge", env.EDGE_SECRET);
    headers.set("X-Client-IP", request.headers.get("CF-Connecting-IP") || "");
    headers.delete("Host");

    const resp = await fetch(url.toString(), {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual",
    });
    const out = new Response(resp.body, resp);
    const loc = out.headers.get("Location");
    if (loc) {
      try {
        const l = new URL(loc, url);
        if (toPublic[l.hostname]) {
          l.hostname = toPublic[l.hostname];
          out.headers.set("Location", l.toString());
        }
      } catch {
        // leave unparsable locations alone
      }
    }
    return out;
  },
};
