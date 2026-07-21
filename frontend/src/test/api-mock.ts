import { vi } from "vitest";

type FetchMock = ReturnType<typeof vi.fn>;

export type RouteResponder = (init?: RequestInit) => unknown | Promise<unknown>;
export type RouteMap = Record<string, unknown | RouteResponder>;

/**
 * Stub global `fetch` so any caller of `fetchJSON` (`src/lib/api.ts:66-72`) or
 * `loadDemoFixture` (`src/lib/demoFetch.ts`) gets predictable JSON without a
 * real network. Pass an exact-match URL → response map; anything not in the map
 * resolves to a 404 so missing routes surface loudly in tests.
 */
export function mockFetchJSON(routes: RouteMap = {}): FetchMock {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const responder = findResponder(routes, url);
    if (responder === undefined) {
      return jsonResponse({ error: `unmocked fetch: ${url}` }, 404);
    }
    const value = typeof responder === "function" ? await responder(init) : responder;
    return jsonResponse(value, 200);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/**
 * Stub global `fetch` to fail with an error status and a `{ error, code,
 * details }` body — the shape `fetchJSON` (`src/lib/api.ts`) surfaces on a
 * non-OK response. Use in hook tests that exercise the error / rollback path;
 * reset it with `vi.unstubAllGlobals()` (typically in `afterEach`).
 */
export function mockFetchError(
  status = 500,
  body: unknown = { error: "boom", code: "X", details: null }
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(body, status))
  );
}

function findResponder(routes: RouteMap, url: string): unknown | RouteResponder | undefined {
  if (url in routes) return routes[url];
  const pathOnly = url.split("?")[0] ?? url;
  if (pathOnly in routes) return routes[pathOnly];
  return undefined;
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
