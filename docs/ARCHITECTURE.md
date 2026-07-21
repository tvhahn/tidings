# Architecture

**For contributors and curious self-hosters.** This document explains how Tidings turns bank transaction emails into categorized data, across both the everyday Docker self-host path (IMAP polling → SQLite) and the advanced AWS Lambda path (SES → S3 → Lambda → DynamoDB). After reading, you'll understand the dual-path design, where transactions enter the system, how categorization happens, and where data lives.

A few domain terms used throughout: a **forwarder** (or forwarding address) is the dedicated email recipient that bank alerts are routed to; **`ForwardedTo`** is that recipient address used as the DynamoDB partition key. An **override** is a known-good company-to-category mapping that short-circuits OpenAI. A **briefing** is an AI-generated spending narrative; an **override audit** records which rule fired on a given transaction.

## System overview

**Self-host path.** Gmail IMAP → Python poller → SQLite, all running in a single Docker stack:

<!-- docs-site:figure:self-host-path -->

```text
  Gmail inbox                  imap_poller (Docker)
 ┌─────────────┐         ┌──────────────────────────────┐
 │ forwarded   │ IMAP    │  imap_poller.py              │
 │ bank emails │────────>│    │                         │
 └─────────────┘         │    ├─> email_pipeline.py     │
                         │    ├─> detect institution    │
                         │    ├─> parse transaction     │
                         │    ├─> categorize (OpenAI)   │
                         │    └─> write (SQLite)        │
                         └──────────────────────────────┘
                                       │
                                       v
                                  data/finance.db
                                       │
                                       v
                                FastAPI ── React UI
```

**Advanced AWS path.** Same parser/categorizer/storage code, different transport and storage — SES inbound delivers emails into S3, Lambda processes each new object into DynamoDB:

<!-- docs-site:figure:aws-path -->

```text
  Email ──> S3 (.eml) ──> Lambda (Docker) ──> DynamoDB
                              │
                              └──> SNS (SMS)
```

