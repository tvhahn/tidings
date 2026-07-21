# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-07-21

Initial open-source release.

### Security

- **Pre-release PII protections.** Parser test fixtures use synthetic
  merchants, amounts, reference numbers, card digits, and filenames; the
  shipped seed configs (`category_overrides.json`, `blocked_companies.json`)
  carry generic defaults; worked examples in docstrings and agent commands use
  invented businesses; the agent-access guide's illustrative token is an
  obvious placeholder. A release-time audit (`scripts/pii/audit_oss_release.py`)
  scans the shipped tree — Luhn card validation, Anthropic-key/JWT/ARN
  patterns, fixture-filename checks, and a blob-level history scan — and runs
  in CI as a blocking release gate over the whole tree (`dev/` included),
  backed by a tracked `pre-push` hook (remote allowlist + tree audit).

### Added

- **Agent activity ledger.** Every write to `/api/v1/*` is journaled with the
  caller's identity (token, browser session, or pre-password device): an
  append-only dual-backend store, `GET /api/v1/whoami` caller introspection
  (finally stamping token `last_used_at`, throttled), a filterable
  `GET /api/v1/activity` feed, and stale-guarded one-call revert for the ten
  invertible operations — surfaced in the app as Settings → Activity, a calm
  feed grouped by principal and burst with per-entry revert. Capture is
  fail-open and adds no latency to the write path.

- **Commitment-aware projection — the projection you can open.** Tidings now
  derives per-merchant expected charges (rent on the 1st, insurance around
  the 20th, the annual renewal) purely from your own transaction history —
  no bank connection, zero new storage. Mid-month projections stop smearing
  fixed charges across the month: projected month end = observed spending +
  charges still committed + an everyday-spending estimate. Each expected
  charge is tracked as upcoming, arrived, assumed (statement-observed and
  awaiting import — counted in the projection, never alarming), or
  unrecorded (a calm "usually bills by the 20th — nothing yet" note). The
  Journal headline ships in two selectable styles (Settings → Display):
  `Standard`, a quiet strip where the projection labels the forecast
  diamond, and `Timeline`, a month line with ink dots for recorded days and
  penciled circles for charges ahead of — and behind — today. Clicking the
  projection anywhere (Journal headline, Summary card) opens one shared
  breakdown sheet showing exactly what the number is made of. Budget
  categories dominated by a known charge project as "expected this month"
  instead of a curve, daily summaries gain a day-before heads-up, and
  mid-month comparisons become like-for-like for statement-imported
  accounts. Which headline style did you keep? Tell us in the discussion
  thread — one will graduate to default permanence.
- **Forecast accuracy for statement importers.** Spending history curves count
  statement-created rows *and* email rows enriched by a statement import — up
  to a quarter of real spending that a naive email-only projection would miss.
- **Operator tooling.** The `dev/` script tree ships the operator CLIs and
  eval harness: `dev/cli/` carries the category-maintenance CLIs behind the
  `/review-categories` and `/fix-categories` slash commands (the yearly
  insights gatherer now works on both storage backends via the storage
  factories, and the DynamoDB backup/restore pair reads its region from
  `AWS_REGION`), and `dev/eval_harness/` re-arms the `make dev-eval-harness`
  Streamlit prompt-eval harness (`uv sync --extra eval`). The standalone
  Lambda and IMAP e2e scripts ship as opt-in pytest integration tests in
  `tests/integration/` — env-gated, self-cleaning, excluded from every
  default gate.

