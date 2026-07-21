/**
 * Screenshot targets for the "Using Tidings" docs section.
 *
 * Each entry names a page of the static-fixture demo SPA (served under the
 * /demo prefix — see frontend/public/serve.json). The generator
 * (generate_docs_screenshots.ts) captures a light + dark WebP pair per entry
 * and writes them to docs-site/src/assets/screenshots/<id>-<theme>.webp.
 *
 * `waitFor` is an optional Playwright selector the generator waits for
 * (visible) before capturing — a positive "data has rendered" signal for
 * pages that fetch async. The generator ALSO waits generically for loading
 * skeletons (.animate-pulse) and dot-loaders (.animate-bounce) to clear, so
 * omitting `waitFor` still avoids a mid-load capture; it is added only where a
 * stable, page-specific marker sharpens that guarantee.
 */

export type DocsShotViewport = "desktop" | "mobile"

export type DocsShot = {
  /** Output basename: <id>-light.webp / <id>-dark.webp. */
  id: string
  /** Path under the served site, including the /demo prefix. */
  path: string
  viewport: DocsShotViewport
  /** Optional Playwright selector waited for (visible) before capture. */
  waitFor?: string
}

export const DOCS_SHOTS: DocsShot[] = [
  { id: "journal", path: "/demo/", viewport: "desktop" },
  { id: "journal-mobile", path: "/demo/", viewport: "mobile" },
  { id: "transactions", path: "/demo/transactions", viewport: "desktop" },
  { id: "categorize", path: "/demo/categorize", viewport: "desktop" },
  { id: "needs-review", path: "/demo/needs-review", viewport: "desktop" },
  // Recharts bar chart — wait for its rendered SVG surface, not the nav's
  // lucide icons (which are <svg> present from first paint).
  { id: "summary-trend", path: "/demo/summary?view=trend", viewport: "desktop", waitFor: ".recharts-surface" },
  { id: "summary-flow", path: "/demo/summary?view=flow", viewport: "desktop" },
  { id: "budgets", path: "/demo/budgets", viewport: "desktop" },
  { id: "budget-edit", path: "/demo/budgets/edit", viewport: "desktop" },
  // Saved briefing renders markdown; the demo month (2026-03) ships one whose
  // first section is "## Headline".
  { id: "insights", path: "/demo/insights", viewport: "desktop", waitFor: "text=Headline" },
  // Merchant intelligence shows a dot-loader while reading six months; the
  // "Committed" summary card only appears once data lands.
  { id: "merchants", path: "/demo/merchants", viewport: "desktop", waitFor: "text=Committed" },
  { id: "income-statement", path: "/demo/income-statement", viewport: "desktop" },
  { id: "tax", path: "/demo/tax", viewport: "desktop" },
  { id: "settings-display", path: "/demo/settings/display", viewport: "desktop" },
  // The demo ledger is an inline slice attributed to the kitchen-agent token;
  // its label is the stable "entries have rendered" marker.
  { id: "settings-activity", path: "/demo/settings/activity", viewport: "desktop", waitFor: "text=kitchen-agent" },
]
