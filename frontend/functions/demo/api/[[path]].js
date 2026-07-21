// Cloudflare Pages Function owning /demo/api/* (spec L1/L9). All routing logic
// lives in the typed, vitest-covered gateway module; this file is glue only.
// Pages' esbuild bundles the TS import from JS at deploy time.
import { resolveDemoApiRequest } from "../../../src/lib/demoApiGateway";

let manifestPromise = null;

function loadManifest(request, env) {
  if (!manifestPromise) {
    manifestPromise = env.ASSETS.fetch(new URL("/demo-api/manifest.json", request.url)).then(
      (res) => res.json()
    );
  }
  return manifestPromise;
}

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, OPTIONS",
  "access-control-allow-headers": "authorization, content-type",
};

const RESPONSE_HEADERS = {
  "content-type": "application/json",
  "access-control-allow-origin": "*",
  "cache-control": "public, max-age=300",
  "x-robots-tag": "noindex",
};

export async function onRequest({ request, env }) {
  const url = new URL(request.url);
  const manifest = await loadManifest(request, env);
  const result = resolveDemoApiRequest(request.method, url.pathname, url.search, manifest);

  if (result.kind === "preflight") {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (result.kind === "error") {
    return new Response(JSON.stringify(result.body), {
      status: result.status,
      headers: RESPONSE_HEADERS,
    });
  }
  // asset: ASSETS response headers are immutable, so re-wrap with the L7 headers.
  const asset = await env.ASSETS.fetch(new URL(result.assetPath, request.url));
  return new Response(asset.body, { status: asset.status, headers: RESPONSE_HEADERS });
}
