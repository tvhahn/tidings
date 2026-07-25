#!/usr/bin/env tsx
/**
 * Render the ~15.1s silent product-tour video for the launch (Reddit / Twitter /
 * README) from the built static-fixture demo. This is a FRAME-STEPPED capture —
 * NOT Playwright recordVideo / CDP screencast. Every frame is an individual
 * viewport screenshot: static beats capture once and file-copy the hold, scroll
 * beats compute an eased scroll offset per frame in Node and screenshot each.
 * The result is deterministic and re-renderable (the demo runs on a pinned
 * clock). ffmpeg then assembles the numbered PNGs into an mp4 + gif.
 *
 * Master timeline: 30 fps, frame_%04d.png in ONE directory, 453 frames total.
 *
 * A SYNTHETIC MOUSE CURSOR (a DOM overlay, not page.mouse) rides on top of the
 * capture: it is parked from frame 1, eases across to the sidebar nav button for
 * the next page, pulses a click ring, and then the beat hard-cuts. Navigation
 * itself stays `page.goto` — no frames are emitted between the pulse and the
 * next beat's first settled frame, so a cosmetic click + hard cut is
 * pixel-identical to a real click, WITHOUT the two costs of real clicking:
 * real pointer movement would trip Recharts tooltips / hover states, and a real
 * nav click would drop `?month=2026-02` (the demo clock is pinned to 2026-03, so
 * a bare /summary shows a partial March). The beat URLs are authoritative.
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

/** Wait two rAFs so a just-applied style/scroll mutation has painted. */
function settleTwoFrames(page: Page): Promise<void> {
  return page.evaluate(
    () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())))
  )
}

/** Instant scroll of the demo shell's <main> scroller, then wait two rAFs so the
 *  new scroll position has painted before the screenshot. */
async function setScroll(page: Page, y: number): Promise<void> {
  await page.evaluate((yy) => {
    document.querySelector("main")?.scrollTo(0, yy)
  }, y)
  await settleTwoFrames(page)
}

// ---------------------------------------------------------------------------
// Synthetic cursor overlay
// ---------------------------------------------------------------------------

const CURSOR_ID = "demo-tour-cursor"
const CURSOR_ARROW_ID = "demo-tour-cursor-arrow"
const CURSOR_RING_ID = "demo-tour-cursor-ring"

/** Frames per nav move (0.7s) and per click pulse (~0.27s). */
const MOVE_FRAMES = 21
const PULSE_FRAMES = 8

/** Where the cursor is parked at frame 1 — over the journal content, out of the
 *  way of every captured surface. */
const CURSOR_PARK = { x: 1180, y: 600 }

/** Authoritative cursor position, in CSS px, owned by Node. Every goto wipes the
 *  DOM, so prepBeat re-injects the overlay at these coordinates. */
let cursorX = CURSOR_PARK.x
let cursorY = CURSOR_PARK.y

/** Inject (or re-position, if already present) the cursor overlay. Idempotent —
 *  safe to call after every goto. All styling is inline: the kill-switch nukes
 *  animations/transitions, so every bit of motion is Node-stepped per frame.
 *  The arrow tip is the viewBox origin and the SVG has overflow:visible, so the
 *  hotspot is exactly the overlay div's top-left corner. */
async function installCursor(page: Page): Promise<void> {
  await page.evaluate(
    ({ id, arrowId, x, y }) => {
      let root = document.getElementById(id)
      if (!root) {
        root = document.createElement("div")
        root.id = id
        root.style.cssText =
          "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none"
        // macOS-style arrow: dark fill, white outline, soft drop shadow.
        root.innerHTML = `<svg id="${arrowId}" width="15.16" height="24" viewBox="0 0 12 19" style="display:block;overflow:visible;transform-origin:0 0;transform:scale(1);filter:drop-shadow(0 1px 2px rgba(0,0,0,0.35))"><path d="M0 0 L0 16.6 L4.2 12.7 L6.6 18.4 L9.1 17.3 L6.8 11.8 L11.4 11.5 Z" fill="#1c1a17" stroke="#ffffff" stroke-width="1.1" stroke-linejoin="round"/></svg>`
        document.body.appendChild(root)
      }
      root.style.left = `${x}px`
      root.style.top = `${y}px`
    },
    { id: CURSOR_ID, arrowId: CURSOR_ARROW_ID, x: cursorX, y: cursorY }
  )
}

