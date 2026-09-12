import { canonicalResource } from "./routing.js";

function plainResponse(message: string, status: number): Response {
  const headers = new Headers({
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-store",
    "Content-Type": "text/plain; charset=utf-8",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "X-Content-Type-Options": "nosniff",
  });
  if (status === 405) {
    headers.set("Allow", "GET, HEAD, OPTIONS");
  }

  return new Response(`${message}\n`, {
    status,
    headers,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "GET" && request.method !== "HEAD" && request.method !== "OPTIONS") {
      return plainResponse("Method not allowed", 405);
    }

    const requestUrl = new URL(request.url);
    const assetPath = canonicalResource(requestUrl.pathname);
    if (assetPath === null) {
      return plainResponse("Not found", 404);
    }

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          Allow: "GET, HEAD, OPTIONS",
          "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control": "public, max-age=86400",
        },
      });
    }

    const assetUrl = new URL(request.url);
    assetUrl.pathname = assetPath;
    assetUrl.search = "";
    assetUrl.hash = "";
    const assetRequest = new Request(assetUrl, {
      method: request.method,
      headers: request.headers,
    });
    const assetResponse = await env.ASSETS.fetch(assetRequest);
    if (assetResponse.status === 404) {
      return plainResponse("Not found", 404);
    }

    const headers = new Headers(assetResponse.headers);
    headers.set("Access-Control-Allow-Origin", "*");
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
    headers.set("Cross-Origin-Resource-Policy", "cross-origin");
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set(
      "Content-Type",
      assetPath.endsWith(".schema.json")
        ? "application/schema+json; charset=utf-8"
        : "application/json; charset=utf-8",
    );

    return new Response(assetResponse.body, {
      status: assetResponse.status,
      statusText: assetResponse.statusText,
      headers,
    });
  },
} satisfies ExportedHandler<Env>;
