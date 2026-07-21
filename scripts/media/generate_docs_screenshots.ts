#!/usr/bin/env tsx
/**
 * Capture "Using Tidings" docs screenshots from the built static-fixture demo
 * SPA. For every target in docs_screenshots.manifest.ts this writes a light +
 * dark WebP pair to docs-site/src/assets/screenshots/<id>-<theme>.webp — the
 * variants ThemedScreenshot.astro swaps between on Starlight's data-theme.
 *
 * Modelled on generate_marketing_screenshots.ts: Playwright Chromium, the base
 * "default" palette forced via the FOWC localStorage keys, demo banner and
 * scrollbars hidden, reducedMotion "reduce", 2x device scale, viewport (not
 * full-page) capture — the demo shell scrolls its inner <main>, so full-page
 * logic would misbehave. Demo fixtures are deterministic (pinned clock), so
 * captures are reproducible.
 *
 * This script does NOT boot the server. Point it at an already-serving build
 * of the demo (see `make docs-screenshots`, which builds + serves on :4179):
 *
 *   cd frontend && pnpm demo:build
 *   cd frontend && pnpm exec serve dist -l 4179
 *   cd frontend && pnpm exec tsx ../scripts/media/generate_docs_screenshots.ts
 *
 * Against another port/host:
 *   DOCS_SHOTS_URL=http://localhost:4188 \
 *     pnpm exec tsx ../scripts/media/generate_docs_screenshots.ts
 */

import { mkdir, writeFile } from "node:fs/promises"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { DOCS_SHOTS, type DocsShot, type DocsShotViewport } from "./docs_screenshots.manifest.ts"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const REPO_ROOT = resolve(__dirname, "..", "..")
const OUT_DIR = resolve(REPO_ROOT, "docs-site/src/assets/screenshots")
const BASE_URL = process.env.DOCS_SHOTS_URL ?? "http://localhost:4179"

const VIEWPORTS: Record<DocsShotViewport, { width: number; height: number }> = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
}
const SCALE = 2
const WEBP_QUALITY = 0.82

type Mode = "light" | "dark"
const MODES: Mode[] = ["light", "dark"]

// Resolve Playwright from frontend/ — the repo root has no node_modules.
const requireFrontend = createRequire(resolve(REPO_ROOT, "frontend/package.json"))
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { chromium } = requireFrontend("@playwright/test") as typeof import("@playwright/test")

type Browser = import("@playwright/test").Browser
type BrowserContext = import("@playwright/test").BrowserContext
type Page = import("@playwright/test").Page

async function encodeWebp(page: Page, png: Buffer): Promise<Buffer> {
  const dataUrl = await page.evaluate(
    async ({ b64, quality }) => {
      const img = new Image()
      img.src = `data:image/png;base64,${b64}`
      await img.decode()
      const canvas = document.createElement("canvas")
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      const ctx = canvas.getContext("2d")
      if (!ctx) throw new Error("no 2d context")
      ctx.drawImage(img, 0, 0)
      return canvas.toDataURL("image/webp", quality)
    },
    { b64: png.toString("base64"), quality: WEBP_QUALITY }
  )
  const prefix = "data:image/webp;base64,"
  if (!dataUrl.startsWith(prefix)) throw new Error("WebP encoding failed")
  return Buffer.from(dataUrl.slice(prefix.length), "base64")
}

/** The FOWC inline script in demo/index.html reads these keys before first
 *  paint, so a themed context renders correctly from the first frame. */
async function newThemedContext(
  browser: Browser,
  mode: Mode,
  viewport: DocsShotViewport
): Promise<BrowserContext> {
  const context = await browser.newContext({
    viewport: VIEWPORTS[viewport],
    deviceScaleFactor: SCALE,
    reducedMotion: "reduce",
  })
  await context.addInitScript((m) => {
    localStorage.setItem("theme", m)
    // Pin the palette a new user lands on (mirrors DEFAULT_PALETTE in
    // frontend/src/stores/theme.ts) so screenshots show the out-of-box look.
    localStorage.setItem("theme.palette", "warm-paper")
    localStorage.setItem("demo-tour:dismissed", "true")
  }, mode)
  return context
}