- **Receipts and the tax pack.** Transactions can now carry file attachments
  (receipt photos, invoices, PDFs — HEIC converted on upload), stored in a
  SQLite-only `data/attachments.db` + `data/raw/attachments/` beside the
  statement store. With the new `ai_receipt_parsing_enabled` consent in
  `data/config.json` (default off), the provider from Settings → Intelligence
  reads a receipt into merchant/date/total + advisory line items — the app's
  first image/vision path — and a tier-ranked matcher proposes which
  transaction the receipt explains, auto-linking only an exact single match.
  A new `/tax` page ("Tax receipts") groups the year's spending into seven
  CRA claim lines (`src/finance/config/tax_line_mappings.json`; a personal
  copy in `data/config/` wins) with per-transaction evidence status
  (receipt / email / statement) and exports the pack as a zip of CSVs plus
  the evidence files. Demo builds render `/tax` from a generated fixture;
  attach, parse, and export stay demo-gated. See
  [docs/guides/configuration.md](docs/guides/configuration.md) and the new
  Attachments and Tax pack sections in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- **Hosted demo API.** The demo journal is now served read-only at
  `https://gettidings.com/demo/api/v1/*`, backed by the existing demo fixtures
  and fronted by a single Cloudflare Pages Function. An agent can explore the
  same routes as a self-hosted install — no token required — before cloning
  anything. Ships with a filtered OpenAPI schema at
  `/demo/api/openapi.json`, a "For agents" landing section, and docs in the
  [agent access guide](docs/guides/agent-access.md#try-it-without-installing).
  Writes return 405 with a self-host pointer. See
  [docs/guides/static-hosted-demo.md](docs/guides/static-hosted-demo.md#demo-api).
- **Unknown-bank onboarding.** Alerts from a bank Tidings doesn't recognize are
  no longer silently dropped when AI is off: a deterministic screen (a
  `$`-amount plus two or more alert keywords) captures them to the Needs review
  queue. New `ai_extraction_enabled` key in `data/config.json` splits the
  "rescue unreadable emails with AI" consent from `ai_categorization_enabled`
  (defaults derive identically from `OPENAI_API_KEY`; absent keys in existing
  configs derive on read), and both switches now appear in Settings →
  Intelligence. See [docs/guides/configuration.md](docs/guides/configuration.md).
- `POST /api/v1/parse-failures/{id}/to-fixture` — writes a scrubbed
  `.txt` + `.json` test-fixture pair from a captured email under
  `tests/test_data/`, for authoring a parser from real evidence. Gated to a
  git checkout with demo mode off; never overwrites. No UI — an agent/dev
  surface.
- `POST /api/v1/parse-failures/retry-all` — re-runs the deterministic parsers
  (never AI) across a whole institution's or sender domain's quarantined
  backlog, capped at 1,000 rows, returning
  `{retried, created, duplicates, still_failing}`. The Needs review page grows
  a "Retry all" button with inline confirm when the queue shares a single
  institution or sender domain.
- `.claude/skills/add-a-parser/` — an evidence-bound Claude Code skill that
  builds a parser for an unsupported bank from the user's own quarantined
  emails: scrubbed fixtures, conservative regex derived from real bodies only,
  three-place registration, property-harness wiring, and a closing bulk retry.
  See the "Start from your own quarantined emails" section of
  [docs/guides/add-a-parser.md](docs/guides/add-a-parser.md).
- New `timezone` key in `data/config.json` (default `"America/Los_Angeles"` for
  backwards compatibility). Non-Pacific OSS users now get correct day/month
  bucketing and correct "latest transaction age" arithmetic. Accepts any IANA
  zone name; invalid values fall back to Pacific with a log warning. See the
  [README](README.md#wire-up-your-own-data) for examples and the
  mid-stream-switch caveat.
- `.devcontainer/docker-compose.override.yml.example` ships three documented
  opt-in snippets for AWS credentials, the Docker socket, and host Claude Code
  config. Copy to `docker-compose.override.yml` (gitignored) and uncomment
  what you need.
- `.github/workflows/release.yml` — tag-triggered workflow that builds
  multi-arch Docker images (`linux/amd64` + `linux/arm64`), pushes to GHCR
  with `:vX.Y.Z` + `:latest`, and creates the GitHub Release from the
  matching `CHANGELOG.md` section. Fires on `v*` tag pushes;
  pre-1.0 tags (`v0.*`) are auto-marked pre-release.
  See [docs/guides/releases.md](docs/guides/releases.md#how-the-release-workflow-works).
- **Curate the tax pack by hand.** Beyond the automatic category → line
  mapping, you can now flag any transaction into a tax line from a "Flag as
  tax item" menu on the Journal and Transactions rows (choosing the line, or
  an "Other claimable" catch-all for categories that aren't mapped), and
  remove — then restore — items from a line on the `/tax` page. Overrides
  persist in a new SQLite-only `data/tax_overrides.db`; a line's total and
  receipt coverage recompute around what you've added or removed. The tax
  rows also gained per-item actions to view the source email and attached
  receipts. Two new demo-gated endpoints back it: `POST`/`DELETE
  /api/v1/tax-pack/items`.
- **Receipts on the Journal.** The receipt/attachment button that lived on the
  Transactions table now appears on Journal entry rows too (a journal entry
  and a transaction are the same record), so you can attach or view receipts
  wherever you are reviewing spending.
- `GET /llms.txt` — every instance serves a plain-text orientation file for
  agents.
- Dual-backend storage: DynamoDB for AWS deployments, SQLite for self-hosted use, selected automatically based on configuration.
- Demo mode with seeded sample data (`data/demo.db`) so new users can explore the dashboard without connecting any real accounts.
- Docker Compose production stack via `Dockerfile.prod` and the root `docker-compose.yml` — one `docker compose up` gets you a working FastAPI + React + SQLite install.
- IMAP poller daemon (`src/finance/imap_poller.py`) that automatically ingests bank alert emails from a dedicated Gmail account, shipped as a separate `imap-poller` Compose service sharing the `finance_data` volume.
- Unified notification service (`src/finance/notification_service.py`) with Ntfy, Twilio, and AWS SNS providers plus a log-only fallback; the active provider is auto-selected from environment variables so zero-config deployments still work.
- AWS Lambda deployment path for serverless users: email → Amazon SES → S3 → Lambda → DynamoDB → notification provider.
- Canadian bank email parsers for RBC, CIBC, MBNA, Simplii, and PC Financial, all inheriting from a shared `TransactionParser` base class.
- PDF statement parsers for RBC Chequing and Simplii Chequing, with a WeasyPrint + Jinja2 synthetic-fixture generator for tests.
- Optional OpenAI-powered transaction categorization (off by default when no API key is configured), with an opt-out Settings toggle (`ai_categorization_enabled`) that disables the OpenAI call and falls back to the existing `Miscellaneous` category. On by default when `OPENAI_API_KEY` is set, off otherwise; user choice is persisted.
- Monthly spending summary Lambda triggered by AWS EventBridge for users on the serverless path.
- FastAPI backend with `/api/v1/*` routes, a unified `{error, code, details}` error schema, and interactive OpenAPI docs at `/docs`.
- React + Vite + TypeScript frontend dashboard covering budget tracking, spending insights, and transaction search.
- Lambda secrets management via AWS SSM Parameter Store with a three-tier fallback loader (SSM → environment → `.env`).
- Bulk transaction edits (`PATCH /api/v1/transactions/bulk`) and a consolidated `/api/v1/insights/context` endpoint to reduce frontend round-trips.
- SQLite WAL mode with a 5-second busy timeout enabled by default for safer concurrent reads/writes on the self-hosted backend.
- Schema versioning with an idempotent migration runner (`src/finance/migrations/`) wired into the local-DB bootstrap, so future schema changes upgrade existing installs cleanly instead of breaking them.
- `GET /api/v1/health` endpoint exposing IMAP poll freshness, last parsed transaction, backend type, and version — paired with a sidebar status indicator (green / amber / red) and a click-through popover of the raw JSON. Uptime monitors can hit the endpoint directly.
- Dynamic demo-data date shift: `src/finance/demo_loader.py` shifts seed transactions forward to the current calendar month at first-run load time (i.e. when the demo DB is empty), with a `DEMO_FREEZE_MONTH` env override for the static-demo fixture export path. Returning users who want a fresh anchor should remove `data/demo.db` (or `docker compose down -v`) before restarting.
- Multi-arch Docker builds in CI (`linux/amd64` + `linux/arm64`) via a `docker-build.yml` workflow, so Raspberry Pi and Apple Silicon users stop hitting `exec format error`.
- `.env.example` covering IMAP, notification provider, OpenAI, and AWS e2e-test configuration so self-hosters have a single reference for required environment variables.
- Community and onboarding documentation: self-hosted-first README, `CONTRIBUTING.md` (centerpiece is a 4-step bank-parser tutorial), `CODE_OF_CONDUCT.md`, GitHub issue templates (bug, feature, and a structured `parser_broken` template), a pull-request template, a public `ROADMAP.md`, and step-by-step guides for Gmail IMAP setup and notification providers.

### Changed

- Fonts are self-hosted; the dashboard and marketing pages no longer request
  fonts.googleapis.com.
- **Summary and budgets redesigned around honest mid-month numbers.** The
  Summary page now leads with a deterministic one-line read of the month and
  swaps its stat cards by month state: the in-progress month shows "Spent so
  far", a projected month end with its typical range, and pace vs a typical
  month at the same day — a partial month is never compared against a
  complete one. The trend chart carries the projection as a hatched remainder
  on the current bar with a dashed 6-month average line, and the category
  table gains share-of-month and vs-average columns (`—` mid-month). Backed
  by a new nullable `pace` block on `GET /api/v1/summary`, computed from the
  existing forecast window (fail-open, current month only). The Flow view now
  reads income → spending → kept: sources split proportionally between a
  `Spending` hub and a `Kept` sink, deficits arrive as `From savings`, and
  the "Drawdown" jargon is gone. Category budgets trade per-row bars for a
  tinted ledger (the page's one bar lives in the split headline card) with
  pace percents, projection tooltips, and click-through rows; the monthly
  matrix becomes a whisper heat map with a legend and current-month marker;
  budget view state lives in the URL (`?view=monthly`). One segmented
  control style now serves both pages.
- **Light mode and the base palette are the default** for new users. A
  fresh install (or a browser with no saved preference) starts in light mode
  on the default palette instead of following the OS theme / Warm Paper.
  Anyone who has already picked a theme or palette keeps their choice.
- **The `/tax` page and its CSV export do not show country-specific tax
  line numbers** (e.g. Canada's "Line 34900"). The plain line labels are the
  surface; the `cra_ref` values stay in `tax_line_mappings.json` for
  self-hosters who want them via a personal config copy.
- Statement-import and manual-entry synthetic dates emit an explicit UTC
  offset (e.g. `-0800`) rather than a hardcoded `PST` abbreviation.
- Pin `ghcr.io/astral-sh/uv` base image to `0.11.14` in both `Dockerfile.prod`
  and `docker/imap_polling/Dockerfile` for reproducible release builds.
- `.devcontainer/Dockerfile` does not install OpenAI Codex or Google
  Gemini CLIs by default. Maintainers and power users restore them by
  uncommenting the "Extra AI CLIs" snippet in the gitignored
  `.devcontainer/docker-compose.override.yml` (auto-copied from the
  `.example`), which sets the `INSTALL_EXTRA_AI_CLIS: "true"` build arg —
  build args in `devcontainer.json` are ignored for compose-based
  devcontainers. Claude Code stays in the default image because the repo
  ships Claude Code skills as project artifacts.
  See [CONTRIBUTING.md](CONTRIBUTING.md) for the snippet.
- `.github/workflows/docker-build.yml` publishes `:main` to GHCR on every
  push to trunk; PRs build without pushing (compile-check). Coordinates with
  `release.yml`: trunk pushes own `:main`; tag pushes own `:vX.Y.Z` +
  `:latest`, so there is no `:latest` race.
- **Compose-file defaults are set for OSS launch.** Self-hosters' `docker
  compose up` (no `-f`) brings up the prod stack (the root
  `docker-compose.yml`). The devcontainer stack lives at
  `.devcontainer/docker-compose.yml`; contributors use VSCode's "Reopen in
  Container" or `docker compose -f .devcontainer/docker-compose.yml up`. The
  default `.devcontainer/docker-compose.yml` does not mount
  `/var/run/docker.sock` or `~/.aws`; restore both via
  `.devcontainer/docker-compose.override.yml` (see the `.example` shipped
  alongside).
- Quickstart drops the `cp .env.example .env` step — demo mode auto-detects
  an empty config and the `.env` is only needed once you wire real IMAP
  credentials. `CONTRIBUTING.md` documents Devcontainer overrides (the three
  opt-in volume snippets) and a `c1` helper that launches Claude Code in a
  persistent tmux session baked into the image.

### Fixed

- `imap_poller` no longer crash-loops when `IMAP_USER` or `IMAP_PASSWORD` is
  unset. The daemon now idles with a single log line; set both vars to enable
  polling. Fixes the bare-`docker compose up` UX for self-hosters who don't
  immediately wire IMAP.
- `/api/v1/health` no longer returns 500 on a fresh `docker compose up`
  against an empty `finance_data` volume. `get_imap_last_poll()` previously
  opened (and silently created) `finance.db`, then queried `config_store`
  before any write had triggered `ensure_schema()` — the
  `sqlite3.OperationalError` propagated up through the health endpoint and
  the sidebar `HealthIndicator` rendered red from first page load. The
  helper now catches `OperationalError` and returns `None`, which is
  semantically correct for "no last poll recorded yet."
  Regression test in `tests/unit/test_imap_poller.py::TestHeartbeat`.
- `.devcontainer/devcontainer.json` no longer enables the
  `docker-outside-of-docker` feature in the default contributor build.
  The feature auto-mounted the host's Docker socket regardless of what
  `.devcontainer/docker-compose.yml` specified, undoing the no-host-daemon
  security posture on a fresh clone. Maintainers and power users who
  build/push images from inside the devcontainer restore the feature by
  adding it to the gitignored `.devcontainer/devcontainer.local.json` —
  `CONTRIBUTING.md` has the snippet. The `aws-cli` feature stays in the
  default image: it's a binary install with no credential exposure, and
  removing it would break maintainer ECR workflows once the socket override
  is restored.

## Versioning

This project follows [Semantic Versioning](https://semver.org/).

- **MAJOR** — breaking API changes, incompatible database schema changes, or removal of a supported bank parser.
- **MINOR** — new features, new bank parsers, new notification providers.
- **PATCH** — bug fixes, parser updates for bank email template changes, documentation.

**Pre-1.0 (`0.x`) versions may contain breaking changes between minor releases.** Read the changelog before upgrading. A 1.0 release will mark API and schema stability.
