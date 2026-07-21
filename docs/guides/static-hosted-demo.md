# Static Hosted Demo Guide

Operational guide for the dual-surface static bundle: a marketing
landing at `/` and the zero-backend demo SPA at `/demo/*`. Both are
produced by a single `pnpm demo:build`; the same `dist/` can sit
behind any static host (Cloudflare Pages, Netlify, S3 + CloudFront,
plain Nginx). Pairs with the
[implementation spec](../specs/00_open-source-migration/2026-04-16-static-demo-deployment/SPEC.md) (local-only, absent in the public repo).

## What it is

Two Vite entry points compiled into one bundle:

- **`/` (marketing)** — `frontend/index.html` + `frontend/src/main-marketing.tsx`
  + `frontend/src/marketing/`. A small bundle (no Recharts/Radix/React Query)
  with the nine landing-page sections ported from the design-system
  marketing UI kit. Links into the demo with full-page anchors so the
  demo SPA bundle only loads on the `/demo/*` boundary.
- **`/demo/*` (demo SPA)** — `frontend/demo/index.html` + the existing
  React Router app, mounted with `<BrowserRouter basename="/demo">`.
  `@/lib/api` is swapped at bundle time for `@/lib/demoApi`. All read
  calls load JSON fixtures from `frontend/public/demo-data/*.json`;
  category edits and budget envelope edits go through a sessionStorage
  overlay; every other mutating surface is hidden or replaced with a
  "Configure locally" callout.

The dataset belongs to the **Mira Lin Chen** persona
(`docs/specs/_archive/2026-05-10-demo-parity/persona.md`, local-only), covers
**May 2025 → March 2026**, and is anchored to demo-today
**2026-03-19** — the last day with transaction data, so the landing
month reads as in progress. The world contains no dates after that
day (enforced by `scripts/demo/check_demo_fixtures.py` in CI). The build
is fully backend-independent.

## TL;DR

Each surface gets a pinned port via `make`. Port 5174 is intentionally
reserved for a second worktree's `pnpm dev` (a common dual-checkout pattern):

```bash
# Real dashboard (real backend, basename `/`)         → http://localhost:5173/
make dev-frontend                       # one window
make dev                                # frontend + api together (shell backgrounding; `make dev-attach`/`dev-restart` are the tmux-aware targets used by the devcontainer's auto-started session)

# Static-fixture demo SPA (no backend)                → http://localhost:5176/
make dev-demo
./dev/start-demo.sh                     # equivalent (also prints the URL)

# Marketing landing (for marketing iteration only)    → http://localhost:5175/
make dev-marketing

# Production preview (marketing + demo, exact ship)   → http://localhost:4173/
make dev-preview                        # build + serve in one step
./dev/start-demo.sh --preview           # equivalent
```

After `make dev-preview` open `http://localhost:4173/` for marketing, then
click "Try the demo →" or any other CTA → `/demo/` → demo SPA with the
persistent banner "Demo mode — your changes don't persist." with quick-access buttons for "Take a tour", "Self-host this", "View on GitHub", and "Back to gettidings.com".

Override any port via make var, e.g. `make dev-demo DEMO_DEV_PORT=5180`.

The basename in `frontend/src/main.tsx` is `/` in dev (so `:5173/` and
`:5176/` both mount the SPA at the root, like before the marketing port)
and `/demo` only in the production demo build (so the deployed `dist/`
serves the SPA from `/demo/*`). The script tag in `frontend/index.html`
ships as the marketing entry; a tiny `devEntrySwap` plugin in
`vite.config.ts` rewrites it to the SPA entry whenever the dev server
starts in any mode other than `marketing`.

## The one build flag

Demo mode is selected by `VITE_DEMO_MODE=true` in `frontend/.env.demo`.
`vite.config.ts` reads this via Vite's `--mode demo` and:

1. Adds a `resolve.alias` entry rewriting `@/lib/api` → `@/lib/demoApi`.
   Every caller (`queryConfigs.ts`, hooks, pages) gets the demo
   implementation without any runtime branching.
