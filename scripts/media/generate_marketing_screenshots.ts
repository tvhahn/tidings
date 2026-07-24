#!/usr/bin/env tsx
/**
 * Capture real product screenshots of the static-fixture demo SPA for the
 * marketing landing (frontend/src/marketing/) and the repo README.
 *
 * Drives the demo with Playwright Chromium at 1440×900 @2x, the warm-paper
 * palette forced (what a new user sees — DEFAULT_PALETTE in stores/theme.ts),
 * demo banner hidden, and writes light + dark pairs to two places:
 *
 *   - frontend/src/marketing/assets/  — screenshot-<slug>.webp (light) and
 *     screenshot-<slug>-dark.webp, imported through Vite so the files are
 *     hashed and bundled (not public/). BrowserShot picks the plate to match
 *     the landing's own .dark class.
 *   - docs/media/readme/             — <slug>-{light,dark}.{webp,png} for
 *     README.md's <picture> blocks (journal/budgets/insights), plus the "Your
 *     data. Your path." card captured from the marketing landing (data-path).
 *     The .png is the lossless twin GitHub links as the click-through target;
 *     it is written from the same capture so the pair can never drift.
 *
 * Demo fixtures are deterministic, so captures are reproducible; the pinned
 * months are derived from the fixture files themselves, so the script
 * survives fixture regeneration. The journal shot pins the latest month —
 * the in-progress month the demo itself lands on — while insights pins the
 * second-latest (a complete month, with a full-month briefing).
 *
 * Regenerate (both dev servers must already be running):
 *   make dev-demo                                # serves fixtures on :5176
 *   make dev-marketing                           # serves landing on :5175
 *   cd frontend && pnpm marketing:screenshots    # captures from both
 *
 * Against other ports (e.g. a worktree's offset servers):
 *   MARKETING_SHOTS_URL=http://localhost:5186 \
 *   MARKETING_LANDING_URL=http://localhost:5185 pnpm marketing:screenshots
 */

import { mkdir, readdir, writeFile } from "node:fs/promises"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const REPO_ROOT = resolve(__dirname, "..", "..")
const MARKETING_OUT_DIR = resolve(REPO_ROOT, "frontend/src/marketing/assets")
const README_OUT_DIR = resolve(REPO_ROOT, "docs/media/readme")
const FIXTURE_DIR = resolve(REPO_ROOT, "frontend/public/demo-data")
const DEMO_BASE_URL = process.env.MARKETING_SHOTS_URL ?? "http://localhost:5176"
const LANDING_BASE_URL = process.env.MARKETING_LANDING_URL ?? "http://localhost:5175"

const VIEWPORT = { width: 1440, height: 900 }
const SCALE = 2
const WEBP_QUALITY = 0.82

type Mode = "light" | "dark"
const MODES: Mode[] = ["light", "dark"]

// Resolve Playwright from frontend/ — the repo root has no node_modules.
const requireFrontend = createRequire(resolve(REPO_ROOT, "frontend/package.json"))
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { chromium } = requireFrontend("@playwright/test") as typeof import("@playwright/test")

type PinnedMonths = {
  /** Latest fixture month — in progress, what the demo lands on. */
  latest: string
  /** Second-latest fixture month — always a complete month of data. */
  complete: string
}

type Shot = {
  slug: string
  path: (months: PinnedMonths) => string
  /** Settles the page (waits + scroll) before capture. */
  settle?: (page: import("@playwright/test").Page) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    slug: "screenshot-journal",
    // The demo's own landing view: a few calm days, one over-daily-budget
    // day (the Apple Store purchase) in the red.
    path: ({ latest }) => `/?month=${latest}`,
  },
  {
    slug: "screenshot-budgets",
    path: () => "/budgets",
  },
  {
    slug: "screenshot-insights",
    path: ({ complete }) => `/insights?month=${complete}`,
    settle: async (page) => {
      // The briefing prose is the point of this capture — bring it up, then
      // back off so the category cards still peek in above it. The app scrolls
      // its inner <main>, not the document, so nudge that scroller: aiming at
      // document.scrollingElement silently did nothing.
      const headline = page.getByRole("heading", { name: "Headline" })
      await headline.waitFor({ state: "visible", timeout: 15_000 })
      await headline.evaluate((el) => {
        el.scrollIntoView({ block: "start" })
        const scroller = el.closest("main") ?? document.scrollingElement
        if (scroller) scroller.scrollTop -= 140
      })
    },
  },
]

