#!/usr/bin/env tsx
/**
 * Generate the three 1200×630 social/OG cards:
 *
 *   - frontend/public/og-image.png            — marketing landing (gettidings.com)
 *   - frontend/public/demo-data/og-image.png  — demo SPA (gettidings.com/demo)
 *   - docs-site/public/og-image.png           — docs (docs.gettidings.com)
 *
 * The DEMO and DOCS cards share one flat, typographic template (spec:
 * docs/specs/00_open-source-migration/2026-07-05-web-surfaces-launch/):
 * warm-paper ground, left-aligned type, no gradients/shadows/ornament
 * (docs/brand/visual.md). Their wordmark lockup is inlined from
 * docs/brand/assets/logo-wordmark.svg (outlined to paths) and headings load
 * Source Serif 4 / Inter from Google Fonts with serif/sans fallbacks.
 *
 * The MARKETING card is the illustrated hero (approved 2026-07-21 design;
 * typography/logo aligned to the live marketing page later the same day):
 * a full-bleed editorial photograph (a linen notebook + potted olive sapling
 * on a wooden desk) under a left→right warm-ivory scrim, with the real
 * favicon mark + serif wordmark (mirroring .nav-brand), the serif
 * "Your spending, delivered." headline (mirroring .h1 in marketing.css),
 * an Inter subtitle, and the monospaced domain. Its only binary source is the
 * checked-in scripts/media/assets/og-desk-olive-notebook.webp (q90, 1536×1024);
 * fonts are embedded from @fontsource — the same opsz-axis Source Serif 4
 * Variable files frontend/src/index.css imports, so the headline gets the
 * identical display optical cut the site renders — and document.fonts
 * assertions guard against a fallback.
 * It is rendered at deviceScaleFactor 2 (supersample) and downscaled +
 * 256-color-quantized with ImageMagick (`convert`, available in the dev
 * environment) to keep the file well under the OG size budget.
 *
 * The committed PNGs are the artifact; this script is the reproducible
 * regen path. Regenerate:
 *   cd frontend && pnpm og:images
 */

import { execFile } from "node:child_process"
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import { createRequire } from "node:module"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"

const execFileAsync = promisify(execFile)

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const REPO_ROOT = resolve(__dirname, "..", "..")

// Resolve Playwright from frontend/ — the repo root has no node_modules.
const requireFrontend = createRequire(resolve(REPO_ROOT, "frontend/package.json"))
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { chromium } = requireFrontend("@playwright/test") as typeof import("@playwright/test")

const WIDTH = 1200
const HEIGHT = 630

// ── Flat template (demo + docs cards) ─────────────────────────────────────

// Same font set the dashboard and marketing page load (frontend/index.html).
const FONT_STYLESHEET =
  "https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"

// Warm-paper palette (frontend/src/styles/themes.css).
const PAPER = "oklch(0.975 0.006 75)" // --popover / --muted
const INK = "oklch(0.18 0.025 55)" // --foreground
const MUTED_INK = "oklch(0.45 0.022 58)" // --fg-secondary

type FlatCard = {
  slug: string
  /** Heading HTML — <em> marks the marketing-typography italic exception. */
  heading: string
  support: string
  domain: string
  out: string
}

