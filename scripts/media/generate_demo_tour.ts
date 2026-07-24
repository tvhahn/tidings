#!/usr/bin/env tsx
/**
 * Render the ~13.6s silent product-tour video for the launch (Reddit / Twitter /
 * README) from the built static-fixture demo. This is a FRAME-STEPPED capture —
 * NOT Playwright recordVideo / CDP screencast. Every frame is an individual
 * viewport screenshot: static beats capture once and file-copy the hold, scroll
 * beats compute an eased scroll offset per frame in Node and screenshot each.
 * The result is deterministic and re-renderable (the demo runs on a pinned
 * clock). ffmpeg then assembles the numbered PNGs into an mp4 + gif.
 *
 * Master timeline: 30 fps, frame_%04d.png in ONE directory, 408 frames total.
 *
 * The built demo serves marketing at / and the demo SPA under /demo/*, so every
 * capture URL carries the /demo prefix. The demo shell is a fixed app-shell
 * (Layout.tsx, staticDemo branch): the OUTER div is h-dvh overflow-hidden and
 * the scroller is <main class="flex-1 overflow-auto"> — the window never
 * scrolls, so scroll beats drive main.scrollTo, not window.scrollTo.
 *
 * This script does NOT boot the server. Point it at an already-serving build
 * (see `make demo-tour`, which builds + serves on a random free port):
 *
 *   cd frontend && pnpm demo:build
 *   cd frontend && pnpm exec serve dist -l 4180
 *   DEMO_TOUR_URL=http://localhost:4180 \
 *     pnpm exec tsx ../scripts/media/generate_demo_tour.ts
 */

import { execFile } from "node:child_process"
import { copyFile, mkdir, readdir, rm, stat } from "node:fs/promises"
import { createRequire } from "node:module"
import { tmpdir } from "node:os"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"

const execFileAsync = promisify(execFile)

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const REPO_ROOT = resolve(__dirname, "..", "..")
const OUT_DIR = resolve(REPO_ROOT, "docs/media")
const MP4_PATH = resolve(OUT_DIR, "demo-tour.mp4")
const GIF_PATH = resolve(OUT_DIR, "demo-tour.gif")
const GIF_720_PATH = resolve(OUT_DIR, "demo-tour-720.gif")

// Frames (and the gif palette temp) live OUTSIDE the repo — kept intact after
// the run for QC. Overridable for inspection: DEMO_TOUR_FRAMES_DIR=…
const FRAMES_DIR = resolve(process.env.DEMO_TOUR_FRAMES_DIR ?? resolve(tmpdir(), "tidings-demo-tour-frames"))
const PALETTE_PATH = resolve(FRAMES_DIR, "palette.png")

const BASE_URL = (process.env.DEMO_TOUR_URL ?? "http://localhost:4180") + "/demo"

const VIEWPORT = { width: 1440, height: 900 }
const SCALE = 2 // frames are 2880×1800
const FPS = 30
const GIF_SIZE_LIMIT = 12 * 1024 * 1024

// Injected after every goto: kills all animation/transition (the .month-transition
// mount fade in particular — reducedMotion alone does NOT suppress it, there is no
// prefers-reduced-motion reset in index.css) and hides scrollbars.
const KILL_SWITCH = `*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important } *::-webkit-scrollbar { display: none }`

// Resolve Playwright from frontend/ — the repo root has no node_modules.
const requireFrontend = createRequire(resolve(REPO_ROOT, "frontend/package.json"))
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { chromium } = requireFrontend("@playwright/test") as typeof import("@playwright/test")

type Page = import("@playwright/test").Page

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

function framePath(index: number): string {
  return resolve(FRAMES_DIR, `frame_${String(index).padStart(4, "0")}.png`)
}

/** Running frame counter — frames are contiguous across all beats. */
let frameIdx = 0

async function shoot(page: Page): Promise<string> {
  frameIdx++
  const p = framePath(frameIdx)
  await page.screenshot({ type: "png", path: p })
  return p
}

/** Fill the next `n` frames by copying an already-captured frame (holds never
 *  re-screenshot an unchanged view). */
async function holdFrames(n: number, sourcePath: string): Promise<void> {
  for (let i = 0; i < n; i++) {
    frameIdx++
    await copyFile(sourcePath, framePath(frameIdx))
  }
}