async function pinnedMonths(): Promise<PinnedMonths> {
  const files = await readdir(FIXTURE_DIR)
  const months = files
    .map((f) => /^summary-(\d{4}-\d{2})\.json$/.exec(f)?.[1])
    .filter((m): m is string => !!m)
    .sort()
  if (months.length < 2) throw new Error(`Expected ≥2 summary fixtures in ${FIXTURE_DIR}`)
  return {
    latest: months[months.length - 1] as string,
    complete: months[months.length - 2] as string,
  }
}

async function encodeWebp(
  page: import("@playwright/test").Page,
  png: Buffer
): Promise<Buffer> {
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

/** The FOWC inline script in both entry HTMLs reads these keys before first
 *  paint, so a themed context renders correctly from the first frame. */
async function newThemedContext(
  browser: import("@playwright/test").Browser,
  mode: Mode
): Promise<import("@playwright/test").BrowserContext> {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
    reducedMotion: "reduce",
  })
  await context.addInitScript((m) => {
    localStorage.setItem("theme", m)
    // Pin the palette a new user lands on (mirrors DEFAULT_PALETTE in
    // frontend/src/stores/theme.ts) so screenshots show the out-of-box look —
    // the same thing the landing itself shows.
    localStorage.setItem("theme.palette", "warm-paper")
    localStorage.setItem("demo-tour:dismissed", "true")
  }, mode)
  return context
}

async function main(): Promise<void> {
  await mkdir(MARKETING_OUT_DIR, { recursive: true })
  await mkdir(README_OUT_DIR, { recursive: true })
  const months = await pinnedMonths()
  console.log(
    `Capturing demo from ${DEMO_BASE_URL}, landing from ${LANDING_BASE_URL} (journal ${months.latest}, insights ${months.complete})`
  )

  const browser = await chromium.launch()
  let total = 0
  try {
    for (const mode of MODES) {
      const context = await newThemedContext(browser, mode)
      const page = await context.newPage()

      for (const shot of SHOTS) {
        const url = `${DEMO_BASE_URL}${shot.path(months)}`
        await page.goto(url, { waitUntil: "networkidle" })
        await page.evaluate(() => document.fonts.ready)
        // Marketing art shows the product, not the demo overlay.
        await page.addStyleTag({ content: "*::-webkit-scrollbar { display: none }" })
        await page.evaluate(() => {
          const span = Array.from(document.querySelectorAll("span")).find(
            (s) => s.textContent?.trim() === "Demo mode"
          )
          const banner = span?.closest("div.border-b")
          if (banner instanceof HTMLElement) banner.style.display = "none"
        })
        await shot.settle?.(page)
        await page.waitForTimeout(250)
        const png = await page.screenshot({ type: "png" })
        const webp = await encodeWebp(page, png)

        const readmeBase = `${shot.slug.replace(/^screenshot-/, "")}-${mode}`
        await writeFile(resolve(README_OUT_DIR, `${readmeBase}.webp`), webp)
        await writeFile(resolve(README_OUT_DIR, `${readmeBase}.png`), png)
        total += webp.byteLength + png.byteLength
        console.log(
          `  [ok] readme/${readmeBase}.{webp,png} <- ${url} (${(webp.byteLength / 1024).toFixed(0)} + ${(png.byteLength / 1024).toFixed(0)} KB)`
        )

        // The landing carries both plates and swaps on its own .dark class
        // (BrowserShot's srcDark); light keeps the original, unsuffixed name.
        const landingName = mode === "dark" ? `${shot.slug}-dark.webp` : `${shot.slug}.webp`
        await writeFile(resolve(MARKETING_OUT_DIR, landingName), webp)
        console.log(`  [ok] marketing/${landingName} (same capture)`)
      }

      // "Your data. Your path." card from the marketing landing — the
      // README's architecture graphic.
      await page.goto(`${LANDING_BASE_URL}/`, { waitUntil: "networkidle" })
      await page.evaluate(() => document.fonts.ready)
      const card = page.locator("#privacy .arch-card")
      await card.scrollIntoViewIfNeeded()
      await page.waitForTimeout(250)
      const cardPng = await card.screenshot({ type: "png" })
      const cardWebp = await encodeWebp(page, cardPng)
      await writeFile(resolve(README_OUT_DIR, `data-path-${mode}.webp`), cardWebp)
      await writeFile(resolve(README_OUT_DIR, `data-path-${mode}.png`), cardPng)
      total += cardWebp.byteLength + cardPng.byteLength
      console.log(
        `  [ok] readme/data-path-${mode}.{webp,png} <- ${LANDING_BASE_URL}/#privacy (${(cardWebp.byteLength / 1024).toFixed(0)} + ${(cardPng.byteLength / 1024).toFixed(0)} KB)`
      )

      await context.close()
    }
  } finally {
    await browser.close()
  }

  console.log(`\nScreenshots total: ${(total / 1024).toFixed(0)} KB`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