2. Runs a `transformIndexHtml` plugin (`demoHtmlMeta()`) that injects
   noindex / OG / Twitter meta and the demo favicon **only into the demo
   entry's HTML** (filename match on `demo/index.html`). A second
   `--mode demo` plugin (`marketingHtmlMeta()` in `vite.config.ts`)
   injects the marketing OG/Twitter/canonical/JSON-LD into the **root**
   entry at build time. Both are build-flag gated because the same
   `index.html` is also the self-hosted app shell — plain `pnpm build`
   emits it as `dist/index.html` and FastAPI serves it at `/`
   (the `StaticFiles` mount in `src/api/main.py`), so a self-hosted install
   must never ship a gettidings.com canonical.
3. Multi-entry input: `rollupOptions.input` produces both
   `dist/index.html` (marketing) and `dist/demo/index.html` (demo SPA).

Production builds (`pnpm build`) are unaffected.

## Static SEO files and OG cards

`robots.txt`, `sitemap.xml`, and `llms.txt` live in `frontend/public/`, so
they ship verbatim in every build's `dist/` (inert in the self-hosted
image, same accepted tradeoff as `_redirects` and `serve.json`). The
three 1200×630 OG cards — marketing (`frontend/public/og-image.png`),
demo (`frontend/public/demo-data/og-image.png`), and docs
(`docs-site/public/og-image.png`) — are committed artifacts; regenerate
all three via `cd frontend && pnpm og:images`
(`scripts/media/generate_og_images.ts`).

## Fixture regeneration

Fixtures live at `frontend/public/demo-data/*.json` (the rename from
`/demo/` happened so the SPA can mount at `/demo/*` without colliding
with the fixture path) and are committed to the repo. Regenerate them
when you change API contracts or the demo seed
(`data/demo/seed.json` — the single source of truth; never edit
fixture JSONs by hand).

**Always regenerate from an isolated worktree.** A worktree has no
`data/config.json` and no real databases, so a botched config flip can
only ever leak seed data — this is what makes the regen safe by
construction:

```bash
# 0. One-time per worktree: hydrate it.
claude --worktree demo-regen        # or the EnterWorktree tool
uv sync && (cd frontend && pnpm install --frozen-lockfile)

# 1. Wipe the demo DBs so the loader picks up seed changes.
rm -f data/demo.db data/demo-statements.db

# 2. Start the worktree's own backend on an offset port with the demo
#    world clock pinned. DEMO_FREEZE_MONTH keeps the loader from
#    date-shifting the seed to the real current month; DEMO_TODAY pins
#    every "today" computation (budget pace, historical windows,
#    forecasts) to the demo's anchor day.
DEMO_FREEZE_MONTH=2026-03 DEMO_TODAY=2026-03-19 \
  uv run uvicorn src.api.main:app --port 8001 &

# 3. Flip the backend into SQLite demo mode. Note the user_id flip:
#    the demo loader hard-codes USER#default, so the factories must
#    read the same partition or budget endpoints 404.
curl -sX PUT http://localhost:8001/api/v1/config \
  -H 'Content-Type: application/json' \
  -d '{"demo_mode":true,"user_id":"default","daily_summary_provider":"openai","insights_provider":"openai"}'

# 4. Sanity-check the persona BEFORE generating: March transactions
#    must belong to Mira.
curl -s "http://localhost:8001/api/v1/transactions?month=2026-03" \
  | grep -o '"name": "[^"]*"' | sort -u
# Expected: only "name": "Mira Lin Chen"

# 5. Regenerate JSON fixtures against the isolated backend.
cd frontend && DEMO_API_BASE=http://localhost:8001/api/v1 pnpm demo:fixtures
```

The endpoint list lives at `scripts/demo/demo_endpoints.ts` —
`DEMO_MONTHS` is the per-month fan-out and covers the 11-month
May 2025 → March 2026 window (March is a partial month by design;
the world ends at demo-today). Adding a new demo endpoint is
one entry plus a regen. `generate_demo_fixtures.ts` sanitises non-JSON
`Infinity` / `NaN` values (the summary endpoint emits these when a
comparison month is empty).

