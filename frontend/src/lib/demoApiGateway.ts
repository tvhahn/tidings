/**
 * Pure routing logic for the hosted demo API (`gettidings.com/demo/api/*`).
 *
 * This module is the single source of truth for how a real API URL maps onto a
 * committed demo fixture. It is imported by BOTH the runtime Cloudflare Pages
 * Function (`frontend/functions/demo/api/[[path]].js`) and the build-time
 * manifest generator (`scripts/demo/generate_demo_api_manifest.ts`) so the two can
 * never disagree about canonical form (spec L4/L9). It has no I/O and no
 * Cloudflare types — behaviour is covered by `demoApiGateway.test.ts`.
 */

/** Machine codes mirror `src/api/errors.py` (`_STATUS_TO_CODE`). */
const NOT_FOUND_BODY_ERROR =
  "that route isn't in the demo snapshot — the demo world covers 2025-05 through 2026-03";
const METHOD_NOT_ALLOWED_BODY_ERROR =
  "the demo API is read-only — self-host Tidings for a writable journal";
const SELF_HOST_URL = "https://github.com/tvhahn/tidings#quickstart";
const OPENAPI_ASSET = "/demo-api/openapi.json";
const MANIFEST_ASSET = "/demo-api/manifest.json";

/** The `/demo/api` prefix every incoming pathname carries. */
const API_PREFIX = "/demo/api";

/** At most this many sibling variants are listed in a 404 `details.available`. */
const MAX_AVAILABLE = 12;

export interface DemoApiManifest {
  name?: string;
  description?: string;
  base: string;
  openapi: string;
  demo_today: string;
  months: string[];
  endpoints: Record<string, string>;
}

export interface GatewayErrorBody {
  error: string;
  code: string;
  details: Record<string, unknown> | null;
}

export type GatewayResult =
  | { kind: "preflight" }
  | { kind: "asset"; assetPath: string }
  | { kind: "error"; status: 404 | 405; body: GatewayErrorBody };

/**
 * Canonical form of a URL relative to `/api/v1`: trailing slash stripped from
 * the path (except a bare `/`); query params URL-decoded, sorted by
 * `(key, value)`, and re-encoded. Shared by the resolver and the manifest
 * generator so a snapshotted key and an incoming request agree byte-for-byte.
 */
export function canonicalize(url: string): string {
  const qIndex = url.indexOf("?");
  let path = qIndex === -1 ? url : url.slice(0, qIndex);
  const query = qIndex === -1 ? "" : url.slice(qIndex + 1);

  if (path.length > 1 && path.endsWith("/")) {
    path = path.replace(/\/+$/, "");
    if (path === "") path = "/";
  }

  if (!query) return path;

  const entries = [...new URLSearchParams(query).entries()].sort((a, b) => {
    if (a[0] !== b[0]) return a[0] < b[0] ? -1 : 1;
    if (a[1] !== b[1]) return a[1] < b[1] ? -1 : 1;
    return 0;
  });

  const sorted = new URLSearchParams();
  for (const [key, value] of entries) sorted.append(key, value);
  const qs = sorted.toString();
  return qs ? `${path}?${qs}` : path;
}

function notFound(details: Record<string, unknown>): GatewayResult {
  return {
    kind: "error",
    status: 404,
    body: { error: NOT_FOUND_BODY_ERROR, code: "NOT_FOUND", details },
  };
}

function methodNotAllowed(): GatewayResult {
  return {
    kind: "error",
    status: 405,
    body: {
      error: METHOD_NOT_ALLOWED_BODY_ERROR,
      code: "METHOD_NOT_ALLOWED",
      details: { self_host: SELF_HOST_URL },
    },
  };
}

/**
 * Resolve an incoming demo-API request to a fixture asset, a preflight, or a
 * structured error — exactly the README §Contracts resolver table. `pathname`
 * carries the `/demo/api` prefix; `search` may include a leading `?`. The
 * method check is case-insensitive and HEAD is treated as GET.
 */
export function resolveDemoApiRequest(
  method: string,
  pathname: string,
  search: string,
  manifest: DemoApiManifest
): GatewayResult {
  const verb = method.toUpperCase();
  if (verb === "OPTIONS") return { kind: "preflight" };
  if (verb !== "GET" && verb !== "HEAD") return methodNotAllowed();

  const rest = pathname.startsWith(API_PREFIX) ? pathname.slice(API_PREFIX.length) : pathname;

  // Discovery roots and the manifest itself.
  if (
    rest === "" ||
    rest === "/" ||
    rest === "/v1" ||
    rest === "/v1/" ||
    rest === "/manifest.json"
  ) {
    return { kind: "asset", assetPath: MANIFEST_ASSET };
  }
  if (rest === "/openapi.json") {
    return { kind: "asset", assetPath: OPENAPI_ASSET };
  }

  // Versioned API surface: `/demo/api/v1/<rest>`.
  if (rest.startsWith("/v1/")) {
    const apiPath = rest.slice("/v1".length); // keeps the leading slash, e.g. "/transactions"
    const searchStr = search.startsWith("?") ? search.slice(1) : search;
    const key = canonicalize(searchStr ? `${apiPath}?${searchStr}` : apiPath);

    const assetPath = manifest.endpoints[key];
    if (assetPath !== undefined) return { kind: "asset", assetPath };

    // Known path, unknown query variant → list the siblings that share the path.
    const canonPath = canonicalize(apiPath);
    const available = Object.keys(manifest.endpoints)
      .filter((k) => k.split("?")[0] === canonPath)
      .sort()
      .slice(0, MAX_AVAILABLE);
    if (available.length > 0) return notFound({ available });
  }

  // Wholly unknown path.
  return notFound({ openapi: "/demo/api/openapi.json" });
}
