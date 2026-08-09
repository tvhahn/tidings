# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning

This project follows [Semantic Versioning](https://semver.org/).

- **MAJOR** — breaking API changes, incompatible database schema changes, or removal of a supported bank parser.
- **MINOR** — new features, new bank parsers, new notification providers.
- **PATCH** — bug fixes, parser updates for bank email template changes, documentation.

**Pre-1.0 (`0.x`) versions may contain breaking changes between minor releases.** Read the changelog before upgrading. A 1.0 release will mark API and schema stability.

## [Unreleased]

### Changed

- Marketing landing: the closing olive-tree photograph now reaches up to the
  FAQ's last question and stays put when an answer opens (the text slides over
  the scene instead of pushing it), the demo subtitle says the demo runs in
  your browser, and the footer theme control is a quiet three-icon row. The
  social-share card is now an illustrated scene — an olive sapling and a
  notebook in morning light — instead of a text-only card.

### Fixed

- Self-hosted image: a hard refresh or direct link to a dashboard route
  (`/transactions`, `/summary`, …) now serves the app instead of a 404. API
  paths keep their JSON 404.

## [0.1.0] — 2026-07-21

Initial open-source release.

### Security

- Release-time PII protections. Synthetic merchants, amounts, reference
  numbers, card digits, and filenames run throughout the parser fixtures and
  worked examples. A release audit script (`scripts/pii/audit_oss_release.py`)
  scans the shipped tree and runs in CI as a blocking release gate, backed by a
  tracked `pre-push` hook that re-audits the tree before every push.

### Added

- **Journal, Summary, and insights dashboards.** A React + Vite + TypeScript
  app — daily Journal, Summary with monthly trends and category breakdowns,
  budget tracking, transaction search — over a FastAPI backend.
- **Commitment-aware projection.** Per-merchant expected charges (rent on the
  1st, the annual renewal) are derived from your own transaction history alone —
  no bank connection, no new storage — so a mid-month projected month-end reads
  as observed spending plus charges still committed plus an everyday estimate,
  rather than smearing fixed charges across the month. The projection opens one
  shared breakdown sheet wherever it appears.
- **Canadian bank email parsers.** Deterministic parsers for RBC, CIBC, MBNA,
  Simplii, and PC Financial alert emails, plus PDF statement parsers for RBC
  and Simplii chequing, on a shared `TransactionParser` base class.
- **Dual-backend storage.** SQLite for self-hosted installs, DynamoDB for AWS
  deployments, selected automatically from configuration; SQLite runs in WAL
  mode behind a schema-versioned, idempotent migration runner.
- **Self-hosted Docker Compose stack.** `docker compose up` brings up
  FastAPI + React + SQLite; an `imap-poller` sidecar ingests bank alerts from a
  dedicated Gmail account over IMAP and idles until credentials are set.
- **AWS serverless variant.** An alternate ingestion path — email → Amazon
  SES → S3 → Lambda → DynamoDB → notification provider — with a monthly-summary
  Lambda on EventBridge and secrets loaded from SSM Parameter Store.
- **Notifications.** A unified service with Ntfy, Twilio, and AWS SNS providers
  plus a log-only fallback; the active provider is auto-selected from
  environment variables, so zero-config deployments still work.
- **Optional AI, off by default.** Consents in `data/config.json` gate
  OpenAI-powered categorization (`ai_categorization_enabled`), rescue of
  unreadable alerts (`ai_extraction_enabled`), and receipt reading
  (`ai_receipt_parsing_enabled`), each defaulting off unless `OPENAI_API_KEY`
  is set. See [docs/guides/configuration.md](docs/guides/configuration.md).
- **Receipts and the tax pack.** Transactions carry file attachments (photos,
  invoices, PDFs, HEIC converted on upload); optional AI reads a receipt into
  merchant/date/total and proposes its transaction. A `/tax` page groups the
  year into CRA claim lines with evidence status and a zip export. See the
  Attachments and Tax pack sections in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- **Agent surface.** A bearer-scoped `/api/v1` with a unified
  `{error, code, details}` schema and OpenAPI docs at `/docs`; an append-only
  activity ledger with one-call revert for invertible writes (Settings →
  Activity); `GET /api/v1/whoami`; `GET /llms.txt`; and a read-only hosted demo
  API. See the [agent access guide](docs/guides/agent-access.md).
- **Demo mode.** Seeded sample data (`data/demo.db`) shifts to the current
  month at first load, so new users can explore the full dashboard without
  connecting any real accounts.
- **Add-a-parser path.** Alerts from an unrecognized bank land in a Needs
  review queue; `POST /api/v1/parse-failures/{id}/to-fixture` writes a scrubbed
  fixture pair, `POST /api/v1/parse-failures/retry-all` re-runs the parsers
  across a backlog, and the `add-a-parser` skill builds a conservative parser
  from your quarantined emails. See
  [docs/guides/add-a-parser.md](docs/guides/add-a-parser.md).
- **Onboarding and community docs.** A self-hosted-first README,
  `CONTRIBUTING.md` centered on a bank-parser tutorial, a code of conduct,
  issue and pull-request templates, and Gmail IMAP and notification guides.
  Multi-arch Docker images (`linux/amd64` + `linux/arm64`) publish from CI, and
  the dashboard self-hosts its fonts.
