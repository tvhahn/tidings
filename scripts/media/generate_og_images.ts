#!/usr/bin/env tsx
/**
 * Generate the three 1200×630 social/OG cards from one flat, typographic
 * template (spec: docs/specs/00_open-source-migration/2026-07-05-web-surfaces-launch/):
 *
 *   - frontend/public/og-image.png            — marketing landing (gettidings.com)
 *   - frontend/public/demo-data/og-image.png  — demo SPA (gettidings.com/demo)
 *   - docs-site/public/og-image.png           — docs (docs.gettidings.com)
 *
 * Brand constraints (docs/brand/visual.md): warm-paper ground, left-aligned
 * type, no gradients, no shadows, no ornament. The wordmark lockup is inlined
 * from docs/brand/assets/logo-wordmark.svg — outlined to paths, so it renders
 * identically with zero font dependency. Headings load Source Serif 4 / Inter
 * from Google Fonts (same URL as frontend/index.html) with serif/sans
 * fallbacks so a failed fetch stays legible.
 *
 * The committed PNGs are the artifact; this script is the reproducible
 * regen path. Regenerate:
 *   cd frontend && pnpm og:images
 */

import { readFile, writeFile } from "node:fs/promises"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const REPO_ROOT = resolve(__dirname, "..", "..")

// Resolve Playwright from frontend/ — the repo root has no node_modules.
const requireFrontend = createRequire(resolve(REPO_ROOT, "frontend/package.json"))
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { chromium } = requireFrontend("@playwright/test") as typeof import("@playwright/test")

const WIDTH = 1200
const HEIGHT = 630

// Same font set the dashboard and marketing page load (frontend/index.html).
const FONT_STYLESHEET =
  "https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"

// Warm-paper palette (frontend/src/styles/themes.css).
const PAPER = "oklch(0.975 0.006 75)" // --popover / --muted
const INK = "oklch(0.18 0.025 55)" // --foreground
const MUTED_INK = "oklch(0.45 0.022 58)" // --fg-secondary

type Card = {
  slug: string
  /** Heading HTML — <em> marks the marketing-typography italic exception. */
  heading: string
  support: string
  domain: string
  out: string
}

const CARDS: Card[] = [
  {
    slug: "marketing",
    heading: "Your spending, <em>delivered.</em>",
    support: "A private finance journal from the transaction emails you already receive.",
    domain: "gettidings.com",
    out: resolve(REPO_ROOT, "frontend/public/og-image.png"),
  },
  {
    slug: "demo",
    heading: "Your spending, <em>delivered.</em>",
    support: "Live demo — browse the real app with sample data.",
    domain: "gettidings.com/demo",
    out: resolve(REPO_ROOT, "frontend/public/demo-data/og-image.png"),
  },
  {
    slug: "docs",
    heading: "Docs",
    support: "Quickstart, self-hosting guides, and the API reference.",
    domain: "docs.gettidings.com",
    out: resolve(REPO_ROOT, "docs-site/public/og-image.png"),
  },
]

function cardHtml(wordmarkSvg: string, card: Card): string {
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link rel="stylesheet" href="${FONT_STYLESHEET}" />
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: ${WIDTH}px; height: ${HEIGHT}px; overflow: hidden; }
      body {
        background: ${PAPER};
        color: ${INK};
        display: flex;
        flex-direction: column;
        padding: 96px;
        font-family: Inter, system-ui, sans-serif;
      }
      .wordmark svg { height: 64px; width: auto; display: block; }
      /* The asset's own style flips .word to near-white under a dark
         prefers-color-scheme; the card is always warm paper, so pin ink. */
      .wordmark .word { fill: ${INK} !important; }
      main {
        flex: 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
        padding-bottom: 20px;
      }
      h1 {
        font-family: "Source Serif 4", Georgia, serif;
        font-weight: 600;
        font-size: 76px;
        line-height: 1.1;
        letter-spacing: -0.01em;
      }
      .support {
        margin-top: 28px;
        font-weight: 400;
        font-size: 30px;
        line-height: 1.45;
        color: ${MUTED_INK};
        max-width: 900px;
      }
      .domain {
        font-weight: 500;
        font-size: 24px;
        color: ${MUTED_INK};
      }
    </style>
  </head>
  <body>
    <div class="wordmark">${wordmarkSvg}</div>
    <main>
      <h1>${card.heading}</h1>
      <p class="support">${card.support}</p>
    </main>
    <div class="domain">${card.domain}</div>
  </body>
</html>`
}

async function main(): Promise<void> {
  const wordmarkSvg = await readFile(
    resolve(REPO_ROOT, "docs/brand/assets/logo-wordmark.svg"),
    "utf8"
  )

  const browser = await chromium.launch()
  try {
    const context = await browser.newContext({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 1,
      colorScheme: "light",
    })
    const page = await context.newPage()

    for (const card of CARDS) {
      await page.setContent(cardHtml(wordmarkSvg, card), { waitUntil: "networkidle" })
      await page.evaluate(() => document.fonts.ready)
      const png = await page.screenshot({ type: "png", fullPage: false })
      await writeFile(card.out, png)
      console.log(`  [ok] ${card.slug} -> ${card.out} (${(png.byteLength / 1024).toFixed(0)} KB)`)
    }

    await context.close()
  } finally {
    await browser.close()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