The pipeline shared between both paths is described next; the AWS variant is detailed in [Advanced: AWS serverless variant](#advanced-aws-serverless-variant) at the end.

## IMAP polling daemon

`src/finance/imap_poller.py` is a long-lived polling daemon that replaces the AWS Lambda path for self-hosted deployments. It connects to an IMAP inbox, fetches new bank transaction emails, and runs them through the same `parse_email()` pipeline used by `lambda_function.py`.

### How it works

1. **UID persistence** — `_load_last_uid()` and `_save_last_uid()` store the last-seen message UID in the `config_store` SQLite table (PK `SYSTEM#imap_poller`, SK `last_seen_uid`). New UIDs above the stored value are fetched on each poll; already-processed messages are skipped. A second row at SK `last_poll_at` is updated on every successful poll; the `/api/v1/health` endpoint reads it as the IMAP heartbeat.

2. **Per-message processing** — `process_message(raw_bytes, uid, transactions_db, context_enricher)` mirrors the Lambda handler flow:
   - `parse_email()` extracts transaction fields
   - `transactions_db.add_transaction()` writes to storage; returns `None` (invalid), `False` (duplicate), or the `DateFileName` (new)
   - `context_enricher.enrich()` computes month-to-date spending context; `update_context()` persists it
   - `notification_service.send()` dispatches the transaction notification through the configured provider — SNS, ntfy, or Twilio, log-only when none is configured (see [`guides/notifications-setup.md`](guides/notifications-setup.md)) — suppressing blocked companies and unknown transaction types

3. **Connect + poll loop** — `ImapPoller` maintains an `imaplib` connection, polls every `poll_interval` seconds (default 60s), and applies exponential backoff (5s → 300s) on connection errors. Designed to run as a Docker service alongside the finance dashboard.

### Testing

`tests/unit/test_imap_poller.py` mocks `imaplib` + pipeline calls to verify orchestration logic. `tests/integration/test_imap_poller.py` is the opt-in end-to-end counterpart: it fetches one real message (requires `IMAP_USER` + `IMAP_PASSWORD`) and verifies the SQLite write — the self-hosted analogue of `tests/integration/test_lambda_e2e.py` on the AWS path.

## Anatomy of a request

Both paths run the same parser pipeline. The entry points differ — `imap_poller.py:_process_message` for IMAP self-hosted, `lambda_function.py:handler` for AWS — but everything from `email_pipeline.parse_email()` onward is shared code.

Here's what happens when a transaction email arrives, file by file:

### Transport and entry

1. **Transport trigger** — A raw email lands in the inbox (IMAP) or as a `.eml` object in S3 (AWS). The IMAP poller fetches new UIDs on its poll loop; the S3 event invokes the Lambda function.

2. **Entry point** — `imap_poller.py:_process_message` or `lambda_function.py:handler()` initializes the OpenAI client (`gpt-5.4-nano`) and calls `parse_email()`.

### Processing pipeline

3. **`email_pipeline.py:parse_email()`** — Orchestrates the full pipeline:
   - `extract_raw_email_details()` parses the raw bytes into structured headers (from, to, date, subject) and extracts the body text. The `X-Forwarded-To` header is used to identify the recipient; `user_mappings.csv` maps this to a `UserId` via an in-memory cache.
   - `parse_email_body()` detects the financial institution and delegates to the right parser (see [Parser system](#parser-system) below).

4. **Parser** — The matched parser (e.g., `RBCParser`) extracts `amount`, `company`, `name`, and `transaction_type` from the body text using regex patterns.

5. **`categorizer.py:categorize_transactions()`** — Runs the tiered `resolve_override()` matcher (exact → normalized → alias) against the overrides + aliases loaded from storage. On a hit, stamps `{source, matched_rule, confidence, reviewed_at}` onto the transaction as `_category_audit` so it rides through to `add_transaction(category_audit=...)`. Only novel phrasing the normalizer can't reach falls through to OpenAI (see [OpenAI integration](#openai-integration)).

6. **`transaction_db.py:add_transaction()`** — Generates a dedup hash, checks for duplicates, and writes to DynamoDB or SQLite (depending on backend; see [Data storage](#data-storage)). Returns the `DateFileName` sort key on success.

7. **`transaction_context.py:TransactionContextEnricher.enrich()`** — For new transactions, queries the same month's partition to compute month-to-date spending for the category, count merchant visits, and look up budget targets. The resulting `TransactionContext` is stored back on the transaction record via `update_context()`. Fail-open: returns `None` on any error.

### Outcomes

8. **Notification** — If the transaction is new (not a duplicate) and the company isn't in the blocked list, the system publishes via the configured notification provider (SNS for AWS, Ntfy/Twilio/log-only for self-hosted). When enrichment context is available, the message includes budget progress (e.g., `restaurant/dining — $340/$400 (85%)`) and merchant frequency (e.g., `3rd visit this month`).

**When things don't match:** If no parser matches the email body, `email_pipeline.py:parse_email_body()` returns the raw `email_details` dict without transaction fields. The email is **not** dropped: every entry point hands it to the parse-failure quarantine (below), which either recovers it via AI extraction or captures it in the dead-letter store for later retry. The same applies when `add_transaction()` rejects parsed fields (`failure_stage: "db_validation_failed"`).

### Parse-failure quarantine

`src/finance/parse_recovery.py` is the shared recovery gate all three transports call (IMAP poller, Lambda handler, `upload-eml`). When parsing yields no usable transaction:

1. **Relevance gate** — an email is relevant when `_detect_institution_by_sender()` matches, a parser name (`email_pipeline.PARSER_KEYS`) appears in the body, or the `email_is_transaction_alert()` classifier says so (classifier errors bias toward capture). Everything else is ignored, as before.
2. **AI extraction fallback** — with an AI client and `ai_categorization_enabled` (the same privacy opt-out the categorizer honors), `extractor.extract_transaction()` runs one forced tool call constrained to `{amount, company, transaction_type}`. `validate_extraction()` enforces the anti-hallucination contract: the amount must appear verbatim in the body (candidate-set membership, `$`/comma tolerant) and the company must be a whitespace-collapsed case-insensitive substring. Recovered transactions are stamped with an `ExtractionAudit` provenance map (`category_audit.build_extraction_audit()`), flow through the normal categorize → `add_transaction` → notification path, and join the attention queue until a human touches them.
3. **Quarantine** — anything relevant that wasn't recovered is persisted by the dual-backend `ParseFailureStore` pair (`parse_failure_store.py` DynamoDB / `parse_failure_store_local.py` SQLite, migration 003) with the full `email_details` dict, a `failure_stage` (`no_parser_match` | `extraction_empty` | `ai_extraction_failed` | `ai_validation_failed` | `db_validation_failed`), and a deterministic `pf_` id so Lambda redeliveries upsert. `GET/DELETE /api/v1/parse-failures[/{id}]` list and dismiss rows; `POST /api/v1/parse-failures/{id}/retry` re-runs the deterministic parsers after a parser fix; `POST /api/v1/parse-failures/{id}/resolve` hand-enters a transaction for a quarantined email the parsers can't read (the "Needs review" manual-entry path). Rows ride along in the `/api/v1/data/export` backup zip.

The whole gate is fail-open (`recover_or_quarantine` never raises) — a quarantine bug must never break ingestion. The first quarantine per institution per 24h sends one calm notification via `notification_service.send_raw`; `/health` exposes the 7-day quarantine count (see [Health endpoint](#health-endpoint)).

## HTTP API

The FastAPI app at `src/api/main.py` serves the dashboard frontend and all external consumers (Claude CLI subprocesses, Home Assistant automations, mobile shortcuts). The router modules in `src/api/routers/` (one per `/api/v1/*` resource) are mounted through `src/api/dependencies.py` factories so both storage backends (DynamoDB + SQLite) work transparently.

### Versioning

Every route mounts under `/api/v1/`. Breaking changes will ship as `/api/v2/` rather than in-place so existing consumers (the React frontend, any external script) keep working until they migrate. The policy is documented in the root OpenAPI description in `src/api/main.py` and surfaces in `/docs`.

### Authentication

Two schemes cover the two kinds of caller; the full walkthrough is [`guides/agent-access.md`](guides/agent-access.md).

- **Browser sessions (TOFU).** First run is trust-on-first-use: the dashboard works without a password until one is set via `POST /api/v1/auth/set-password` (Settings → Password). After that, `POST /api/v1/auth/login` issues a signed `tidings_session` cookie; `/logout` and `/sign-out-all` revoke sessions. Password hashing and session issue live in `src/finance/auth_session.py`; the routes in `src/api/routers/auth.py`.
- **Bearer tokens (agents and scripts).** `bearer_auth_middleware` (`src/api/auth.py`, mounted in `main.py`) validates `fin_…` tokens minted by `src/finance/agent_tokens.py` — only the SHA-256 hash is persisted. Each token carries a scope checked against per-scope route allowlists (`SCOPE_ALLOWLISTS` in `src/api/auth.py`); `read` covers GET routes, `read+write` all methods. `/api/v1/health` and the other `PUBLIC_PATHS` stay unauthenticated.

### Unified error schema

Every 4xx/5xx response follows the shape:

```json
{ "error": "Transaction not found", "code": "NOT_FOUND", "details": null }
```

Routers keep raising `HTTPException(status_code=..., detail="...")` — the handler at `main.py:http_exception_handler` rewrites every exception into the shape above using `code_from_status()` (see `src/api/errors.py` for the status→code map: `404 → NOT_FOUND`, `409 → CONFLICT`, `422 → VALIDATION_ERROR`, etc.). Pydantic `RequestValidationError` gets the full error list in `details`.

Use `ApiException(status_code, code, message, details)` from `src/api/errors.py` when you need a custom machine code or structured details — the handler unpacks its richer payload automatically.

### Discovery

`FastAPI(openapi_tags=...)` in `src/api/main.py` declares one tag per router domain (`_OPENAPI_TAGS`). The auto-generated schema is reachable at:

- `http://localhost:8000/docs` — Swagger UI
- `http://localhost:8000/redoc` — ReDoc
- `http://localhost:8000/openapi.json` — machine-readable schema

### Scripts share modules, not HTTP

Anything that needs domain logic outside the API — the operator CLIs in `dev/cli/`, slash commands, the AWS Lambda handlers — imports the shared modules under `src/finance/` directly rather than calling over HTTP. This is deliberate: module-level access is the break-glass path for fixing data when the API is not running. The correct DRY pattern is shared importable modules under `src/finance/`, consumed by both sides.

Canonical example: `src/finance/insights_context.py` exports `gather_context(year_month)`. The `GET /api/v1/insights/context` endpoint imports it and returns the JSON; the `/spending-insights` slash command runs the same function offline. Single function, two callers, no HTTP coupling.

### Filter semantics

`/api/v1/transactions/search` filters are intentionally *not* uniform across fields. `company` is a case-insensitive substring match (merchant strings arrive with payment-processor noise like `"Sq *coffee Spot Cen"`); `category`, `institution`, and `type` are case-insensitive exact match (clean enum-like values). The split is load-bearing domain knowledge, not an inconsistency — documented per-field in OpenAPI at `src/api/routers/search.py`.

### Health endpoint

`GET /api/v1/health` (`src/api/routers/health.py`) is an unauthenticated liveness probe. It returns `{status, version, backend, imap_last_poll, imap_poll_age_seconds, last_transaction_at, last_transaction_age_seconds, parse_failures_7d, ai_categorization_status, checked_at}` in under 50 ms. Status thresholds: `ok` when the IMAP poller heartbeat is under 5 minutes old (or the poller isn't configured); `degraded` at 5–30 minutes, when `parse_failures_7d > 0` (one or more emails quarantined in the last 7 days — the per-institution template-drift signal, surfaced in minutes instead of weeks), or when `ai_categorization_status` is `degraded` (a run of hard provider errors filing transactions as Miscellaneous); `stale` past 30 minutes, or when no transaction has been parsed in 14 days. `stale` always wins over a quarantine-driven `degraded`. Every read is fail-open — a fresh boot with no parse-failures table reports `parse_failures_7d: null` rather than 500-ing. The React frontend polls the endpoint and surfaces the status as a sync dot beside the month picker.

## Parser system

Parsers use the **Strategy pattern**. Each institution has a class inheriting from `TransactionParser` (`parser_base.py`), which requires implementing `parse_email(email_body_text, email_details) -> dict`.

Beyond the five email parsers, `etransfer_parser.py` handles Interac e-Transfer notifications from any Canadian bank using `payments.interac.ca`, and statement PDF parsers (`rbc_statement_parser.py`, `simplii_statement_parser.py`) cover batch imports — detailed in the [Statement import](#statement-import) section below.

### Two-phase institution detection

`email_pipeline.py:parse_email_body()` selects the parser in two phases:

1. **Sender domain** — Match `from_email` against a domain map (`cibc.com` → CIBC, `alerts.rbc.com` → RBC, etc.). This is fast and reliable for direct institution emails.

2. **Body text fallback** — If no domain matches (e.g., forwarded emails, Interac e-transfers from `payments.interac.ca`), scan the body text for institution name strings.

Interac e-transfers are intentionally omitted from the domain map because multiple institutions (RBC, Simplii) use the same `payments.interac.ca` sender — the body text reveals which institution originated the transfer.

### Parser capabilities

| Parser | Transaction Types | Detection Method |
|--------|------------------|-----------------|
| **RBC** | purchase, withdrawal, e-transfer | Sender domain or body text |
| **CIBC** | purchase, preauth payment | Sender domain or body text |
| **MBNA** | purchase | Sender domain or body text |
| **PC Financial** | purchase | Sender domain or body text |
| **Simplii** | e-transfer | Body text only (uses Interac sender) |

The shared `etransfer_parser.py:parse_e_transfer()` function handles e-transfer parsing for both RBC and Simplii.

### Adding a new parser

1. Create `src/finance/parsers/<institution>_parser.py` with a class inheriting from `TransactionParser` (from `parser_base.py`)
2. Implement `parse_email()` — extract `amount`, `company`, `name`, `transaction_type` using regex
3. Register it in `build_parsers()` in `email_pipeline.py` (the imports sit at module top)
4. If the institution has a unique sender domain, add it to `_detect_institution_by_sender()`
5. Add test fixtures in `tests/test_data/<institution>/` (`.txt` + `.json` pairs)

## Data storage

### DynamoDB schema

**Table: `Transactions`** (on-demand billing / `PAY_PER_REQUEST`)

| Attribute | Type | Role | Description |
|-----------|------|------|-------------|
| `ForwardedTo` | String | **Partition key** | Email recipient address |
| `DateFileName` | String | **Sort key** | `YYYY.MM.DD_HH.MM_<filename>.eml` — encodes temporal ordering |
| `TransactionHash` | String | | SHA-256 dedup hash (see below) |
| `UserId` | String | | Mapped from `ForwardedTo` via `user_mappings.csv` |
| `Institution` | String | | e.g., "RBC", "CIBC" |
| `Amount` | Decimal | | Transaction amount (stored as DynamoDB Decimal) |
| `Company` | String | | Merchant or recipient name |
| `TransactionType` | String | | "purchase", "withdrawal", "preauth", "e-transfer" |
| `Category` | String | | Lowercased category from OpenAI (e.g., "groceries") |
| `Name` | String | | Cardholder first name |
| `Date` | String | | Timestamp in the configured `timezone` (`src/finance/app_timezone.py`, default Pacific), formatted `MM/DD/YYYY HH:MM ZZZ` where `ZZZ` is that zone's abbreviation (e.g. `PDT`/`PST`) |
| `FileName` | String | | S3 object key |
| `FromName`, `FromEmail` | String | | Sender details (email lowercased) |
| `ToName`, `ToEmail` | String | | Recipient details (email lowercased) |
| `Subject` | String | | Email subject line |
| `Body` | String | | Full email body text |
| `CategoryAudit` | Map | | Audit metadata: `source` (`override`/`override_normalized`/`override_alias`/`override_fuzzy`/`manual`/`audit`/`statement_import`/`statement_enrich`/`manual_edit`), `matched_rule` (original-case override key that fired), `confidence` (Decimal; `1.0` for Tiers 0–2, cosine score for Tier 3), `reviewed_at` (ISO timestamp) |
| `ExtractionAudit` | Map | | Provenance for AI-recovered rows (parse-failure quarantine path): `method` (`ai_fallback`), `model`, `validated` (always `true`), `extracted_at` (ISO timestamp), `schema_version`. Built by `category_audit.build_extraction_audit()` |
| `Ignored` | Boolean | | When true, transaction is excluded from summaries |
| `Comment` | String | | User annotation/note on the transaction |
| `DeletedAt` | String | | ISO 8601 timestamp when soft-deleted; absent if active |
| `TransactionContext` | Map | | Enrichment context: `category_month_total`, `merchant_month_count`, optional `category_budget_target` and `category_budget_pct` |

The table is auto-created if it doesn't exist.

### DynamoDB: BudgetConfig table

**Table: `BudgetConfig`** (on-demand billing / `PAY_PER_REQUEST`)

| Attribute | Type | Role | Description |
|-----------|------|------|-------------|
| `PK` | String | **Partition key** | `USER#<user_id>` — derived from `data/config.json` `user_id` field |
| `SK` | String | **Sort key** | Prefixed config key (e.g., `BUDGET#targets#2026`, `BUDGET#groups#2026`) |
| `Data` | Map | | JSON config payload |
| `UpdatedAt` | String | | ISO 8601 timestamp |
| `Version` | Number | | Monotonically increasing; used for optimistic locking |

Two items per year:
- **Budget Targets** (`SK = "BUDGET#targets#2026"`) — spending ceiling and per-category targets (annual amount, input_mode, category_type, derived monthly_amount)
- **Category Groups** (`SK = "BUDGET#groups#2026"`) — display-only grouping of categories for UI organization

Writes use `ConditionExpression` for optimistic locking. On conflict, the API returns HTTP 409 and the frontend re-reads before retrying.

### BudgetService

`src/finance/budget_service.py` — follows the same pattern as `SpendingSummary`. CRUD operations for budget configuration, historical average computation (with 1-hour in-memory cache), and category type inference (fixed/variable/lumpy). Every write also persists a JSON backup to `src/finance/config/budget_config.json`.

On the self-hosted SQLite backend, the `BudgetConfig` equivalent lives in `data/finance.db` and is created automatically by `ensure_schema()`. On the AWS path, the `BudgetConfig` DynamoDB table is provisioned during initial deployment.

### Schema migrations (SQLite)

The self-hosted backend owns its schema lifecycle through an idempotent migration runner at `src/finance/migrations/`. A `schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)` table records every applied migration; the runner discovers numbered modules (`001_initial.py`, `002_...`, ...), applies each pending migration in a transaction, and records success. `ensure_schema()` is called by the IMAP poller at startup and by every SQLite-backed service constructor on first use; the FastAPI lifespan does not call it explicitly. Users see one consistent database regardless of which service wakes up first after an upgrade.

### Deduplication

Transactions are deduplicated using a SHA-256 hash of six fields:

```text
SHA-256( forwarded_to | institution | amount | company | date | transaction_type )
```

Before writing, `_transaction_exists()` queries DynamoDB for a matching `TransactionHash` under the same `ForwardedTo` partition. **The check fails open** — if the query errors (DynamoDB throttling, network issue), the transaction is written anyway. This prioritizes data capture over strict uniqueness; a duplicate row is less harmful than a lost transaction.

### Timezone handling

All dates are normalized to the configured app timezone (`timezone` key in `data/config.json`, default `America/Los_Angeles`) before storage. The sort key format (`YYYY.MM.DD_HH.MM_filename.eml`) uses this local time, ensuring chronological ordering within each partition.

Because the sort-key prefix is local-time and is written once at ingest, changing `timezone` does **not** rewrite history. New transactions bucket in the new zone; older rows retain their original prefix. For a single-user deployment that stays in one place this is invisible. For users who move continents, midnight-adjacent transactions ingested before the switch may group on the "wrong" calendar day in the Journal until they age out.

The helper lives in `src/finance/app_timezone.py` — `get_app_timezone()` returns a `ZoneInfo` and `get_tzinfos()` produces the `dateutil.parse(tzinfos=…)` map. The map always resolves `PST`/`PDT` to Pacific regardless of configured zone so legacy rows (and test fixtures) continue to parse correctly after a zone switch.

## OpenAI integration

The system uses OpenAI's **function calling** (tool use) to get structured output — not free-text parsing.

### Transaction categorization

The categorization flow has three stages, in order:

1. **Override resolver short-circuit.** `categorize_transactions()` runs the tiered `resolve_override()` matcher against overrides + aliases. If any tier hits, the category is returned immediately without calling OpenAI (see [Category override system](#category-override-system)).

2. **Feature gate.** The OpenAI call is gated on the `ai_categorization_enabled` flag in `data/config.json`. AI categorization is enabled by default when `OPENAI_API_KEY` is set; toggle in Settings → Intelligence to disable it. When disabled, the categorizer returns the `Miscellaneous` fallback without touching OpenAI.

3. **OpenAI call.** If no override matches and the gate is open, the function sends the transaction amount and company to `gpt-5.4-nano` with a forced function call (`categorize_transaction`) that constrains the output to one of 39 predefined categories:

> Alcohol, Auto Maintenance, Baby & Kids, Bank Fees, Car Payment, Charitable Giving, Childcare, Clothing, Coffee & Cafes, Education, Entertainment, Fitness, Gasoline, Gifts, Groceries, Health Care, Hobbies, Home Goods, Home Maintenance, Insurance, Internet, Miscellaneous, Mortgage, Moving, Personal Care, Pets, Phone, Professional Services, Public Transit, Rent, Restaurant/Dining, Rideshare & Taxi, Strata/HOA, Subscriptions, Taxes, Technology, Therapy, Travel, Utilities

Existing users keep whatever list is in their `CategoryConfig` storage — the JSON above is read once on first access for fresh users and then storage takes over.

**Fallback:** If the API call fails, returns no completion, or the response can't be parsed, the category defaults to `"Miscellaneous"`.

### Transaction alert detection

`email_is_transaction_alert()` uses a separate function call (`detect_if_transaction_alert`) to classify whether an email is actually a transaction alert vs. a credit-card payment confirmation or unrelated email. Returns `True`, `False`, or `None` on error.

## Category override system

Known-good company→category mappings are managed via `OverrideService` (DynamoDB-backed) and also persisted to `data/config/category_overrides.json` as a backup. The Lambda pipeline loads overrides and merchant aliases together via `config_loader.py:get_override_context()` — a bundled 5-minute in-memory cache that returns `(overrides, aliases)` and is invalidated by override or alias mutations.

### Tiered resolver (`resolve_override`)

All five override lookup sites — Lambda categorizer, `OverrideService.lookup_category`, statement reconciler, `/fix-categories` dev script, and `CategorySuggester._exact_match` — delegate to `src/finance/category_resolver.py:resolve_override(company, overrides, aliases=None)`. The resolver returns a frozen `ResolvedOverride(category, tier, matched_rule, confidence)` or `None`, applying tiers cheap-to-expensive and returning on the first hit:

| Tier | Method | `source` stamp | Confidence | Available in Lambda? |
|------|--------|----------------|------------|----------------------|
| 0 (exact) | Case-insensitive string equality against override keys | `override` | `1.0` | yes |
| 1 (normalized) | `merchant_normalizer` regex cleanup on both sides — strips store numbers (`#1234`), location markers, province/country codes, punctuation. One `BOOSTER JUICE` override catches every `BOOSTER JUICE #N` variant | `override_normalized` | `1.0` | yes |
| 2 (alias) | Same as Tier 1, plus merchant alias substitution after cleanup. Skipped when aliases is empty | `override_alias` | `1.0` | yes |
| 3 (fuzzy) | Cosine similarity on `CategorySuggester`'s embedded corpus. Threshold `0.85` (reconciler) / `0.90` (automatic paths) | `override_fuzzy` | cosine score | **no** — no embedding imports in Lambda module graph |

**Ambiguity blacklist:** when two override keys collapse to the same normalized (or alias-resolved) key but disagree on category, the group is dropped from that tier's map and falls through to the next. Example: `SHOPPERS DRUG MART #123 → Health Care` vs `SHOPPERS DRUG MART #456 → Groceries` → neither resolves on `SHOPPERS DRUG MART #789`; the transaction falls through to OpenAI.

Tier 3 is available to the webapp and statement reconciler via an optional `suggester` parameter on the resolver (Phase 2; see the dated specs under `docs/specs/` — local-only, absent in the public repo).

### Audit trail

Every resolver hit stamps `CategoryAudit` on the new transaction row at insert time via the new `add_transaction(transaction_data, category_audit=...)` kwarg on both DynamoDB and SQLite backends. The audit map carries `source` (tier-derived), `matched_rule` (original-case override key that fired), `confidence` (Decimal in DynamoDB, REAL in SQLite), and `reviewed_at` (ISO timestamp). Phase 4's duplicates UI reads `matched_rule` to show which override collapsed onto each variant.

SQLite schema backs the audit fields with `category_audit_reviewed_at`, `category_audit_source`, `category_audit_matched_rule` (TEXT), and `category_audit_confidence` (REAL) columns. Added idempotently on connection bootstrap via `_apply_column_migrations()` in `local_db.py`.

### Retroactive category correction

`TransactionsDB` provides two methods for updating historical records:

- **`update_category(forwarded_to, date_file_name, new_category, source)`** — Changes the `Category` attribute and writes a `CategoryAudit` map with `reviewed_at` (ISO timestamp) and `source` (e.g., `"manual"`, `"override"`, `"audit"`). Returns the old category value.
- **`mark_category_reviewed(forwarded_to, date_file_name, source)`** — Writes `CategoryAudit` metadata without changing the category, marking the transaction as audited.

### Slash command workflow

The `/review-categories` and `/fix-categories` slash commands form a review-then-fix pipeline. `/review-categories` analyzes transactions for inconsistencies and updates the overrides file. `/fix-categories` applies those overrides retroactively to DynamoDB and audits the full history. The slash-commands operational guide lives at `docs/guides/slash-commands.md` in the repo.

### Category management services

The category override system is also backed by DynamoDB for webapp access, using two services that share the `CategoryConfig` table (same schema as `BudgetConfig` — PK/SK with optimistic locking).

**`OverrideService`** (`src/finance/override_service.py`) — CRUD for the company→category overrides map. Stores the full map as a single DynamoDB item (`SK = "CONFIG#category_overrides"`). Supports individual put/delete, bulk replace, and suggestion dismissal tracking (a `Dismissed` map on the same item keyed by `company_lower|category_lower`). Every write persists a JSON backup to `category_overrides.json` and `dismissed_suggestions.json`.

**`CategoryService`** (`src/finance/category_service.py`) — CRUD for the master category list. Stores the sorted list as a single DynamoDB item (`SK = "CONFIG#categories"`). Supports add, rename, and delete with case-insensitive uniqueness checks. `Miscellaneous` is protected from rename/delete. Falls back to the local `categories.json` file if DynamoDB is unavailable. Every write persists a JSON backup to `categories.json`.

Both services fall back to their local JSON files (`category_overrides.json`, `categories.json`) when DynamoDB is unavailable, so the self-hosted SQLite path works without provisioning any AWS resources. On the AWS path, the `CategoryConfig` table is created during initial deployment; the one-time setup scripts that were used to bootstrap the original maintainer's account are not part of the public repo.

**API endpoints** (`src/api/routers/overrides.py` and `src/api/routers/category_management.py`):

- `GET /api/v1/overrides` — List all overrides with version
- `PUT /api/v1/overrides/{company}` — Add or update a single override
- `DELETE /api/v1/overrides/{company}` — Remove an override
- `GET /api/v1/overrides/suggestions` — Get category suggestions derived from user edits
- `POST /api/v1/overrides/suggestions/dismissed` — Dismiss a suggestion
- `DELETE /api/v1/overrides/suggestions/dismissed/{key}` — Undismiss a suggestion
- `GET /api/v1/categories/managed` — List categories with version
- `POST /api/v1/categories` — Add a new category
- `PUT /api/v1/categories/{old_name}` — Rename a category
- `DELETE /api/v1/categories/{name}` — Delete a category
- `GET /api/v1/categories/{name}/usage` — Check transaction count before deletion
- `PUT /api/v1/categories/{name}/group` — Update a category's budget group assignment

## Monthly spending summary

The `spending_summary.py:SpendingSummary` class generates monthly spending reports from DynamoDB data.

### How it works

`query_month(year_month)` queries all transactions for a given `YYYY-MM` month by scanning each `ForwardedTo` partition with a `begins_with` filter on the `DateFileName` sort key prefix. Results are aggregated across all partitions.

`aggregate(items)` splits transactions into spending types (purchase, withdrawal, preauth) and deposit types (e-transfer), then computes totals, counts, breakdowns by category and company, and top categories.

`get_summary_with_comparison(year_month)` fetches the current and previous month summaries and calculates month-over-month deltas for total spending and category-level changes.

### Automated SMS notifications

`docker/email_parsing/summary_handler.py` is a separate Lambda handler that automates the monthly SMS. It reuses the same Docker image as the email parser but with a different entry point (`summary_handler.handler`).

An EventBridge Scheduler rule triggers the Lambda on the 8th of every month at 17:00 UTC (10:00 AM PDT during daylight saving, 09:00 AM PST otherwise — the cron expression is fixed in UTC, so the local time shifts seasonally). The handler calls `SpendingSummary.get_summary_with_comparison()` for the previous month, formats the result with `format_sms()`, and publishes it to the same SNS topic used for transaction notifications.

Deployment scripts `7_establish_summary_lambda.sh` and `8_create_schedule.sh` create the Lambda function and schedule respectively.

## AI spending insights

The system generates AI-powered spending briefings via Claude Code CLI. Generation runs as a background task; the frontend polls for status.

### How it works

1. **Context gathering** — `src/finance/insights_context.py:gather_context()` assembles a comprehensive spending snapshot: current + previous month comparison (via `SpendingSummary`), 6-month trend, budget targets and year-to-date totals (via `BudgetService`), and historical category averages. All `Decimal` values are converted to `float` for JSON serialization. The context is written to `data/insights/context_<YYYY-MM>.json`.

2. **Background-task generation** — `POST /api/v1/insights/generate` (`src/api/routers/insights.py`) gathers the context and kicks off a background generation task that spawns a Claude CLI subprocess (`claude -p <prompt> --output-format text --model <model> --no-session-persistence`, via the shared transport in `src/finance/ai_cli.py`) with a 180-second timeout. The endpoint returns 202 with a task id. The frontend polls `GET /api/v1/insights/status` until the task completes, then reads the result via `GET /api/v1/insights/saved/{id}`.

3. **Saved briefings** — Completed briefings (>200 chars) are persisted to `data/insights/<YYYY-MM>/<timestamp>.md`. Two additional endpoints serve saved briefings: `GET /api/v1/insights/saved?month=YYYY-MM` (list) and `GET /api/v1/insights/saved/{id}?month=YYYY-MM` (retrieve).

### Slash command

The `/spending-insights [YYYY-MM]` slash command provides an offline alternative — it runs the same `gather_context()` pipeline, then Claude Code generates the briefing directly in the conversation rather than via a subprocess.

## Spending journal

The Spending Journal is a day-grouped transaction timeline that surfaces the per-transaction enrichment written by `TransactionContextEnricher` (`category_budget_pct`, `merchant_month_count`) directly in the UI, and pairs each day with an AI-generated narrative summary.

### How it works

1. **Day grouping** — `GET /api/v1/journal?month=YYYY-MM` (`src/api/routers/journal.py`) queries the month's transactions, filters out deleted/ignored rows, and groups them by the `YYYY.MM.DD` prefix of the `DateFileName` sort key. Days are ordered descending (newest first) but MTD totals are accumulated ascending so each day carries a running month-to-date figure. The budget ceiling (annual target ÷ 12) is attached when configured.

2. **Daily context gathering** — `src/finance/daily_summary_context.py:gather_daily_contexts()` takes the day-grouped list and builds a compact context dict per day: `day_of_week`, `day_total`, `transaction_count`, top merchants, `mtd_total`, top MTD categories, and budget ceiling. These dicts feed the AI prompt.

3. **Multi-provider summary generation** — `src/finance/summary_provider.py` exposes four implementations of a `SummaryProvider` ABC:
   - `OpenAISummaryProvider` — uses `instructor` + OpenAI for structured per-day output (one API call per day).
   - `ClaudeCLISummaryProvider` — spawns the Claude Code subprocess with a single batched prompt containing all days, then parses the response back into per-day summaries.
   - `CodexCLISummaryProvider` — spawns the OpenAI Codex CLI subprocess with the same single-batched-prompt approach.
   - `GeminiCLISummaryProvider` — spawns the Google Gemini CLI subprocess with the same single-batched-prompt approach.
   `create_summary_provider()` dispatches based on `data/config.json`'s `daily_summary_provider` field (`"openai"`, `"claude_cli"`, `"codex"`, `"gemini_cli"`, or `"disabled"`), threading the optional `daily_summary_model` / `daily_summary_reasoning_effort` overrides into the chosen provider (see [`configuration.md`](guides/configuration.md)).

4. **Background generation** — `POST /api/v1/journal/summaries/generate` kicks off an `asyncio.Task` tracked in module-level state (single-slot; returns HTTP 409 if a job is in flight). As each day completes, the summary text is written to `data/journal/<YYYY-MM>/<DD>.txt`. `GET /api/v1/journal/summaries/status` reports progress; `GET /api/v1/journal/summaries?month=YYYY-MM` returns the full saved set.

The frontend Journal page (`frontend/src/pages/JournalPage.tsx`) renders each day as a card with the transactions, inline enrichment badges, a waveform pace bar, and the AI summary (collapsible). Auto-generation is scoped to the current day only.

## Cash-flow Sankey (Summary → Flow view)

The Summary page's Flow view renders a Sankey diagram for the selected month: income sources split proportionally between a `Spending` hub (feeding the expense parent groups) and a `Kept` sink; when spending exceeds income, a `From savings` source covers the deficit. A three-figure strip above the diagram (`Income` · `Spent` · `Kept`, or `From savings` in a deficit month) always sums exactly.

### How it works

1. **Backend** — `GET /api/v1/summary` returns `deposits_by_company` alongside the existing aggregates. The aggregator already computed it; the `DepositSourceSummary` Pydantic model exposes it on the response. The same endpoint also carries the nullable `pace: MonthPaceInfo` block (populated only when the requested month is the current one) that drives the Summary page's mid-month cards and the chart's hatched projection. No dedicated endpoint and no DB writes — the Sankey is a frontend roll-up over `/summary` plus `/category-management` group assignments.

2. **Graph builder** — `frontend/src/lib/cashFlow.ts:buildCashFlowGraph()` joins deposits, category spend, and group memberships into the `{ nodes, links }` shape `@visx/sankey` expects, splitting each income source between spending and kept with cent-exact allocation. Pure function, no React; covered by `cashFlow.test.ts`.

3. **Render** — `SankeyCashFlow.tsx` (rendered by `SummaryPage.tsx`'s Flow view) uses `@visx/sankey` + `@visx/responsive`, with theme-aware palette via `getGroupColor` + `useChartTone`. Mobile (<768px) falls back to a text breakdown so narrow screens don't render an unreadable diagram.

Phase A (this section) ships an MVP. Phase B — drill-down, dedicated endpoint, year scope, two-layer expense breakdown, and folding `IncomeStatement` into a tab — is captured in `docs/specs/_archive/2026-04-26-sankey-cash-flow-research/handoff-phase-b.md` (a local-only spec, absent in the public repo).

## Merchant intelligence (`/merchants`)

The `/merchants` page surfaces structured recurring-charge detection, price-change alerts, and committed burn rate — separate from the AI narrative briefing on `/insights`.

### How it works

1. **`merchant_intelligence.py:MerchantIntelligenceService`** — runs over 6 months of `by_company` data from `SpendingSummary` (no new storage, 1-hour in-memory cache). Computes:
   - **Recurring detection** — fixed (same amount every month, ≥3 months) and variable (charged most months, ≥4 of 6).
   - **Price-change alerts** — recurring merchants whose latest amount drifted ≥5% AND ≥$1 from prior baseline.
   - **New / churned classification** — first appearance this month, or absent after recurring payments end.
   - **Committed burn rate** — sum of recurring monthly amounts, exposed alongside discretionary spend.

2. **`GET /api/v1/merchants/intelligence?month=YYYY-MM&months=6`** (`src/api/routers/merchants.py`) returns the structured payload. Demo mode computes the same shape on the fly from summary fixtures.

3. **Frontend** — `MerchantsPage.tsx` renders `MerchantSummaryCards` (committed vs. discretionary, counts), `RecurringMerchantsList` (fixed/variable with monthly amounts), and `MerchantAlerts` (price changes, new, stopped). Brand voice: "notable changes" not "alerts"; sentence case throughout.

This page executes the `2026-02-24-merchant-intelligence` spec end-to-end and Phase 2 of `2026-04-26-gentle-insights-implementation`.

## Design decisions

**Fail-open deduplication** — If the DynamoDB duplicate check fails (network error, throttling), the transaction is written anyway. Rationale: a duplicate row can be cleaned up later, but a lost transaction is unrecoverable. Financial data capture is prioritized over strict uniqueness.

**Two-phase institution detection** — Sender domain first, body text fallback. Forwarded emails may not preserve the original sender. Interac e-transfers all come from `payments.interac.ca` regardless of originating bank, so body text is the only way to distinguish them.

**Container-based Lambda** — The Docker image is built from the repo root (`docker build -f docker/email_parsing/Dockerfile .`) so it can include `src/` directly. The `OPENAI_API_KEY` is loaded at runtime from SSM Parameter Store via `src/finance/secrets.py` (SSM → env var → `data/.env` → project-root `.env` fallbacks for local/CI use), never baked into the image.

**Function calling for categorization** — Using OpenAI's tool use with an enum constraint guarantees the response is one of the predefined categories. No free-text parsing or fuzzy matching needed. The `Miscellaneous` fallback handles any failure mode gracefully.

**Category overrides** — Known-good company→category mappings in `category_overrides.json` short-circuit the OpenAI API call. This reduces latency and cost for recurring merchants while ensuring consistent categorization. The `/review-categories` slash command maintains the override file.

**Blocked companies for SMS** — Recurring subscription charges from specific companies (e.g. YouTube, a paid newsletter) are suppressed from SMS to reduce notification fatigue. Unknown transaction types are also suppressed.

## Statement import

The statement import system fills gaps in the email-based pipeline by parsing bank statement PDFs and importing missing transactions.

### Parser system

`src/finance/statement_parser.py` defines the `StatementParser` base class, `StatementParseResult`, and the `select_parser()` auto-detection helper. Institution-specific parsers live in `src/finance/parsers/` and are re-exported from `statement_parser.py` for backward compatibility:

- **`RBCChequingParser`** (`src/finance/parsers/rbc_statement_parser.py`) — RBC chequing account statements (single date column, CamelCase descriptions)
- **`SimpliiChequingParser`** (`src/finance/parsers/simplii_statement_parser.py`) — Simplii Financial chequing account statements (two date columns: trans. date + eff. date, clean text descriptions)

Each parser extends `StatementParser` and produces a `StatementParseResult` with transactions, metadata, and raw/cleaned descriptions.

**Auto-detection:** `select_parser(pdf_bytes)` inspects the first two pages for Simplii markers (`"simplii"` in text or `"trans."` header word) and returns the appropriate parser. Defaults to `RBCChequingParser` if no Simplii markers are found or on error. The API upload and reparse endpoints use `select_parser()` automatically.

Description cleanup (`clean_statement_description()`) strips known prefixes like `BillPayment`, `InteracPurchase`, `ATMwithdrawal`, etc., and applies CamelCase splitting. A `_PREFIX_DISPLAY_NAMES` dict maps prefixes that ARE the entire description (e.g., `Monthlyfee` → `Monthly fee`). Simplii descriptions are already clean text, so cleanup is near-no-op.

### Four-tier reconciliation

`src/finance/statement_reconciler.py` matches parsed transactions against existing DynamoDB records:

1. **Tier 1 (Exact):** Same date + same amount (±$0.01) + compatible type → auto-matched
2. **Tier 2 (Suspected Duplicate):** Cross-type match (e.g., withdrawal vs e-transfer) + same direction → flagged for review
3. **Tier 3 (Fuzzy):** Date ±2 days + same amount + compatible type → flagged as ambiguous
4. **Tier 4 (New):** No match found → offered for import with category suggestion from overrides

Type mapping: statement `withdrawal` matches DB `purchase`, `withdrawal`, `preauth`; statement `deposit` matches DB `e-transfer`, `deposit`. A direction filter (`_same_direction()`) rejects cross-type matches when transactions flow in opposite directions. Used-key tracking prevents double-matching.

### Statement-specific DynamoDB fields

Statement-imported transactions use a subset of the Transactions schema:

- **DateFileName:** `YYYY.MM.DD_00.00_stmt_RBC_<hash8>.pdf` — synthetic sort key with `stmt_` prefix
- **Date:** `MM/DD/YYYY 00:00 PST` — synthetic format for compatibility
- **StatementSource:** e.g., `RBC_Chequing_2026-01` — identifies the source statement
- **CategoryAudit:** `{"reviewed_at": "<ISO>", "source": "statement_import"}`
- **TransactionHash:** Uses raw description (not cleaned) for hash stability. When multiple identical transactions occur on the same day (same date, amount, description, type), an occurrence counter suffix (`|1`, `|2`, ...) is appended before re-hashing to produce distinct `TransactionHash` and `DateFileName` values. Occurrence 0 (the first) is unchanged for backward compatibility.

Email-specific fields (`FromName`, `FromEmail`, `ToName`, `ToEmail`, `Subject`, `Body`, `FileName`) are omitted.

### SQLite persistence

`src/finance/statement_store.py` provides a SQLite persistence layer (WAL mode) so users can resume partially-completed imports and view upload history. Three tables: `schema_version`, `statements`, `statement_transactions`. Default actions are assigned per reconciliation tier (new→import, matched→enrich/skip). Status is computed from action states: `pending_review` → `in_progress` → `complete`.

### API endpoints

- `POST /api/v1/statements/upload` — Upload PDF, parse, reconcile, and persist to SQLite
- `GET /api/v1/statements` — List all uploaded statements with status and counts
- `GET /api/v1/statements/{statement_id}` — Retrieve statement detail with all transactions
- `DELETE /api/v1/statements/{statement_id}` — Delete a statement and its transactions
- `PATCH /api/v1/statements/{statement_id}/transactions/{tx_index}` — Update a single transaction (action, company, category)
- `PATCH /api/v1/statements/{statement_id}/transactions` — Bulk-update multiple transactions
- `POST /api/v1/statements/{statement_id}/reparse` — Re-parse PDF preserving user edits
- `POST /api/v1/statements/import` — Execute import actions for reviewed transactions

Uploaded PDFs are saved to `data/raw/statements/<institution>/`.

## Attachments and receipts

Any transaction can carry file attachments — a receipt photo, an invoice, a claim letter. Attachments are the evidence layer under the tax pack: a bank alert proves you *paid*; the receipt proves *what you bought*.

### Storage

`src/finance/attachment_store.py` is a single SQLite store (`data/attachments.db`, WAL mode) on the StatementStore template — deliberately **not** a dual-backend pair, because attachment files live on the server's disk regardless of the transaction backend. Rows persist the transaction composite (`forwarded_to`, `date_file_name`); the `tx_id` surrogate exists only at the API boundary (`Depends(parse_tx_id)`). Attachment ids are deterministic (`att_` + 16 hex of `sha256(file_sha256|original_filename)`), so re-uploading the identical file upserts. Files land at `data/raw/attachments/<YYYY-MM>/<id>_<sanitized name>`; accepted uploads are JPEG/PNG/WebP/HEIC/PDF up to 10 MB, validated on both extension and declared content-type, with HEIC/HEIF converted to JPEG at upload (the stored content-type is always ours, never the client header). Demo mode uses its own empty `data/demo-attachments.db`.

### Receipt parsing (AI, opt-in)

`src/finance/receipt_parser_ai.py` turns a receipt into `{merchant, date, total, line_items?}` using the provider already selected in Settings → Intelligence (`resolve_ai_statement_provider()` is reused, not forked). Text PDFs go through pdfplumber text; images are the codebase's first vision path — OpenAI gets one multimodal message with a base64 data URL, Codex gets `-i <path>`, Claude Code gets the file path in the prompt plus `--allowedTools Read`; Gemini image input is deferred. Validation is fail-closed (`validate_receipt_parse`, pure): merchant/date/total are required, a text-PDF's total must appear verbatim in the extracted text, and line items are advisory — if they don't reconcile with the total within $0.05 they are dropped while the parse survives. Line items live only in the attachment row's `parse_json` and render only in the attachment view dialog; they are never aggregated. Parsing is gated by the `ai_receipt_parsing_enabled` consent (default off, never auto-enabled) and every successful parse carries a provenance stamp (`method`, `provider`, `model`, `parsed_at`, `schema_version`).

### Matching

`src/finance/receipt_matcher.py` ranks the transactions a parsed receipt could explain — the same tier-ranked reconciliation shape as statement import, scoped to one receipt. T1 = exact amount (±$0.02) + same day + normalized-merchant equality; T2 = amount within tolerance + within a 3-day window; T3 = the restaurant-tip band (up to +20%) within the window. The matcher is pure (no storage imports); the candidates endpoint feeds it the receipt month's raw transactions (plus the adjacent month near a boundary). An unlinked receipt with exactly one T1 candidate auto-links; everything else is user-confirmed. Unmatched receipts never create transaction rows — they wait in the "Receipts to file" list on the Transactions page.

### API endpoints

- `POST /api/v1/attachments` — multipart upload, optionally linked via a `tx_id` form field
- `GET /api/v1/attachments?unlinked=true&kind=receipt` — list with optional filters
- `GET /api/v1/transactions/{tx_id}/attachments` — a transaction's attachments
- `GET /api/v1/attachments/{id}/file` — serve the file inline
- `POST /api/v1/attachments/{id}/parse` — synchronous AI parse (422 when consent is off)
- `GET /api/v1/attachments/{id}/candidates` — ranked match candidates; performs the auto-link
- `POST /api/v1/attachments/{id}/link` — link to a transaction (`tx_id: null` unlinks)
- `DELETE /api/v1/attachments/{id}` — remove the row and the file on disk

## Tax pack

The `/tax` page ("Tax receipts") groups a calendar year's spending into claim lines with per-transaction evidence status, and exports the whole thing as a zip.

### How it works

1. **Mapping seed** — `src/finance/config/tax_line_mappings.json` maps seven lines (charitable, medical, childcare, moving, tuition, dues, instalments) to categories from the built-in taxonomy. It reads through `config_loader._config_path()`, so a personal copy in `data/config/` wins over the packaged seed; a category claimed by two lines fails at load. `note` is an informational string rendered verbatim. `cra_ref` (a country-specific line reference, e.g. Canada's "Line 34900") remains in the seed for self-hosters who want it, but is **no longer shown in the UI or the CSV export** — the labels are the country-neutral surface.
2. **Service** — `src/finance/tax_pack_service.py:TaxPackService.get_tax_pack(year)` walks the year's twelve months via `query_month`, keeps spending-type rows, and buckets by **lowercased** category (stored rows carry `"charitable giving"`, the seed says `"Charitable Giving"`). Evidence per transaction: `receipt` (a receipt-kind attachment links to the composite, bulk-probed in one query), `statement` (`StatementSource` present — no source email exists), or `email` (the source alert rides on the row). The pack computation reads transactions but is layered over a small override store (next point).
3. **Manual overrides** — membership is *(category-derived ∪ manually-included) − manually-excluded*. `src/finance/tax_override_store.py:TaxOverrideStore` is a single SQLite store (`data/tax_overrides.db`, WAL, on the attachment-store template — SQLite-only, not a dual-backend pair) keyed by the transaction composite, holding one row per override: `mode` (`include`|`exclude`) plus a target `line_key` for includes. `POST /api/v1/tax-pack/items` flags a transaction into a line (used by the "Flag as tax item" menu on the Journal and Transactions rows); `DELETE /api/v1/tax-pack/items/{tx_id}` clears an override (removes a manual flag or restores an excluded item). An included item whose category isn't mapped — or any include targeting `"other"` — lands in a synthetic **"Other claimable"** line that only appears when populated. Excluded derived members move to their line's `excluded_transactions` and stop counting toward totals/coverage. Both mutations are demo-gated.
4. **Export** — `GET /api/v1/tax-pack/export?year=` streams an in-memory zip: `summary.csv`, one `lines/<key>.csv` per claim line, attachment files under `evidence/<key>/`, and the source email body as `.txt` for email-evidence rows. Disabled in demo mode.

The page itself is the income-statement skeleton — year picker, expandable lines, evidence chips, a "Download tax pack" button — with a fixed footer: "Tidings organizes your records; it doesn't give tax advice." Each line's rows carry per-item actions: view the source email, view attached receipts, attach a new one, and remove the item (with a restorable "Removed" section per line).

## Agent activity ledger

Every 2xx non-GET request under `/api/v1/*` (outside `/api/v1/auth/` and four
write-verbed reads) is journaled to an append-only ledger. The pieces:

- **Principal resolution** — `src/api/auth.py` resolves the caller on every
  request (`Principal`: token / session / tofu / dev-bypass) and stashes it on
  `request.state.principal`. Successful bearer auth also stamps the token's
  `last_used_at`, throttled to once per 15 minutes.
- **Capture** — inside `bearer_auth_middleware` (deliberately not a second
  middleware: Starlette registration order would put it outside auth). After
  `call_next`, `src/api/activity.py` builds an envelope from the request scope
  only — bodies are never read, so multipart uploads and streaming responses
  pass through untouched — and dispatches the store write fire-and-forget
  (`asyncio.to_thread` task held in a strong-ref set; fail-open; zero response
  latency).
- **Before/after images** — ten instrumented handlers (transaction
  patch/comment/fields/bulk, override put/delete, alias put/delete, budget
  config, groups) call `stage_before()` with the pre-mutation state and the
  value being written; everything else is captured envelope-only,
  `reversible: false`. Bulk images use a minimal per-row projection capped at
  200 rows (a ledger entry is one DynamoDB item under the 400 KB limit).
- **Store** — `ActivityStore` / `ActivityStoreLocal`
  (`src/finance/activity_store*.py`), the standard dual-backend pair
  (migration 004). Append-only API; 90-day retention on both backends
  (SQLite prune-on-write, DynamoDB TTL).
- **Endpoints** — `GET /api/v1/whoami` (caller introspection),
  `GET /api/v1/activity` (filtered feed), `POST /api/v1/activity/{id}/revert`
  (`src/api/activity_revert.py` dispatch; stale-guard compares the entry's
  after-image against current state and 409s rather than clobber a newer
  edit; the revert is itself journaled and linked off the response path).
- **UI** — Settings → Activity: the feed grouped by principal and 10-minute
  burst, expandable before/after, inline-confirm revert.

## Advanced: AWS serverless variant

The AWS path uses the same parser, categorizer, and override system as the self-hosted path, but swaps the transport and storage layers:

- **Transport.** SES → S3 → Lambda. Bank emails arrive via SES inbound, land as `.eml` objects in an S3 bucket, and trigger the Lambda function on each new object. See [Email-to-S3 setup](https://docs.gettidings.com/self-hosting/email-to-s3/) for the SES + DNS + bucket policy walkthrough.
- **Storage.** DynamoDB tables (`Transactions`, `BudgetConfig`, `CategoryConfig`) replace the SQLite file. Schema definitions are in the Data storage section above; both backends share the same field names.
- **Notifications.** SNS publishes SMS messages to your phone number; the same notification message format is used as the self-hosted Ntfy/Twilio paths.
- **Deployment.** A set of numbered shell scripts in `docker/email_parsing/` automate ECR image build/push, Lambda function creation, and EventBridge schedule for the monthly summary job. See [AWS deployment](https://docs.gettidings.com/self-hosting/aws/) for the full sequence.

Code volume favours the self-hosted path: `imap_poller.py` is ~575 lines with 50 unit tests; `lambda_function.py` is ~135 lines with 13 unit tests. The Lambda handler is intentionally thin because it delegates everything to shared `src/finance/` modules.

## Configuration

| Setting | Location | Notes |
|---------|----------|-------|
| `OPENAI_API_KEY` | SSM Parameter Store (`/email-parser/openai-api-key`) | Loaded via `src/finance/secrets.py` tiered loader: SSM → env var → `data/.env` → project-root `.env`. Lambda returns HTTP 500 if missing |
| AWS credentials | IAM role / env | S3, DynamoDB, SNS, Lambda access |
| SNS topic ARN | `lambda_function.py` | Hardcoded; update when changing regions |
| User mappings | `src/finance/user_mappings.csv` | Maps `ForwardedTo` → `UserId`; cached in memory |
| OpenAI model | `lambda_function.py` | `DEFAULT_OPENAI_CHAT_MODEL` (`gpt-5.4-nano`, `src/finance/ai_cli.py`) is the fallback for every OpenAI-path feature; each feature's `*_model` config key overrides it (see [`configuration.md`](guides/configuration.md)) |
| Category overrides | `src/finance/config/category_overrides.json` | Company→category map; short-circuits OpenAI |
| Categories enum | `src/finance/config/categories.json` | 39 predefined categories for OpenAI function call |
| Blocked companies | `src/finance/config/blocked_companies.json` | Companies suppressed from SMS notifications |
| Card name mappings | `src/finance/config/card_name_mappings.json` | Maps card last-4 digits → cardholder first name |
| Budget config backup | `src/finance/config/budget_config.json` | Local JSON backup of BudgetConfig DynamoDB items |
| Dismissed suggestions | `src/finance/config/dismissed_suggestions.json` | Override suggestions dismissed by user; prevents re-suggestion |
| CI/CD | `.github/workflows/ci.yml` | Lint + test on push/PR to `main` |
