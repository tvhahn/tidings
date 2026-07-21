#!/usr/bin/env tsx
/**
 * Snapshot read-only backend responses into static JSON fixtures for the
 * hosted demo. Expects a FastAPI dev server to be running at
 * http://localhost:8000 in SQLite demo_mode.
 *
 * Usage:
 *   tsx scripts/demo/generate_demo_fixtures.ts            # skip AI-derived endpoints
 *   tsx scripts/demo/generate_demo_fixtures.ts --include-ai
 */

import { mkdir, writeFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { ENDPOINTS } from "./demo_endpoints"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const REPO_ROOT = resolve(__dirname, "..", "..")
const OUT_DIR = resolve(REPO_ROOT, "frontend/public/demo-data")
const API_BASE = process.env.DEMO_API_BASE ?? "http://localhost:8000/api/v1"

const includeAi = process.argv.includes("--include-ai")

async function ensureDir(path: string): Promise<void> {
  await mkdir(path, { recursive: true })
}

async function fetchEndpoint(url: string): Promise<unknown> {
  const full = `${API_BASE}${url}`
  const res = await fetch(full, { headers: { accept: "application/json" } })
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${full}\n${body.slice(0, 200)}`)
  }
  // FastAPI may emit `Infinity` / `NaN` literals (invalid JSON) when an endpoint
  // divides by zero (e.g. summary comparison with no prior month). Replace them
  // with `null` before parsing so fixtures stay well-formed.
  const raw = await res.text()
  const sanitised = raw
    .replace(/:\s*-?Infinity\b/g, ": null")
    .replace(/:\s*NaN\b/g, ": null")
  return JSON.parse(sanitised)
}

async function main(): Promise<void> {
  await ensureDir(OUT_DIR)
  let ok = 0
  let skipped = 0
  let failed = 0

  for (const ep of ENDPOINTS) {
    if (ep.ai && !includeAi) {
      console.log(`  [skip] ${ep.slug} (AI; pass --include-ai)`)
      skipped++
      continue
    }
    try {
      const data = await fetchEndpoint(ep.url)
      const file = resolve(OUT_DIR, `${ep.slug}.json`)
      await writeFile(file, JSON.stringify(data, null, 2) + "\n", "utf-8")
      console.log(`  [ok]   ${ep.slug} <- ${ep.url}`)
      ok++
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      if (ep.optional) {
        console.log(`  [skip] ${ep.slug} (optional, ${msg.split("\n")[0]})`)
        skipped++
      } else {
        console.error(`  [FAIL] ${ep.slug}: ${msg}`)
        failed++
      }
    }
  }

  console.log(`\n${ok} ok · ${skipped} skipped · ${failed} failed`)
  if (failed > 0) process.exit(1)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