/** Instant scroll of the demo shell's <main> scroller, then wait two rAFs so the
 *  new scroll position has painted before the screenshot. */
async function setScroll(page: Page, y: number): Promise<void> {
  await page.evaluate((yy) => {
    document.querySelector("main")?.scrollTo(0, yy)
  }, y)
  await page.evaluate(
    () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())))
  )
}

async function waitLoadersGone(page: Page): Promise<void> {
  await page
    .waitForFunction(
      () => document.querySelectorAll(".animate-pulse, .animate-bounce").length === 0,
      undefined,
      { timeout: 8000 }
    )
    .catch(() => {})
}

function hideBanner(page: Page): Promise<void> {
  return page.evaluate(() => {
    const span = Array.from(document.querySelectorAll("span")).find(
      (s) => s.textContent?.trim() === "Demo mode"
    )
    const banner = span?.closest("div.border-b")
    if (banner instanceof HTMLElement) banner.style.display = "none"
  })
}

/** goto → kill-switch + scrollbar CSS → fonts.ready → loaders gone → per-beat
 *  waitFor → hide banner → 500ms settle → optional instant scroll offset. Runs
 *  in full BEFORE any frame is emitted for the beat. */
async function prepBeat(
  page: Page,
  path: string,
  waitFor: string | null,
  offsetY: number
): Promise<void> {
  await page.goto(`${BASE_URL}${path}`, { waitUntil: "networkidle" })
  await page.addStyleTag({ content: KILL_SWITCH })
  await page.evaluate(() => document.fonts.ready)
  await waitLoadersGone(page)
  if (waitFor) {
    await page.locator(waitFor).first().waitFor({ state: "visible", timeout: 15_000 })
  }
  await hideBanner(page)
  await page.waitForTimeout(500)
  await setScroll(page, offsetY)
}

/** A static beat: capture the (optionally offset) view once, copy the rest. */
async function staticBeat(
  page: Page,
  path: string,
  waitFor: string | null,
  offsetY: number,
  holdCount: number
): Promise<void> {
  await prepBeat(page, path, waitFor, offsetY)
  const first = await shoot(page)
  await holdFrames(holdCount - 1, first)
}

/** A hold → eased-scroll → hold beat. Scroll drives main from `fromY` to `toY`
 *  over `scrollCount` distinct, screenshotted frames (easeInOutCubic). */
async function scrollBeat(
  page: Page,
  path: string,
  waitFor: string | null,
  opts: {
    fromY: number
    toY: number
    holdStart: number
    scrollCount: number
    holdEnd: number
  }
): Promise<void> {
  await prepBeat(page, path, waitFor, opts.fromY)
  // Opening hold.
  const first = await shoot(page)
  await holdFrames(opts.holdStart - 1, first)
  // Eased scroll — each frame is a distinct screenshot.
  let last = first
  for (let k = 1; k <= opts.scrollCount; k++) {
    const progress = k / opts.scrollCount
    const y = opts.fromY + (opts.toY - opts.fromY) * easeInOutCubic(progress)
    await setScroll(page, y)
    last = await shoot(page)
  }
  // Closing hold on the final scroll frame.
  await holdFrames(opts.holdEnd, last)
}

async function ffprobeSize(path: string): Promise<number> {
  const s = await stat(path)
  return s.size
}

async function encodeMp4(): Promise<void> {
  console.log("Encoding mp4…")
  await execFileAsync("ffmpeg", [
    "-y",
    "-framerate",
    String(FPS),
    "-start_number",
    "1",
    "-i",
    resolve(FRAMES_DIR, "frame_%04d.png"),
    "-vf",
    "scale=1440:-2:flags=lanczos",
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "20",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    MP4_PATH,
  ])
}

async function encodeGif(width: number, out: string): Promise<void> {
  const filters = `fps=15,scale=${width}:-1:flags=lanczos`
  console.log(`Encoding gif (${width}w) — palette pass…`)
  await execFileAsync("ffmpeg", [
    "-y",
    "-framerate",
    String(FPS),
    "-start_number",
    "1",
    "-i",
    resolve(FRAMES_DIR, "frame_%04d.png"),
    "-vf",
    `${filters},palettegen=stats_mode=diff`,
    PALETTE_PATH,
  ])
  console.log(`Encoding gif (${width}w) — render pass…`)
  await execFileAsync("ffmpeg", [
    "-y",
    "-framerate",
    String(FPS),
    "-start_number",
    "1",
    "-i",
    resolve(FRAMES_DIR, "frame_%04d.png"),
    "-i",
    PALETTE_PATH,
    "-lavfi",
    `${filters} [x]; [x][1:v] paletteuse=dither=sierra2_4a:diff_mode=rectangle`,
    out,
  ])
  await rm(PALETTE_PATH, { force: true })
}