async function setCursorPos(page: Page, x: number, y: number): Promise<void> {
  cursorX = x
  cursorY = y
  await page.evaluate(
    ({ id, xx, yy }) => {
      const el = document.getElementById(id)
      if (el) {
        el.style.left = `${xx}px`
        el.style.top = `${yy}px`
      }
    },
    { id: CURSOR_ID, xx: x, yy: y }
  )
  await settleTwoFrames(page)
}

/** Ease the cursor from its current position to (x, y) over `frames` distinct,
 *  screenshotted frames (holds may be file-copies; motion never is). */
async function moveCursorTo(page: Page, x: number, y: number, frames: number): Promise<void> {
  const fromX = cursorX
  const fromY = cursorY
  for (let k = 1; k <= frames; k++) {
    const p = easeInOutCubic(k / frames)
    await setCursorPos(page, fromX + (x - fromX) * p, fromY + (y - fromY) * p)
    await shoot(page)
  }
}

/** Expanding ring centred on the cursor hotspot (4px → 28px radius, 0.5 → 0
 *  opacity), plus a 2-frame arrow squeeze to sell the press. Stepped from Node —
 *  a CSS animation would be dead under the kill-switch. */
async function clickPulse(page: Page, frames: number): Promise<void> {
  for (let k = 1; k <= frames; k++) {
    const t = k / frames
    const grow = 1 - (1 - t) * (1 - t) // easeOutQuad — quick pop, soft finish
    await page.evaluate(
      ({ rootId, ringId, arrowId, radius, opacity, scale }) => {
        const root = document.getElementById(rootId)
        if (!root) return
        let ring = document.getElementById(ringId)
        if (!ring) {
          ring = document.createElement("div")
          ring.id = ringId
          ring.style.cssText =
            "position:absolute;box-sizing:border-box;border-radius:9999px;border:2px solid #1c1a17"
          root.insertBefore(ring, root.firstChild)
        }
        ring.style.left = `${-radius}px`
        ring.style.top = `${-radius}px`
        ring.style.width = `${radius * 2}px`
        ring.style.height = `${radius * 2}px`
        ring.style.opacity = String(opacity)
        const arrow = document.getElementById(arrowId)
        if (arrow) arrow.style.transform = `scale(${scale})`
      },
      {
        rootId: CURSOR_ID,
        ringId: CURSOR_RING_ID,
        arrowId: CURSOR_ARROW_ID,
        radius: 4 + 24 * grow,
        opacity: 0.5 * (1 - t),
        scale: k <= 2 ? 0.9 : 1,
      }
    )
    await settleTwoFrames(page)
    await shoot(page)
  }
  // Tear the ring down and un-squeeze the arrow; the next beat hard-cuts.
  await page.evaluate(
    ({ ringId, arrowId }) => {
      document.getElementById(ringId)?.remove()
      const arrow = document.getElementById(arrowId)
      if (arrow) arrow.style.transform = "scale(1)"
    },
    { ringId: CURSOR_RING_ID, arrowId: CURSOR_ARROW_ID }
  )
}

/** Viewport centre of a sidebar nav button, resolved at runtime — never
 *  hardcoded. Scoped to `aside nav` because the mobile tab bar and the sidebar
 *  stats panel carry buttons with the same accessible names. */
