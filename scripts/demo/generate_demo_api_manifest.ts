#!/usr/bin/env tsx
/**
 * Generate the hosted demo API manifest — the map the Cloudflare Pages Function
 * uses to resolve a real API URL onto a committed demo fixture.
 *
 * The manifest keys are `canonicalize()`d URLs relative to /api/v1; values are
 * absolute asset paths under the deployed origin. Coverage is the ENDPOINTS list
 * in demo_endpoints.ts filtered to fixtures that actually exist on disk (ragged
 * coverage is expected — journal-summaries/insights-saved only exist for the AI
 * months), plus a synthetic /health entry served from the hand-authored
 * demo-api/health.json.
 *
 * `canonicalize` is imported from the runtime gateway module so the manifest and
 * the resolver can never disagree (spec L4). Output is byte-stable
 * (2-space indent, key-sorted endpoints, trailing newline) so `verify-demo-api`
 * can gate regen with `git diff --exit-code`.
 *
 * Usage: tsx scripts/demo/generate_demo_api_manifest.ts
 */

import { existsSync } from "node:fs"
import { writeFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { canonicalize } from "../../frontend/src/lib/demoApiGateway"
import { DEMO_MONTHS, ENDPOINTS } from "./demo_endpoints"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const REPO_ROOT = resolve(__dirname, "..", "..")
const FIXTURE_DIR = resolve(REPO_ROOT, "frontend/public/demo-data")
const OUT_FILE = resolve(REPO_ROOT, "frontend/public/demo-api/manifest.json")

const DEMO_TODAY = "2026-03-19"

async function main(): Promise<void> {
  const endpoints: Record<string, string> = {}
  let included = 0
  let skipped = 0

  for (const ep of ENDPOINTS) {
    if (!existsSync(resolve(FIXTURE_DIR, `${ep.slug}.json`))) {
      console.log(`  ${ep.slug} — no fixture, skipped`)
      skipped++
      continue
    }
    endpoints[canonicalize(ep.url)] = `/demo-data/${ep.slug}.json`
    included++
  }

  // Synthetic entry: /health is hand-authored inside the demo world (spec L8),
  // not snapshotted from a live backend.
  endpoints["/health"] = "/demo-api/health.json"

  const sortedEndpoints: Record<string, string> = {}
  for (const key of Object.keys(endpoints).sort()) {
    sortedEndpoints[key] = endpoints[key]
  }

  const manifest = {
    name: "Tidings demo API",
    description: "Read-only snapshot of the Tidings demo journal. All data is fictional.",
    base: "/demo/api/v1",
    openapi: "/demo/api/openapi.json",
    demo_today: DEMO_TODAY,
    months: [...DEMO_MONTHS],
    endpoints: sortedEndpoints,
  }

  await writeFile(OUT_FILE, JSON.stringify(manifest, null, 2) + "\n", "utf-8")
  console.log(`\n${included} fixtures + /health · ${skipped} skipped → ${OUT_FILE}`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
