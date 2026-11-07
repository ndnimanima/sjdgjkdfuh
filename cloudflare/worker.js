/**
 * Cloudflare Worker edge proxy for Rozaneh.
 *
 * FastAPI, SQLite, media extraction and the scheduler remain on a persistent
 * container/VPS origin. The Worker safely forwards same-origin browser traffic
 * to that service; it is not intended to run the Python application itself.
 * Set ROZANEH_ORIGIN to the origin's HTTPS base URL (no trailing path).
 */
export default {
  async fetch(request, env, ctx) {
    const originValue = env.ROZANEH_ORIGIN;
    if (!originValue) {
      return new Response("ROZANEH_ORIGIN is not configured. See docs/DEPLOY.md.", {
        status: 503,
        headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
      });
    }

    let origin;
    try {
      origin = new URL(originValue);
      if (origin.protocol !== "https:" && origin.hostname !== "localhost" && origin.hostname !== "127.0.0.1") {
        throw new Error("Origin must use HTTPS.");
      }
    } catch (error) {
      return new Response("Invalid ROZANEH_ORIGIN configuration.", {
        status: 500,
        headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
      });
    }

    const incoming = new URL(request.url);
    const target = new URL(incoming.pathname + incoming.search, origin);
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.set("x-forwarded-host", incoming.host);
    headers.set("x-forwarded-proto", incoming.protocol.replace(":", ""));
    headers.set("x-forwarded-for", request.headers.get("cf-connecting-ip") || "");
    headers.set("x-real-ip", request.headers.get("cf-connecting-ip") || "");
    headers.set("x-rozaneh-edge", "cloudflare-worker");

    const init = {
      method: request.method,
      headers,
      redirect: "manual",
    };
    if (request.method !== "GET" && request.method !== "HEAD") init.body = request.body;

    let upstream;
    try {
      upstream = await fetch(new Request(target.toString(), init));
    } catch (error) {
      return new Response("Rozaneh origin is unavailable.", {
        status: 502,
        headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
      });
    }

    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.set("x-rozaneh-edge", "cloudflare-worker");
    // Panel/auth/API responses must never be cached at the edge.
    responseHeaders.set("cache-control", "no-store");
    responseHeaders.delete("server");

    if (env.LOG_EDGE_ACCESS === "1" && env.EDGE_DB) {
      const requestId = request.headers.get("cf-ray") || crypto.randomUUID();
      const path = incoming.pathname.slice(0, 240);
      ctx.waitUntil(
        env.EDGE_DB.prepare(
          "INSERT INTO edge_access_log (request_id, method, path, status, created_at) VALUES (?, ?, ?, ?, ?)"
        )
          .bind(requestId, request.method, path, upstream.status, new Date().toISOString())
          .run()
          .catch(() => undefined)
      );
    }

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  },
};
