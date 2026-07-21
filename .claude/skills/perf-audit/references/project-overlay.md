# Project overlay — Tidings

The swappable per-repo layer. Everything in this file names a file, port, or house rule;
nothing in the core references does. **On a different repo:** if this file doesn't match the
project, bootstrap a fresh overlay per SKILL.md Phase 0 instead of "adapting" this one in
place.

**Overlay updated:** 2026-07-02 (post snappy-navigation ship).

## Surfaces & servers

Assume dev servers are already running — **never start them** (per repo `CLAUDE.md`).

| Surface | Port | Use in this audit |
|---|---|---|
| Real dashboard (Vite dev) | :5173 | primary audit target (pairs with API :8000) |
| Production preview | :4173 | confirmation runs — re-verify magnitudes here before trusting dev-build numbers |
| Static demo SPA | :5176 | only when auditing the demo |
| API (FastAPI) | :8000 | backend timing |

If a needed surface isn't up, ask the user to start it.

## Data-layer source of truth

- `frontend/src/lib/queryConfigs.ts` — ALL React Query keys, fetchers, staleTimes. Hooks in
  `frontend/src/hooks/` are thin wrappers over `queries.*` factories (ESLint-enforced).
- `frontend/src/lib/api.ts` — all HTTP calls. Any `fetch` outside these two files (and the
  allow-list below) is a convention violation *and* a race-condition surface (rule W4).

## Backend stack selection

FastAPI (Python, run via `uv run`) + dual storage: **DynamoDB** (production) / **SQLite**
(local/demo). Use the FastAPI/Python + SQLite/DynamoDB columns of
[`backend-checklist.md`](./backend-checklist.md); ignore the Node/Postgres columns here.

**Weighting rule (measured):** the backend is fast — 3–161 ms per endpoint (snappy-navigation
benchmark, 2026-07-01). Default the audit's depth to frontend render/interaction unless
TTFB/Server-Timing shows otherwise.

## Brand rules (§0, non-negotiable)

- The counter-move to slowness is **never** a spinner / skeleton / shimmer / animation /
  gradient / confetti. Remove the wait — don't decorate it. Loading states stay calm, honest,
  layout-stable. A metric lowered by adding a decorative distraction fails the audit.
- All copy suggestions must follow `docs/brand/voice.md` (no exclamations, sentence case).
- Skeletons only for >1 s cold first-loads (the existing first-load `Skeleton`s are fine —
  preserve-list). In-place refreshes hold real prior content (`keepPreviousData`).

## Preserve-list — already well-decided; do NOT re-fix or re-flag

Shipped and production-verified by `2026-07-01-snappy-navigation` (see its `IMPLEMENTATION_PLAN.md`
§ Implementation status) and `2026-04-20-dashboard-speedup`:

- **`content-visibility` utilities** `.cv-auto` / `.cv-auto-row` (`frontend/src/index.css:384-392`)
  applied at `DayCard.tsx:121` and `TransactionCard.tsx:189` — cut the month-nav style recalc
  **659 ms/4,984 el → 43 ms/427 el**. The single biggest shipped win; guard, don't touch.
- **Two-state month split** (`setDisplayMonth` urgent + URL month at transition priority) on
  `JournalPage.tsx` and `TransactionsPage.tsx` — header flips in ~14 ms.
- **React Router v7 auto-wraps navigations (including `setSearchParams`) in `startTransition`.**
  Do NOT prescribe manual `startTransition` around `setSearchParams`, and do NOT flag the
  absence of `useTransition` imports — `useDeferredValue` on the month is inert for the same
  reason (the value is already a transition value).
- **Adjacent-month prefetch**: `usePrefetchJournalMonth` (Journal), `usePrefetchMonth`
  (Transactions), MonthPicker hover/arrow prefetch (`MonthPicker.tsx`).
- **`placeholderData: keepPreviousData` + tiered `staleTime`** on month-scoped factories in
  `queryConfigs.ts` — present by design; the correct in-place-refresh pattern.
- **React Query v5 tracks accessed props by default** — `notifyOnChangeProps: 'tracked'` was
  removed from the library; do not recommend it (`main.tsx:36` comment).
- **RQ localStorage persistence** (`main.tsx`, 24 h) + `refetchOnWindowFocus`/`refetchOnReconnect`.
- **`React.memo` + stable handlers** on `DayCard` / `JournalTransactionRow` / `TransactionCard`.
- **One-layout-at-a-time rows + lazy-mounted hover action clusters** (snappy Phase 4) — at-rest
  DOM cut ~6.6k → ~2.1–2.5k nodes.
- **Route-level `React.lazy` on 21 routes**; `JournalPage` is eagerly imported **by design**
  (always-visible home).