### Verify before commit

`pnpm demo:fixtures` writes whatever the API returns — there's no
sanitisation. Run the consistency gate plus the identity greps before
staging fixtures:

```bash
# The full cross-fixture gate: banned old-persona vocabulary, identity,
# summary↔transaction↔trend reconciliation (±$1), no dates after
# demo-today. Same script runs in CI.
uv run python scripts/demo/check_demo_fixtures.py

grep -rohE '"forwarded_to":\s*"[^"]+"' frontend/public/demo-data/ | sort -u
# Expected: only "forwarded_to": "mira.tidings@example.com"

grep -rohE '"institution":\s*"[^"]+"' frontend/public/demo-data/ | sort -u
# Expected: only RBC, CIBC, Simplii, Tangerine
```

Tangerine is in the demo world deliberately even though no Tangerine parser
ships: it plays the *unsupported bank* — its alerts populate the Needs-review
queue and the AI-extraction storyline. The fixture set is not a claim about
parser coverage; the supported list lives in the README's bank table.

The same checks run in CI via `.github/workflows/demo-smoke.yml`.
Local verification is faster — and catches a leak before it ever
reaches a PR.

If a check fails, the seed-driven demo backend wasn't actually serving
the regen. `rm -f data/demo.db data/demo-statements.db`, re-PUT
`demo_mode:true,user_id:default`, hit `/api/v1/transactions?month=2026-03`
and confirm `"name":"Mira Lin Chen"` before re-running
`pnpm demo:fixtures`.

### AI-derived fixtures

Monthly insights and journal daily summaries are pre-generated AI
content. Empty stub fixtures ship by default so the UI stays clean:

```bash
# Regenerate AI content (costs tokens via your configured provider)
cd frontend && pnpm demo:fixtures:ai
```

## What's interactive vs. hidden

| Surface | Demo behaviour |
|---|---|
| Journal, Transactions, Summary, Budgets, Income, Search, Insights (read) | ✅ fully interactive, backed by fixtures |
| Category edits on Transactions | ✅ sessionStorage overlay, persists across nav, dies on tab close |
| Budget envelope edits on `/budgets/edit` | ✅ same overlay mechanism |
| Theme toggle in Settings | ✅ kept |
| Add transaction / EML upload / CSV export | ❌ hidden |
| Statement PDF upload page body | ❌ replaced with "Configure locally" callout |
| Statement history row actions (open / download / re-parse / delete) | ❌ self-hosted modal |
| Generate Insight / Regenerate summary buttons | ❌ hidden (with a hint pointing at the repo) |
| Settings → Intelligence (AI provider) | ❌ hidden behind callout |
| Settings → Password / Sessions / Backup | ❌ hidden in demo (account-shaped) |
| Categorize → Rules / Aliases (write) | ✅ editable; sessionStorage overlay, dies on tab close |
| Categorize → Categories (write: add / rename / delete / icon / group) | ❌ self-hosted modal on every affordance |
| Trash (under /transactions/trash) | ❌ hidden behind callout |
| AI generation status polling, background workers | ❌ stubbed — returns "idle" immediately |

Unknown routes redirect to `/` with a one-shot flash banner.

## Serving locally

`frontend/public/serve.json` configures the `serve` package for SPA
fallback under `/demo/*`. The marketing root is served directly from
`dist/index.html` (no rewrite needed), the demo SPA is served from
`dist/demo/index.html` for any unknown sub-path:

```json
{ "rewrites": [{ "source": "/demo/**", "destination": "/demo/index.html" }] }
```

```bash
pnpm exec serve dist -l 4173
```

Open:
- `http://localhost:4173/` → marketing landing
- `http://localhost:4173/demo/` → Journal (demo SPA)
- `http://localhost:4173/demo/transactions` → Transactions, etc.