async function navButtonCenter(page: Page, label: string): Promise<{ x: number; y: number }> {
  const button = page.locator("aside nav").getByRole("button", { name: label, exact: true })
  const count = await button.count()
  if (count !== 1) {
    throw new Error(`Sidebar nav button "${label}" matched ${count} elements (expected exactly 1)`)
  }
  const box = await button.boundingBox()
  if (!box) throw new Error(`Sidebar nav button "${label}" has no bounding box`)
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}

/** One transition: ease to a nav button, pulse a click. The caller's next
 *  prepBeat is the hard cut — emit nothing in between. [MOVE + PULSE frames] */
async function clickNav(page: Page, label: string): Promise<void> {
  const { x, y } = await navButtonCenter(page, label)
  await moveCursorTo(page, x, y, MOVE_FRAMES)
  await clickPulse(page, PULSE_FRAMES)
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

/** goto → kill-switch + scrollbar CSS → re-inject cursor → fonts.ready →
 *  loaders gone → per-beat waitFor → hide banner → 500ms settle → optional
 *  instant scroll offset. Runs in full BEFORE any frame is emitted for the
 *  beat. */
async function prepBeat(
  page: Page,
  path: string,
  waitFor: string | null,
  offsetY: number
): Promise<void> {
  await page.goto(`${BASE_URL}${path}`, { waitUntil: "networkidle" })
  await page.addStyleTag({ content: KILL_SWITCH })
  // The goto wiped the DOM — put the cursor back where Node last left it.
  await installCursor(page)
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
    // top at y1140), covering ~2–3 day-cards. The cursor sits parked at
    // CURSOR_PARK throughout. The terminal hold is trimmed 18 → 4 because the
    // cursor move that follows now carries the beat's tail. [24 + 78 + 4 = 106]
    await scrollBeat(page, "/?month=2026-02", ".month-transition", {
      fromY: 0,
      toY: 1140,
      holdStart: 24,
      scrollCount: 78,
      holdEnd: 4,
    })
    // Journal → Summary. [21 + 8 = 29]
    await clickNav(page, "Summary")

    // Beat 2 — Summary, trend. Bar chart (isAnimationActive=false) sits fully
    // in the first viewport (top 311 / bottom 661), so no offset. The cursor
    // rests on the (now active) Summary nav button. [72]
    await staticBeat(page, "/summary?month=2026-02", ".recharts-surface", 0, 72)

    // Beat 3 — Summary, flow. The 520px sankey ends 20px below the fold; the
    // <main> inner has 24px top padding, so scrolling exactly 24 brings the
    // "Summary" title flush to the top AND fully reveals the sankey. Trend →
    // flow is deliberately a bare hard cut with NO cursor move: the view toggle
    // is not a nav click, and Summary stays the active nav item on both. Hold
    // trimmed 72 → 58 to pay for the transition that follows. [58]
    await staticBeat(page, "/summary?view=flow&month=2026-02", 'svg[height="520"] path', 24, 58)
    // Summary → Budgets. [21 + 8 = 29]
    await clickNav(page, "Budgets")

    // Beat 4 — Budgets. Static hold at the top (loaders-gone gate covers the
    // skeleton → content swap). Hold trimmed 48 → 34. [34]
    await staticBeat(page, "/budgets", null, 0, 34)
    // Budgets → Insights. [21 + 8 = 29]
    await clickNav(page, "Insights")

    // Beat 5 — Insights (February briefing renders — .prose gates on it). Content
    // exceeds the viewport by 447px, so hold → eased scroll to the bottom →
    // hold. The cursor stays parked on the Insights nav button — the sidebar
    // does not scroll with <main>. [30 + 45 + 21 = 96]
    await scrollBeat(page, "/insights?month=2026-02", ".prose", {
      fromY: 0,
      toY: 447,
      holdStart: 30,
      scrollCount: 45,
      holdEnd: 21,
    })
    // Total: 106 + 29 + 72 + 58 + 29 + 34 + 29 + 96 = 453 frames ≈ 15.1s.
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