/** Wait for loading skeletons and dot-loaders to clear — a generic guard that
 *  keeps a capture off a mid-load frame regardless of the page. Best-effort:
 *  never fatal, the per-shot waitFor and settle timeout are the backstops. */
async function waitLoadersGone(page: Page): Promise<void> {
  await page
    .waitForFunction(
      () =>
        document.querySelectorAll(".animate-pulse").length === 0 &&
        document.querySelectorAll(".animate-bounce").length === 0,
      undefined,
      { timeout: 8000 }
    )
    .catch(() => {})
}

async function hideChrome(page: Page): Promise<void> {
  await page.addStyleTag({ content: "*::-webkit-scrollbar { display: none }" })
  await page.evaluate(() => {
    const span = Array.from(document.querySelectorAll("span")).find(
      (s) => s.textContent?.trim() === "Demo mode"
    )
    const banner = span?.closest("div.border-b")
    if (banner instanceof HTMLElement) banner.style.display = "none"
  })
}

async function captureShot(page: Page, shot: DocsShot, mode: Mode): Promise<Buffer> {
  const url = `${BASE_URL}${shot.path}`
  await page.goto(url, { waitUntil: "networkidle" })
  await page.evaluate(() => document.fonts.ready)
  await waitLoadersGone(page)
  if (shot.waitFor) {
    await page.locator(shot.waitFor).first().waitFor({ state: "visible", timeout: 15_000 })
  }
  await hideChrome(page)
  // Settle: let charts/layout land after reflow (animations are reduced).
  await page.waitForTimeout(500)
  const png = await page.screenshot({ type: "png" })
  return encodeWebp(page, png)
}

async function main(): Promise<void> {
  await mkdir(OUT_DIR, { recursive: true })
  console.log(`Capturing ${DOCS_SHOTS.length} pages × ${MODES.length} themes from ${BASE_URL}`)

  const browser = await chromium.launch()
  const produced: string[] = []
  const failures: string[] = []
  let totalBytes = 0
  try {
    for (const mode of MODES) {
      // One context per viewport per theme — theme is applied at context
      // creation (addInitScript runs before any page loads).
      const contexts = {} as Record<DocsShotViewport, { ctx: BrowserContext; page: Page }>
      for (const vp of Object.keys(VIEWPORTS) as DocsShotViewport[]) {
        const ctx = await newThemedContext(browser, mode, vp)
        contexts[vp] = { ctx, page: await ctx.newPage() }
      }
      try {
        for (const shot of DOCS_SHOTS) {
          const { page } = contexts[shot.viewport]
          const file = `${shot.id}-${mode}.webp`
          try {
            const webp = await captureShot(page, shot, mode)
            await writeFile(resolve(OUT_DIR, file), webp)
            produced.push(file)
            totalBytes += webp.byteLength
            console.log(`  [ok] ${file} <- ${shot.path} (${(webp.byteLength / 1024).toFixed(0)} KB)`)
          } catch (err) {
            failures.push(file)
            console.error(`  [FAIL] ${file} <- ${shot.path}: ${(err as Error).message}`)
          }
        }
      } finally {
        for (const vp of Object.keys(contexts) as DocsShotViewport[]) {
          await contexts[vp].ctx.close()
        }
      }
    }
  } finally {
    await browser.close()
  }

  const expected = DOCS_SHOTS.length * MODES.length
  console.log(
    `\nProduced ${produced.length}/${expected} images (${(totalBytes / 1024).toFixed(0)} KB) in ${OUT_DIR}`
  )
  if (failures.length > 0) {
    console.error(`Failed captures (${failures.length}): ${failures.join(", ")}`)
    process.exit(1)
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