const FLAT_CARDS: FlatCard[] = [
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

function flatCardHtml(wordmarkSvg: string, card: FlatCard): string {
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

// ── Illustrated marketing card (approved 2026-07-21 design) ────────────────
//
// Every constant below is the approved recipe. Origin: the sign-off card at
// og-candidate/card.html + shoot.mjs (regular-spacing variant), with the
// type/logo constants re-anchored to the live site the same day (maintainer
// direction): headline mirrors `.marketing .h1`, wordmark mirrors
// `.marketing .nav-brand`, the mark is frontend/public/favicon.svg verbatim,
// and the accent is the light-theme `--brand` token. Do not tune these
// without a new design sign-off.

const MARKETING_OUT = resolve(REPO_ROOT, "frontend/public/og-image.png")
const MARKETING_PHOTO = resolve(REPO_ROOT, "scripts/media/assets/og-desk-olive-notebook.webp")
const MARKETING_MARK = resolve(REPO_ROOT, "frontend/public/favicon.svg")

// Photograph placement: source is 1536×1024; a 1536×804 window at top offset
// 132 scales to 1200×630 (scale 0.78125). Implemented as a 1200×800 cover
// image shifted up 103.125px (the same framing card.html used).
const PHOTO_RENDER_W = 1200
const PHOTO_RENDER_H = 800
const PHOTO_SHIFT_UP = 103.125

// Warm-ivory (#fbf8f1) left→right scrim protecting the text zone.
const IVORY_RGB = "251, 248, 241"

// Terracotta brand accent + ink hierarchy (oklch).
const BRAND = "oklch(0.58 0.15 40)" // --brand, light theme (themes.css) — italic headline word
const M_INK = "oklch(0.24 0.02 55)"
const M_SUB = "oklch(0.40 0.02 55)"
const M_URL = "oklch(0.46 0.03 45)"

// Supersample factor: render at DPR 2, then Lanczos-downscale + quantize.
const MARKETING_DSF = 2

// @fontsource woff2 faces the render must embed (data URIs) + document.fonts
// assertions so a missing face fails loudly instead of falling back.
const MARKETING_FONTS = [
  // The opsz-axis files — the exact faces frontend/src/index.css imports
  // (opsz.css / opsz-italic.css). The wght-only files render the headline at
  // the text optical size, visibly heavier than the site at display sizes.
  {
    family: "Source Serif 4 Variable",
    weight: "200 900",
    style: "normal",
    file: "@fontsource-variable/source-serif-4/files/source-serif-4-latin-opsz-normal.woff2",
  },
  {
    family: "Source Serif 4 Variable",
    weight: "200 900",
    style: "italic",
    file: "@fontsource-variable/source-serif-4/files/source-serif-4-latin-opsz-italic.woff2",
  },
  {
    family: "Inter",
    weight: "400",
    style: "normal",
    file: "@fontsource/inter/files/inter-latin-400-normal.woff2",
  },
  {
    family: "Inter",
    weight: "500",
    style: "normal",
    file: "@fontsource/inter/files/inter-latin-500-normal.woff2",
  },
  {
    family: "JetBrains Mono",
    weight: "500",
    style: "normal",
    file: "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2",
  },
] as const

// Font faces the render asserts are loaded (no fallback): [CSS font shorthand, sample glyphs].
const MARKETING_FONT_CHECKS: [string, string][] = [
  ['600 30px "Source Serif 4 Variable"', "Tidings"],
  ['500 66px "Source Serif 4 Variable"', "spending"],
  ['italic 500 66px "Source Serif 4 Variable"', "delivered"],
  ['400 27px "Inter"', "journal"],
  ['500 20px "JetBrains Mono"', "gettidings"],
]

async function dataUri(path: string, mime: string): Promise<string> {
  const buf = await readFile(path)
  return `data:${mime};base64,${buf.toString("base64")}`
}

async function marketingCardHtml(): Promise<string> {
  const nodeModules = resolve(REPO_ROOT, "frontend/node_modules")
  const fontFaces = (
    await Promise.all(
      MARKETING_FONTS.map(async (f) => {
        const uri = await dataUri(join(nodeModules, f.file), "font/woff2")
        return `@font-face {
  font-family: "${f.family}"; font-weight: ${f.weight}; font-style: ${f.style};
  font-display: block; src: url("${uri}") format("woff2");
}`
      })
    )
  ).join("\n")
  const photoUri = await dataUri(MARKETING_PHOTO, "image/webp")
  const markSvg = await readFile(MARKETING_MARK, "utf8")

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<style>
  ${fontFaces}
  :root {
    --brand: ${BRAND};
    --ink:   ${M_INK};
    --sub:   ${M_SUB};
    --url:   ${M_URL};
    --serif: "Source Serif 4 Variable", "Source Serif 4", Georgia, serif;
    --sans:  "Inter", system-ui, sans-serif;
    --mono:  "JetBrains Mono", ui-monospace, monospace;
    --ivory: ${IVORY_RGB};
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: ${WIDTH}px; height: ${HEIGHT}px; }
  body { -webkit-font-smoothing: antialiased; text-rendering: geometricPrecision; }
  .stage {
    position: relative;
    width: ${WIDTH}px; height: ${HEIGHT}px;
    overflow: hidden;
    background: #efe9df;
  }
  .photo {
    position: absolute; z-index: 0;
    left: 0; top: -${PHOTO_SHIFT_UP}px;
    width: ${PHOTO_RENDER_W}px; height: ${PHOTO_RENDER_H}px;
    object-fit: cover; display: block;
  }
  .scrim {
    position: absolute; inset: 0; z-index: 1; pointer-events: none;
    background: linear-gradient(to right,
      rgba(var(--ivory), 0.94) 0%,
      rgba(var(--ivory), 0.86) 30%,
      rgba(var(--ivory), 0.46) 52%,
      rgba(var(--ivory), 0.00) 74%);
  }
  .copy {
    position: absolute; z-index: 2;
    left: 0; top: 0; bottom: 0;
    display: flex; flex-direction: column;
    padding: 62px 80px;
    width: 720px;
  }
  /* Mirrors .marketing .nav-brand (serif 600, -0.01em, icon:text ≈ 1.3). */
  .wm {
    display: flex; align-items: center; gap: 11px;
    font-family: var(--serif); font-weight: 600;
    font-size: 30px; letter-spacing: -0.01em; color: var(--ink);
  }
  /* favicon.svg viewBox is 417×320 — 39×30 keeps its aspect ratio. */
  .wm svg { width: 39px; height: 30px; display: block; }
  .mid { margin-top: auto; margin-bottom: auto; }
  /* Mirrors .marketing .h1 (weight 500, 1.02, -0.025em). */
  h1 {
    font-family: var(--serif); font-weight: 500;
    font-size: 66px; line-height: 1.02; letter-spacing: -0.025em;
    color: var(--ink);
  }
  h1 em { font-style: italic; font-weight: 500; color: var(--brand); }
  .sub {
    margin-top: 22px;
    font-family: var(--sans); font-weight: 400;
    font-size: 27px; line-height: 1.42; letter-spacing: -0.005em;
    color: var(--sub); max-width: 540px;
  }
  .url {
    font-family: var(--mono); font-weight: 500;
    font-size: 20px; letter-spacing: 0.06em; color: var(--url);
  }
</style>
</head>
<body>
  <div class="stage">
    <img class="photo" src="${photoUri}" alt="" />
    <div class="scrim"></div>
    <div class="copy">
      <span class="wm">
        ${markSvg.trim()}
        Tidings
      </span>
      <div class="mid">
        <h1>Your spending, <em>delivered.</em></h1>
        <p class="sub">A private finance journal from the transaction emails you already receive.</p>
      </div>
      <span class="url">gettidings.com</span>
    </div>
  </div>
</body>
</html>`
}

/**
 * Downscale a DPR-2 supersample to 1200×630 and reduce to a 256-color palette
 * with Floyd–Steinberg dithering. Uses ImageMagick's `convert` (available in
 * the dev environment) — the same steps the approved shoot.mjs recipe used to
 * land the card at ~330 KB.
 */
async function downscaleAndQuantize(supersample: Buffer, outPath: string): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), "og-marketing-"))
  const src = join(dir, "supersample.png")
  try {
    await writeFile(src, supersample)
    await execFileAsync("convert", [
      src,
      "-filter",
      "Lanczos",
      "-resize",
      `${WIDTH}x${HEIGHT}`,
      "-dither",
      "FloydSteinberg",
      "-colors",
      "256",
      "-strip",
      outPath,
    ])
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

async function renderMarketingCard(browser: import("@playwright/test").Browser): Promise<void> {
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: MARKETING_DSF,
    colorScheme: "light",
  })
  try {
    const page = await context.newPage()
    await page.setContent(await marketingCardHtml(), { waitUntil: "networkidle" })
    await page.evaluate(() => document.fonts.ready)

    const fontsOk = await page.evaluate((checks) => {
      return checks.every(([font, sample]) => document.fonts.check(font, sample))
    }, MARKETING_FONT_CHECKS)
    if (!fontsOk) {
      throw new Error("Marketing card font check failed — a face did not load (fallback risk).")
    }

    // Settle two frames so webfont metrics + the photo are painted before capture.
    await page.evaluate(
      () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
    )

    const supersample = await page.screenshot({
      type: "png",
      clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT },
    })
    await downscaleAndQuantize(supersample, MARKETING_OUT)
    const { size } = await readFile(MARKETING_OUT).then((b) => ({ size: b.byteLength }))
    console.log(`  [ok] marketing -> ${MARKETING_OUT} (${(size / 1024).toFixed(0)} KB)`)
  } finally {
    await context.close()
  }
}

async function main(): Promise<void> {
  const wordmarkSvg = await readFile(
    resolve(REPO_ROOT, "docs/brand/assets/logo-wordmark.svg"),
    "utf8"
  )

  const browser = await chromium.launch()
  try {
    // Illustrated marketing card (its own DPR-2 context + ImageMagick post).
    await renderMarketingCard(browser)

    // Flat demo + docs cards (shared DPR-1 template).
    const context = await browser.newContext({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 1,
      colorScheme: "light",
    })
    const page = await context.newPage()

    for (const card of FLAT_CARDS) {
      await page.setContent(flatCardHtml(wordmarkSvg, card), { waitUntil: "networkidle" })
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
