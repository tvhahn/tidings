// Post-deploy smoke for the DEPLOYED web surfaces (Cloudflare Pages).
//
// Why this exists as a separate gate: `make verify` builds frontend/dist and
// serves it with `pnpm exec serve`, which honors frontend/public/serve.json.
// Cloudflare ignores serve.json and honors frontend/public/_redirects instead.
// Those are two different files implementing the same SPA-fallback rule, so a
// broken _redirects rule is invisible to every local gate — exactly what
// happened: the rewrite pointed at /demo/index.html, a path Cloudflare
// 308-canonicalizes to /demo/, so it never resolved and every demo deep link
// silently served the marketing landing page with a 200.
//
// Nothing here can run before a deploy. Run it after one:
//   make prod-smoke                       (against https://gettidings.com)
//   PROD_BASE_URL=https://<preview>.pages.dev make prod-smoke
//
// Exits non-zero on the first surface that is wrong. No dependencies.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BASE = (process.env.PROD_BASE_URL ?? "https://gettidings.com").replace(/\/$/, "");
const ATTEMPTS = Number(process.env.PROD_SMOKE_ATTEMPTS ?? 3);
const RETRY_MS = Number(process.env.PROD_SMOKE_RETRY_MS ?? 5000);

const manifest = JSON.parse(
  readFileSync(fileURLToPath(new URL("../demo/demo_routes.json", import.meta.url)), "utf8")
);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Fetch with retries — a post-deploy probe races CDN propagation. */
async function get(path) {
  let lastErr;
  for (let i = 0; i < ATTEMPTS; i++) {
    try {
      const res = await fetch(`${BASE}${path}`, { redirect: "follow" });
      return { status: res.status, type: res.headers.get("content-type") ?? "", body: await res.text() };
    } catch (err) {
      lastErr = err;
      if (i < ATTEMPTS - 1) await sleep(RETRY_MS);
    }
  }
  throw new Error(`${path}: request failed after ${ATTEMPTS} attempts — ${lastErr?.message}`);
}

/** The shell is identified by the data-surface attribute the build stamps on <html>. */
const surfaceOf = (body) => body.match(/data-surface="([^"]+)"/)?.[1] ?? "(none)";

const failures = [];
const check = (ok, label, detail) => {
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}${detail ? `  — ${detail}` : ""}`);
  if (!ok) failures.push(`${label} — ${detail}`);
};

console.log(`Probing ${BASE}\n`);

// 1. Marketing root. Guards against the demo build overwriting the landing page.
{
  const { status, body } = await get("/");
  const surface = surfaceOf(body);
  check(status === 200 && surface === "marketing", "/ serves the marketing shell", `${status} ${surface}`);
}

// 2. Every demo route must be served by the DEMO shell. A host-level SPA
//    fallback break shows up here as "marketing" with a 200 — not as a 404.
console.log("\nDemo routes (must be the demo shell, not marketing):");
for (const { path } of manifest.routes) {
  const { status, body } = await get(path);
  const surface = surfaceOf(body);
  check(status === 200 && surface === "demo", path, `${status} ${surface}`);
}

// 3. The demo API Pages Function must not be shadowed. The /demo/* rewrite in
//    _redirects overlaps /demo/api/*; the Function wins only because
//    frontend/public/_routes.json includes that prefix. If someone drops the
//    include, these start returning HTML instead of JSON.
console.log("\nDemo API function (must stay JSON, not the SPA shell):");
for (const path of ["/demo/api/openapi.json", "/demo/api/v1/health"]) {
  const { status, type } = await get(path);
  check(status === 200 && type.includes("application/json"), path, `${status} ${type}`);
}

// 4. Document the not-found behavior we rely on. An unmatched path falling
//    through to the marketing shell is what masked the original bug; assert it
//    so the masking mechanism itself is visible and intentional.
{
  const { body } = await get("/zzz-nonexistent-path-smoke");
  check(surfaceOf(body) === "marketing", "unmatched path falls back to marketing", surfaceOf(body));
}

console.log("");
if (failures.length) {
  console.error(`prod-smoke: ${failures.length} failure(s)\n${failures.map((f) => `  - ${f}`).join("\n")}`);
  process.exit(1);
}
console.log("prod-smoke: all deployed surfaces OK");