- **`.month-transition` composited 150 ms fade** (`index.css`) — cheap, leave it.
- Backend: GZip on; `Cache-Control: stale-while-revalidate` on; DynamoDB reads are
  partition-scoped `Query` (no scans); trend fan-out already `asyncio.gather`-parallel;
  blocking I/O thread-offloaded (verify one example, don't re-audit all).

## Known-findings ledger — open items; report as "known, deferred", not discoveries

- **Virtualize the monthly Transactions table / Journal day list** — deliberately deferred
  until measurements demand (`TransactionTable.tsx` has an unused `virtualize` path; enabled
  only on Search). Variable-height DayCards prefer content-visibility.
- **View Transitions API** — cosmetic only; deferred until render cost is fixed.
- **React Compiler** — not enabled; the comment at `TransactionTable.tsx:369` claiming its
  skip is stale.
- Backend Tier 3 (all deferred; backend already fast):
  - 3–5× same-month `query_month` fan-out across `/journal`, `/summary`, `/summary/trend`,
    `/attention` (`spending_summary_base.py:53-58`) — short-TTL memo candidate.
  - `_TRANSACTION_LIST_PROJECTION` not applied on `/transactions`, `/transactions/attention`,
    `/transactions/trash` (`transactions.py`) — pulls full items incl. email bodies.
  - Small `asyncio.gather` opportunities (`journal.py`, `spending_summary_base.py:67-68`);
    Semaphore-bound trend fan-out (`summary.py:107`); `date_file_name`-leading SQLite index
    (`local_db.py:245-246`).

## Measured baselines (production preview, minified — re-measure, don't assume)

| Interaction | @1× CPU | @4× CPU | Captured |
|---|---|---|---|
| Journal month-nav: header flip | ~14 ms | ~25 ms | 2026-07-01/02 (snappy ship) |
| Journal month-nav: body settle | 108–146 ms | 450–550 ms | same |
| Transactions picker flip | ~75 ms | — | same |
| Biggest style recalc (month nav) | 43 ms / 427 el | — | same |
| At-rest DOM | ~2.1–2.5k nodes | — | same |
| API endpoints | 3–161 ms | n/a | 2026-07-01 |

A re-audit that measures materially worse than these has found a **regression** — say so
explicitly and diff against this table.

## Report destination

Save as `docs/specs/<YYYY-MM-DD>-perf-audit/README.md` (suffix the slug if the folder exists,
e.g. `-journal`), add **one** `Analysis` row to `docs/specs/INDEX.md` in date order. Those two
writes are the only writes a default audit makes.

## Book availability

`docs/reference/advanced-react/` is **present** — use the pointer map in
[`frontend-checklist.md`](./frontend-checklist.md) §6 and cite `NN_chXX-*.md § "<heading>"`.

## Scanner config

`scripts/perf-grep.mjs` parses the fenced block below (first ` ```json ` block after this
heading). Keep it valid JSON — no comments, no trailing commas.

```json
{
  "root": "frontend/src",
  "queryConfigsPath": "frontend/src/lib/queryConfigs.ts",
  "routesFile": "frontend/src/App.tsx",
  "pagesDir": "frontend/src/pages",
  "loadingFlagVocab": ["isFetching", "isPending", "isLoading", "isPlaceholderData", "isNavPending"],
  "rawFetchAllowlist": [
    "lib/api.ts",
    "lib/queryConfigs.ts",
    "lib/demoFetch.ts",
    "components/AuthBoundary.tsx"
  ],
  "dimAllowFiles": [],
  "monthParamHooks": ["useMonthParam"],
  "prefetchMarkers": ["usePrefetchMonth", "usePrefetchJournalMonth", "prefetchJournalMonth", "prefetchQuery"],
  "monthPrefetchExempt": [],
  "monthFactoryParamNames": ["month"],
  "keepPreviousDataExempt": [],
  "staleTimeExempt": [],
  "eagerRouteAllowlist": ["JournalPage"],
  "requiredPatterns": [
    { "id": "cv-utilities-defined", "file": "frontend/src/index.css", "pattern": "content-visibility:\\s*auto", "severity": "P0", "why": "cv-auto utilities are the shipped 659ms-to-43ms recalc fix" },
    { "id": "daycard-cv", "file": "frontend/src/components/DayCard.tsx", "pattern": "\\bcv-auto\\b", "severity": "P1", "why": "DayCard must keep content-visibility" },
    { "id": "transactioncard-cv", "file": "frontend/src/components/TransactionCard.tsx", "pattern": "cv-auto-row", "severity": "P1", "why": "TransactionCard must keep content-visibility" },
    { "id": "journal-instant-ack", "file": "frontend/src/pages/JournalPage.tsx", "pattern": "setDisplayMonth", "severity": "P1", "why": "two-state split: urgent header flip" },
    { "id": "transactions-instant-ack", "file": "frontend/src/pages/TransactionsPage.tsx", "pattern": "setDisplayMonth", "severity": "P1", "why": "two-state split: urgent header flip" },
    { "id": "journal-prefetch", "file": "frontend/src/pages/JournalPage.tsx", "pattern": "usePrefetchJournalMonth", "severity": "P1", "why": "adjacent-month prefetch (0 cold fetches)" },
    { "id": "transactions-prefetch", "file": "frontend/src/pages/TransactionsPage.tsx", "pattern": "usePrefetchMonth", "severity": "P1", "why": "adjacent-month prefetch" }
  ],
  "maxPerRule": 20
}
```

Config-key meanings: `requiredPatterns` are **regression guards** — the pattern must be
present in the file or the scanner emits a finding at the given severity (this is how the
shipped snappy-navigation fixes stay shipped). `*Exempt`/`*Allowlist`/`dimAllowFiles` entries
suppress a rule for named paths — add a path only after a human judges the hit intentional,
and note why in this file next to the entry.