`frontend/public/_redirects` (Cloudflare Pages / Netlify convention)
carries the same rule: `/demo/* /demo/ 200`. The destination must be the
directory form — Cloudflare 308-canonicalizes `/demo/index.html` to
`/demo/`, so an `index.html` destination never resolves and the rule
silently falls through to the root not-found handler. Other static
hosts that don't read `_redirects` need their own equivalent (Nginx:
`try_files $uri /demo/index.html;` inside a `location /demo/` block,
plus a default `try_files $uri /index.html;` for the marketing root).

## Anti-rot CI

`.github/workflows/demo-smoke.yml` runs on every PR touching
`frontend/**` or the fixture scripts. It:

1. Installs Playwright Chromium.
2. Runs `pnpm demo:build`.
3. Serves `dist/` on `:4173`.
4. Runs `frontend/e2e/demo-smoke.spec.ts` — navigates every demo
   route under `/demo/*`, asserts zero `console.error` (benign
   sparse-fixture 404s are filtered) and a page-specific content
   marker, then exercises the two allowlisted mutations. Also runs
   `frontend/e2e/marketing-smoke.spec.ts` for the marketing surface
   and the cross-surface flow.

If either workflow goes red, the demo is broken. Fix it before
merging.

## Static-host deployment

This is a one-time owner-side setup (not scripted, not part of the
loop's deliverable). The dual-surface bundle is host-agnostic; pick
whichever fits.

### Cloudflare Pages

1. Create a Cloudflare Pages project connected to the GitHub repo.
2. Build command: `cd frontend && pnpm install --frozen-lockfile && pnpm demo:build`.
3. Build output directory: `frontend/dist`.
4. Environment variable: `VITE_DEMO_MODE=true`.
5. Production branch: `main`.
6. Confirm per-PR preview deploys are enabled (default-on for GitHub-connected projects).
7. Verify the GitHub OAuth connection is read-only.

`frontend/public/_redirects` is copied into `dist/_redirects` by the
build and Cloudflare picks it up automatically.

**Verify the deploy, don't assume it.** `make verify` serves `dist` with
`serve`, which reads `serve.json` — Cloudflare reads `_redirects`. The two
files carry the same rule for different readers, so a broken `_redirects`
passes every local gate. Run `make prod-smoke` after a deploy (or
`PROD_BASE_URL=https://<preview>.pages.dev make prod-smoke` against a preview);
it asserts each demo route is served by the demo shell rather than the
marketing one. To reproduce Cloudflare's pipeline locally without deploying:
`cd frontend && pnpm dlx wrangler pages dev dist`.

`pnpm demo:build` now prerenders the marketing landing into
`dist/index.html` (full copy and FAQ answers in the static HTML for
non-JS crawlers) as its final step — the build command itself is
unchanged.

### Custom domain (`gettidings.com`)

Mapping the apex to the host is also owner-side. Once DNS is wired,
`https://gettidings.com/` serves the marketing landing and
`https://gettidings.com/demo` serves the demo SPA. The hard-coded
href "Back to gettidings.com" in the demo banner becomes literal at
that point; until then it's a relative `/` link that works everywhere.

### Netlify, S3 + CloudFront, plain Nginx

Same artifact, host-specific fallback rules. Use `_redirects` for
Netlify-compatible hosts; for Nginx see the SPA-fallback block in
"Serving locally" above.

## Demo API

The same fixtures the demo SPA renders are also served as a read-only JSON
API at `https://gettidings.com/demo/api/v1/*` — one endpoint an agent can hit
to taste the contract before installing. It reuses the committed
`frontend/public/demo-data/*.json` bytes verbatim; there is no second snapshot
tree.

### Committed artifacts

Three files live under `frontend/public/demo-api/` (kept separate from
`demo-data/` so the fixture-identity gate doesn't sweep them):

- `manifest.json` — generated. Maps canonicalized API URLs to asset paths.
- `openapi.json` — generated. The root `openapi.json` filtered to the demo's
  paths, retitled, and given a `servers` entry.
- `health.json` — hand-authored inside the demo world (a live health probe
  computes ages from the real clock and would report `stale`), pinned to
  `2026-03-19` America/Toronto.

### Regenerate

Both generated artifacts are byte-stable — regen produces no diff unless the
inputs changed:

```bash
cd frontend && pnpm demo:api-manifest          # rebuild manifest.json
uv run python scripts/demo/generate_demo_openapi.py  # rebuild openapi.json
```

### How it's served

Cloudflare Pages invokes Functions ahead of static assets, so a single
Function owns the API prefix while every other route stays on the free static
path:

- `frontend/functions/demo/api/[[path]].js` — thin glue that loads the
  manifest, resolves the request, and writes the response headers. All routing
  logic lives in `frontend/src/lib/demoApiGateway.ts`, where it is typed,
  linted, and vitest-covered.
- `frontend/public/_routes.json` — scopes Function invocation to
  `/demo/api/*`, keeping the marketing and demo-SPA requests static.

### Gate

`make verify-demo-api` regenerates both artifacts, fails on any
`git diff` under `frontend/public/demo-api/`, and runs
`scripts/demo/check_demo_api.py` (manifest shape, canonical keys, asset existence,
schema consistency, and `health.json` structure). It runs inside `make verify`
after `verify-openapi`.

### Local check

`serve` and Playwright cannot exercise the Function — Pages Functions only run
on Cloudflare, so `/demo/api/*` under `serve` returns the SPA shell by design.
Do not add Playwright coverage for these routes. To see the live shape locally,
run Wrangler after a demo build:

```bash
cd frontend && pnpm demo:build
pnpm dlx wrangler pages dev dist
```

### Cloudflare requirement

The Function is only discovered when the Pages project's root directory is
`frontend`. Project 1 (the marketing + demo bundle) therefore sets root
directory `frontend`, build command
`pnpm install --frozen-lockfile && pnpm demo:build`, and output directory
`dist`. Cloudflare detects `frontend/functions/` automatically from there.

## Troubleshooting

**All data shows `$0.00`.** The Vite alias didn't apply. Check that
you ran `pnpm demo:build` (not `pnpm build`) and that
`frontend/.env.demo` exists with `VITE_DEMO_MODE=true`.

**404s on `/transactions`, `/settings`, etc.** The static host isn't
configured for SPA fallback. `frontend/public/serve.json` handles this
for the `serve` package; Cloudflare Pages uses `frontend/public/_redirects`.

**Demo deep links return 200 but render the marketing landing page.** Not a
404 — the `/demo/*` rewrite in `_redirects` failed to resolve and the root
not-found handler answered instead. Check the destination is `/demo/`, not
`/demo/index.html`. `make prod-smoke` catches this; local gates cannot.

**Stale fixtures.** Browser cache can pin an old 404 after regenerating
fixtures — hard-reload (Ctrl+Shift+R / Cmd+Shift+R) or restart
`serve`.

**Fixture endpoint returns 404 during regeneration.** The endpoint may
be marked optional in `scripts/demo/demo_endpoints.ts` — the generator
skips those. Non-optional failures abort the run with exit 1.

**Playwright test fails with "Demo mode not visible".** Confirm
`pnpm demo:build` succeeded and `dist/index.html` contains the
`noindex` meta (`grep noindex frontend/dist/index.html`).

## Related

All three are local-only specs, absent in the public repo:

- Spec: [`docs/specs/00_open-source-migration/2026-04-16-static-demo-deployment/SPEC.md`](../specs/00_open-source-migration/2026-04-16-static-demo-deployment/SPEC.md) (local-only)
- Panel rationale: [`EXPERT_PANEL.md`](../specs/00_open-source-migration/2026-04-16-static-demo-deployment/EXPERT_PANEL.md) (local-only)
- OSS migration master plan: [`docs/specs/00_open-source-migration/PLAN.md`](../specs/00_open-source-migration/PLAN.md) (local-only)
