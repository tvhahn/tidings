import { describe, expect, it } from "vitest";
import { canonicalize, resolveDemoApiRequest, type DemoApiManifest } from "./demoApiGateway";

const manifest: DemoApiManifest = {
  name: "Tidings demo API",
  description: "Read-only snapshot of the Tidings demo journal. All data is fictional.",
  base: "/demo/api/v1",
  openapi: "/demo/api/openapi.json",
  demo_today: "2026-03-19",
  months: ["2025-05", "2026-03"],
  endpoints: {
    "/categories": "/demo-data/categories.json",
    "/health": "/demo-api/health.json",
    "/summary/trend?end_month=2026-03&months=6": "/demo-data/summary-trend.json",
    "/transactions?month=2026-01": "/demo-data/transactions-2026-01.json",
    "/transactions?month=2026-02": "/demo-data/transactions-2026-02.json",
    "/transactions?month=2026-03": "/demo-data/transactions-2026-03.json",
  },
};

describe("canonicalize", () => {
  it("1. sorts multi-param queries by (key, value)", () => {
    expect(canonicalize("/summary/trend?months=6&end_month=2026-03")).toBe(
      "/summary/trend?end_month=2026-03&months=6"
    );
  });

  it("2. strips a trailing slash from the path", () => {
    expect(canonicalize("/transactions/")).toBe("/transactions");
    expect(canonicalize("/")).toBe("/");
  });

  it("3. is idempotent", () => {
    const once = canonicalize("/summary/trend?months=6&end_month=2026-03");
    expect(canonicalize(once)).toBe(once);
  });

  it("4. preserves an already-canonical URL", () => {
    expect(canonicalize("/transactions?month=2026-03")).toBe("/transactions?month=2026-03");
  });

  it("5. decodes percent-encoded values so they hit the same key", () => {
    expect(canonicalize("/transactions?month=2026%2D03")).toBe("/transactions?month=2026-03");
  });
});

describe("resolveDemoApiRequest", () => {
  it("6. OPTIONS on any path is a preflight", () => {
    expect(
      resolveDemoApiRequest("OPTIONS", "/demo/api/v1/transactions", "?month=2026-03", manifest)
    ).toEqual({
      kind: "preflight",
    });
  });

  it("7. POST returns 405 with the locked body verbatim", () => {
    const result = resolveDemoApiRequest("POST", "/demo/api/v1/overrides", "", manifest);
    expect(result).toEqual({
      kind: "error",
      status: 405,
      body: {
        error: "the demo API is read-only — self-host Tidings for a writable journal",
        code: "METHOD_NOT_ALLOWED",
        details: { self_host: "https://github.com/tvhahn/tidings#quickstart" },
      },
    });
  });

  it("8. DELETE returns 405", () => {
    const result = resolveDemoApiRequest("DELETE", "/demo/api/v1/categories", "", manifest);
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.status).toBe(405);
      expect(result.body.code).toBe("METHOD_NOT_ALLOWED");
    }
  });

  it("9. HEAD of a known URL resolves to the asset", () => {
    expect(
      resolveDemoApiRequest("HEAD", "/demo/api/v1/transactions", "?month=2026-03", manifest)
    ).toEqual({
      kind: "asset",
      assetPath: "/demo-data/transactions-2026-03.json",
    });
  });

  it("10. GET a known URL resolves to the manifest asset path", () => {
    expect(
      resolveDemoApiRequest("GET", "/demo/api/v1/transactions", "?month=2026-03", manifest)
    ).toEqual({
      kind: "asset",
      assetPath: "/demo-data/transactions-2026-03.json",
    });
  });

  it("11. reordered params resolve to the same asset", () => {
    expect(
      resolveDemoApiRequest(
        "GET",
        "/demo/api/v1/summary/trend",
        "?months=6&end_month=2026-03",
        manifest
      )
    ).toEqual({ kind: "asset", assetPath: "/demo-data/summary-trend.json" });
  });

  it("12. unknown query variant on a known path is a 404 listing available variants", () => {
    const result = resolveDemoApiRequest(
      "GET",
      "/demo/api/v1/transactions",
      "?month=2024-01",
      manifest
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.status).toBe(404);
      expect(result.body.code).toBe("NOT_FOUND");
      const available = result.body.details?.available as string[];
      expect(Array.isArray(available)).toBe(true);
      expect(available.length).toBeGreaterThan(0);
      expect(available.length).toBeLessThanOrEqual(12);
      expect(available).toContain("/transactions?month=2026-03");
    }
  });

  it("13. a wholly unknown path is a 404 pointing at the openapi schema", () => {
    const result = resolveDemoApiRequest("GET", "/demo/api/v1/nonexistent", "", manifest);
    expect(result).toEqual({
      kind: "error",
      status: 404,
      body: {
        error:
          "that route isn't in the demo snapshot — the demo world covers 2025-05 through 2026-03",
        code: "NOT_FOUND",
        details: { openapi: "/demo/api/openapi.json" },
      },
    });
  });

  it("14. /demo/api/ and /demo/api/v1 resolve to the manifest asset", () => {
    for (const path of [
      "/demo/api",
      "/demo/api/",
      "/demo/api/v1",
      "/demo/api/v1/",
      "/demo/api/manifest.json",
    ]) {
      expect(resolveDemoApiRequest("GET", path, "", manifest)).toEqual({
        kind: "asset",
        assetPath: "/demo-api/manifest.json",
      });
    }
  });

  it("15. /demo/api/openapi.json resolves to the openapi asset", () => {
    expect(resolveDemoApiRequest("GET", "/demo/api/openapi.json", "", manifest)).toEqual({
      kind: "asset",
      assetPath: "/demo-api/openapi.json",
    });
  });

  it("16. /demo/api/v1/health resolves to /demo-api/health.json", () => {
    expect(resolveDemoApiRequest("GET", "/demo/api/v1/health", "", manifest)).toEqual({
      kind: "asset",
      assetPath: "/demo-api/health.json",
    });
  });

  it("17. a lowercase method verb is accepted", () => {
    expect(resolveDemoApiRequest("get", "/demo/api/v1/categories", "", manifest)).toEqual({
      kind: "asset",
      assetPath: "/demo-data/categories.json",
    });
  });
});
