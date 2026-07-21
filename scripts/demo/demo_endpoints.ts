/**
 * Canonical list of read-only API endpoints to snapshot for the static demo.
 *
 * Each entry maps a backend URL (relative to /api/v1) to a fixture slug served
 * from frontend/public/demo-data/<slug>.json. The generator iterates this list; to
 * add a new demo endpoint, append one entry.
 */

export interface EndpointSpec {
  slug: string
  url: string
  ai?: boolean
  optional?: boolean
}

export const DEMO_MONTHS = [
  "2025-05",
  "2025-06",
  "2025-07",
  "2025-08",
  "2025-09",
  "2025-10",
  "2025-11",
  "2025-12",
  "2026-01",
  "2026-02",
  "2026-03",
] as const
export const DEMO_YEAR = 2026

function monthEndpoints(slug: string, url: (m: string) => string, opts: { optional?: boolean; ai?: boolean } = {}): EndpointSpec[] {
  return DEMO_MONTHS.map((m) => ({ slug: `${slug}-${m}`, url: url(m), ...opts }))
}

export const ENDPOINTS: EndpointSpec[] = [
  { slug: "config", url: "/config" },
  { slug: "categories", url: "/categories" },
  { slug: "categories-managed", url: "/categories/managed" },
  { slug: "category-icons", url: "/categories/icons", optional: true },
  { slug: "overrides", url: "/overrides" },
  { slug: "overrides-suggestions", url: "/overrides/suggestions", optional: true },
  { slug: "overrides-duplicates", url: "/overrides/duplicates", optional: true },
  { slug: "merchant-aliases", url: "/merchant-aliases" },
  { slug: `groups-${DEMO_YEAR}`, url: `/groups?year=${DEMO_YEAR}` },
  { slug: `budget-config-${DEMO_YEAR}`, url: `/budget/config?year=${DEMO_YEAR}`, optional: true },
  { slug: `budget-status-${DEMO_YEAR}`, url: `/budget/status?year=${DEMO_YEAR}` },
  { slug: "budget-historical", url: "/budget/historical-averages", optional: true },
  { slug: `income-statement-${DEMO_YEAR}`, url: `/income-statement?year=${DEMO_YEAR}` },
  { slug: `tax-pack-${DEMO_YEAR}`, url: `/tax-pack?year=${DEMO_YEAR}` },
  { slug: "summary-trend", url: `/summary/trend?months=6&end_month=2026-03` },
  { slug: "coverage", url: "/coverage" },
  { slug: "statements", url: "/statements", optional: true },
  // The "Needs review" queue. The committed parse-failures.json is hand-authored
  // (PII-free, persona-consistent, with email bodies the live summary endpoint
  // never returns); `optional` keeps regeneration from hard-failing on a clean
  // demo DB. Note: a regen against a live backend would overwrite it with the
  // body-less summary list — re-author by hand if that happens.
  { slug: "parse-failures", url: "/parse-failures", optional: true },

  ...monthEndpoints("transactions", (m) => `/transactions?month=${m}`),
  ...monthEndpoints("all", (m) => `/transactions/all?month=${m}`),
  ...monthEndpoints("attention", (m) => `/transactions/attention?month=${m}`, { optional: true }),
  ...monthEndpoints("trash", (m) => `/transactions/trash?month=${m}`, { optional: true }),
  ...monthEndpoints("summary", (m) => `/summary?month=${m}`),
  ...monthEndpoints("journal", (m) => `/journal?month=${m}`),
  ...monthEndpoints("journal-summaries", (m) => `/journal/summaries?month=${m}`, { optional: true, ai: true }),
  ...monthEndpoints("insights-saved", (m) => `/insights/saved?month=${m}`, { optional: true, ai: true }),
]