async function main(): Promise<void> {
  // Fresh frames each run (stale frames would corrupt the sequence); kept after.
  await rm(FRAMES_DIR, { recursive: true, force: true })
  await mkdir(FRAMES_DIR, { recursive: true })
  await mkdir(OUT_DIR, { recursive: true })

  console.log(`Capturing demo tour from ${BASE_URL}`)
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
    reducedMotion: "reduce",
  })
  // The FOWC inline script reads these before first paint (light + warm-paper,
  // tour dismissed) so every frame renders the out-of-box look.
  await context.addInitScript(() => {
    localStorage.setItem("theme", "light")
    localStorage.setItem("theme.palette", "warm-paper")
    localStorage.setItem("demo-tour:dismissed", "true")
  })
  const page = await context.newPage()

  try {
    // Beat 1 — Journal (February, full month). Scroller is <main>; land the
    // scroll on a day-card boundary (card top ≈ y1163 sits ~23px below the frame
    // top at y1140), covering ~2–3 day-cards. [24 + 78 + 18 = 120]
    await scrollBeat(page, "/?month=2026-02", ".month-transition", {
      fromY: 0,
      toY: 1140,
      holdStart: 24,
      scrollCount: 78,
      holdEnd: 18,
    })

    // Beat 2 — Summary, trend. Bar chart (isAnimationActive=false) sits fully
    // in the first viewport (top 311 / bottom 661), so no offset. [72]
    await staticBeat(page, "/summary?month=2026-02", ".recharts-surface", 0, 72)

    // Beat 3 — Summary, flow. The 520px sankey ends 20px below the fold; the
    // <main> inner has 24px top padding, so scrolling exactly 24 brings the
    // "Summary" title flush to the top AND fully reveals the sankey. [72]
    await staticBeat(page, "/summary?view=flow&month=2026-02", 'svg[height="520"] path', 24, 72)

    // Beat 4 — Budgets. Static hold at the top (loaders-gone gate covers the
    // skeleton → content swap). [48]
    await staticBeat(page, "/budgets", null, 0, 48)

    // Beat 5 — Insights (February briefing renders — .prose gates on it). Content
    // exceeds the viewport by 447px, so hold → eased scroll to the bottom →
    // hold. [30 + 45 + 21 = 96]
    await scrollBeat(page, "/insights?month=2026-02", ".prose", {
      fromY: 0,
      toY: 447,
      holdStart: 30,
      scrollCount: 45,
      holdEnd: 21,
    })
  } finally {
    await browser.close()
  }

  const frames = (await readdir(FRAMES_DIR)).filter((f) => f.endsWith(".png"))
  console.log(`\nCaptured ${frameIdx} frames (${frames.length} on disk) in ${FRAMES_DIR}`)
  if (frames.length !== frameIdx) {
    throw new Error(`Frame count mismatch: counter ${frameIdx} vs ${frames.length} on disk`)
  }

  await encodeMp4()
  await encodeGif(840, GIF_PATH)

  const mp4Bytes = await ffprobeSize(MP4_PATH)
  let gifBytes = await ffprobeSize(GIF_PATH)
  console.log(`\nmp4: ${(mp4Bytes / 1024 / 1024).toFixed(2)} MB -> ${MP4_PATH}`)
  console.log(`gif (840w): ${(gifBytes / 1024 / 1024).toFixed(2)} MB -> ${GIF_PATH}`)

  if (gifBytes > GIF_SIZE_LIMIT) {
    console.log(`gif exceeds ${GIF_SIZE_LIMIT / 1024 / 1024} MB — also rendering a 720w variant`)
    await encodeGif(720, GIF_720_PATH)
    const gif720Bytes = await ffprobeSize(GIF_720_PATH)
    console.log(`gif (720w): ${(gif720Bytes / 1024 / 1024).toFixed(2)} MB -> ${GIF_720_PATH}`)
  }

  console.log(`\nFrames kept for QC at: ${FRAMES_DIR}`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
