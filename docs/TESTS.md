# Testing Guide

## Quick Start

```bash
make test                                # all backend unit tests (with coverage report, no gate)
make test-ci                             # all backend unit tests with the 90% branch-coverage gate (pre-deploy)
make verify                              # the full regression gate: canon links + backend + frontend + e2e + openapi + demo API
make test-fast                           # all backend unit tests, no coverage (fastest loop)
uv run pytest tests/unit/test_rbc_parser.py -v   # narrow a run to one file (no false coverage fail)
uv run pytest tests/integration/ -m integration  # integration tests (needs OPENAI_API_KEY)
cd frontend && pnpm test                 # frontend tests (Vitest)
```

The 90% coverage gate (branch coverage — an untaken `if`/`else` edge counts as a miss; configured in `[tool.coverage.run]`) lives only in `make test-ci` (and its `make verify-backend` superset), so narrow-scope runs (e.g., a single test file) don't fail with a spurious coverage failure. `make test-ci` is the backend slice; **`make verify` is the authoritative full gate** — it is what CI runs and what CONTRIBUTING and the release ritual mean by "the tests pass."

The full-suite make targets (`test` / `test-ci` / `test-fast`) fan out across
cores via pytest-xdist (`-n auto`, ~7× on a many-core box; adapts to 4-core CI
runners). Serial escape hatch: `make test-ci PYTEST_WORKERS=0`. xdist is
deliberately kept out of pytest `addopts`, so ad-hoc
`uv run pytest path/to/file.py` runs stay serial — no worker spin-up tax on the
narrow-loop iteration the previous paragraph describes.

## Unit Tests

Unit tests cover the full processing pipeline. The table below is a map,
not a manifest — new test files land faster than it updates; `ls tests/unit/`
is the authoritative inventory.

| Test File | What It Covers |
|-----------|---------------|
| `test_rbc_parser.py` | RBC parser — purchases, withdrawals, e-transfers |
| `test_cibc_parser.py` | CIBC parser — purchases, preauth payments |
| `test_mbna_parser.py` | MBNA parser — purchases |
| `test_pc_financial_parser.py` | PC Financial parser — purchases |
| `test_simplii_parser.py` | Simplii parser — e-transfers |
| `test_parser_errors.py` | All parsers — malformed/empty input handling |
| `test_institution_detection.py` | Sender-domain and body-text institution routing |
| `test_email_extraction.py` | Timezone conversion, user-mapping, forwarded-to |
| `test_openai_categorization.py` | Mocked categorization fallback/error paths |
| `test_lambda_handler.py` | Lambda handler decision branches (mock-level) |
| `test_transaction_dedup.py` | Hash generation, duplicate detection, fail-open |
| `test_transaction_schema.py` | DynamoDB item schema, Decimal conversion |
| `test_config.py` | Config loader caching behavior |
| `test_spending_summary.py` | SpendingSummary — aggregation, month queries, comparison |
| `test_summary_handler.py` | Monthly-summary Lambda handler — SNS publish, date logic |
| `test_transaction_db_update.py` | Category updates, audit metadata, mark-as-reviewed |
| `test_budget_service.py` | BudgetService — CRUD, type inference, historical averages, caching |
| `test_api_budget.py` | Budget API — config CRUD, pace status, historical averages, 409 conflict |
| `test_api_categories.py` | Categories API — predefined category list endpoint |
| `test_api_summary.py` | Summary API — monthly spending summary and trend endpoints |
| `test_api_transactions.py` | Transactions API — listing, filtering, category/comment updates, ignored flag |
| `test_api_insights.py` | Insights API — background-task generation with status polling |
| `test_transaction_db_comment.py` | DynamoDB comment operations — SET/REMOVE expression building |
| `test_transaction_db_delete.py` | Soft delete (set_deleted) and permanent delete operations |
| `test_transaction_context.py` | TransactionContextEnricher — month-to-date spending, budget lookup, fail-open |
| `test_email_pipeline.py` | Full email parsing pipeline — end-to-end parse_email with mocked OpenAI |
| `test_statement_parser.py` | Statement PDF parser — description cleanup, PDF validation, RBC parsing, Simplii parsing, parser auto-detection |
| `test_statement_reconciler.py` | Four-tier reconciliation — exact/suspected duplicate/fuzzy/new matching, direction filter |
| `test_transaction_db_statement.py` | Statement transaction DB writes — synthetic keys, dedup, CategoryAudit |
| `test_api_overrides.py` | Overrides API — DynamoDB-backed override CRUD, suggestions, dismissals |
| `test_category_service.py` | CategoryService — DynamoDB-backed category CRUD with optimistic locking |
| `test_override_service.py` | OverrideService — CRUD with DynamoDB and JSON backup |
| `test_api_category_management.py` | Category management API — category CRUD, version conflict |
| `test_statement_store.py` | StatementStore — SQLite persistence for statement imports |
| `test_api_statement_persistence.py` | Statement persistence API — list, detail, delete, patch, reparse |
| `test_api_statements.py` | Statement API — upload/parse/reconcile, import actions, source badge |
| `test_statement_dedup.py` | Statement dedup fix — PDF fixture parsing, hash uniqueness for same-day duplicates, import pipeline |
| `test_income_statement_service.py` | IncomeStatementService — aggregation, category type classification, projection |
| `test_merge_details.py` | merge_details, extract_email_body, extract_forwarded_message_details in parser_base / email_parser |
| `test_embedding_cache.py` | SQLite embedding cache — pack/unpack vectors, storage, retrieval |
| `test_merchant_normalizer.py` | Merchant name normalization — store number stripping, location cleanup |
| `test_category_suggest.py` | Embedding-based category suggestion — cosine similarity, CategorySuggester |
| `test_category_resolver.py` | Tiered category override resolver — exact/normalized/alias tiers, ambiguity blacklist, tier ordering |
| `test_api_search.py` | Search API — cross-month transaction search and CSV export |
| `test_merchant_alias_service.py` | MerchantAliasService — DynamoDB-backed alias CRUD |
| `test_api_income_statement.py` | Income statement API — yearly aggregation endpoint |
| `test_api_groups.py` | Category groups API — group CRUD with version conflict handling |
| `test_api_journal.py` | Journal API — day-grouped transaction timeline endpoint |
| `test_api_daily_summaries.py` | Daily summary API — generate/status/retrieve endpoints, background task orchestration |
| `test_api_error_schema.py` | Unified error envelope — `{error, code, details}` handler output for plain `HTTPException`, `RequestValidationError`, and custom `ApiException` code preservation |
| `test_api_transactions_bulk.py` | Bulk category update API — success, partial failure, empty list, malformed body validation, default source |
| `test_daily_summary_context.py` | Daily summary context builder — per-day context dict assembly for AI summaries |
| `test_summary_provider.py` | Dual-provider AI summary generation — OpenAI API and Claude CLI providers |
| `test_imap_poller.py` | IMAP polling daemon — orchestration logic, UID persistence, message processing |
| `test_transaction_db_local.py` | TransactionsDBLocal — SQLite-backed transaction storage |
| `test_spending_summary_local.py` | SpendingSummaryLocal — SQLite-backed spending aggregation |
| `test_transaction_context_local.py` | TransactionContextEnricher end-to-end against SQLite backend (no mocks) |
| `test_local_db.py` | SQLite connection setup — WAL mode, busy_timeout, foreign keys, schema init |
| `test_secrets.py` | Tiered secret loader — SSM → env → .env fallback chain and `lru_cache` behavior |
| `test_api_config.py` | `/api/v1/config` read + update — `ai_categorization_enabled` privacy flag round-trip, isolated `data/config.json` |
| `test_api_health.py` | `/api/v1/health` liveness probe — status thresholds (ok/degraded/stale), IMAP heartbeat age, last-transaction freshness |
| `test_api_overrides_duplicates.py` | `GET /api/v1/overrides/duplicates` + `POST /api/v1/overrides/consolidate` — unanimous-group detection, atomic optimistic-lock consolidation |
| `test_api_overrides_match.py` | `GET /api/v1/overrides/match` — preview-match hint widget endpoint, Tier 0/1/2 + optional Tier 3 embedding fallback |
| `test_budget_service_local.py` | BudgetServiceLocal — SQLite-backed budget config CRUD parity with DynamoDB, version conflicts |
| `test_category_service_local.py` | CategoryServiceLocal — SQLite-backed category list CRUD parity with DynamoDB |
| `test_override_service_local.py` | OverrideServiceLocal — SQLite-backed override CRUD parity with DynamoDB |
| `test_date_edge_cases.py` | Date boundary handling — leap-year, DST transitions, year rollover in `extract_basic_details()` |
| `test_demo_loader.py` | demo_loader — SQLite seed data loader for open-source demo mode, transaction date format validation |
| `test_migrations.py` | Versioned SQLite migration runner (`src/finance/migrations`) — idempotency, version tracking, failure modes |
| `test_notification_service.py` | NotificationService — SNS / Ntfy / log-only providers, blocked-companies filter, formatting parity with prior Lambda `send_sms()`, fail-open behavior |
| `test_api_data.py` | Data export/backup API — admin export and DynamoDB → SQLite migration endpoints |
| `test_app_timezone.py` | App timezone helper — `get_app_timezone()` ZoneInfo + `get_tzinfos()` PST/PDT mapping under config switches |
| `test_category_icon_service_local.py` | CategoryIconServiceLocal — SQLite-backed category icon CRUD, defaults |
| `test_category_icons_parity.py` | Category icon defaults parity — every category in `categories.json` has a default icon mapping |
| `test_data_backup.py` | Data backup helpers — JSON snapshot writers used by config services for disk persistence |
| `test_dependencies_lazy_singleton.py` | API dependency factories — lazy-singleton behavior, per-process caching, factory swapping |
| `test_merchant_alias_service_local.py` | MerchantAliasServiceLocal — SQLite-backed merchant alias CRUD parity with DynamoDB |
| `test_merchant_intelligence.py` | MerchantIntelligenceService — recurring detection, price-change alerts, new/churned classification, committed burn rate |
| `test_storage.py` | Storage factory — backend selection (DynamoDB vs SQLite), credential probe, demo-mode override |
| `test_parser_base.py` | `parser_base.parse_amount` — currency/amount string parsing helper |
| `test_transaction_hash.py` | `transaction_hash.py` — dedup hash generation (64-char lowercase SHA-256 digest) |
| `test_tx_id.py` | `tx_id` surrogate-id helpers — derive/parse the stable transaction id |
| `test_category_audit.py` | `category_audit.py` — build + normalize the v2 `CategoryAudit` dict |
| `test_api_audit_normalization.py` | API-layer `CategoryAudit` v2 normalization — audit shape on transaction responses |
| `test_extractor.py` | AI transaction extraction (`extractor.py`) — mocked forced tool call, verbatim anti-hallucination validation |
| `test_parse_recovery.py` | Shared parse-failure recovery / quarantine gate — relevance gate, AI fallback, fail-open behavior |
| `test_parse_failure_store.py` | Dual-backend contract for the parse-failure (dead-letter) store |
| `test_api_parse_failures.py` | Parse-failures API — dead-letter quarantine list/detail/retry/dismiss/resolve endpoints |
| `test_api_ingestion.py` | Ingestion API (`ingestion.py`) — manual transaction add and `.eml` upload |
| `test_ai_client.py` | AI provider router (`ai_client.py`) — provider selection, Codex availability + login state |
| `test_chatgpt_oauth.py` | Codex CLI device-auth wrapper (`chatgpt_oauth.py`) — start/status/disconnect subprocess flow |
| `test_forecast_service.py` | Spending forecast engine — cumulative-fraction tables + end-of-month projection math |
| `test_category_icon_service.py` | `CategoryIconService` (DynamoDB) — icon CRUD, allowlist, version lock |
| `test_default_categories_groups.py` | Default category/group consistency — every default category lives in exactly one default group |
| `test_dual_backend_contract.py` | Behavioral contract across the dual-backend service pairs |
| `test_summary_provider_cli.py` | `SummaryProvider` CLI / subprocess paths — Claude CLI batched-prompt handling |
| `test_daily_summary_scheduler.py` | Daily summary scheduler — auto-generation scheduling scoped to the current day |
| `test_imap_poller_idle.py` | IMAP poller idle path — `main()` no-new-mail branch |
| `test_transaction_db_admin.py` | DynamoDB `Transactions` table DDL helpers — table create/describe |
| `test_demo_clock.py` | `DEMO_TODAY` world-clock override — pinned demo-mode clock |
| `test_logging_config.py` | `src/api/logging_config.py` — logger setup |
| `test_agent_tokens.py` | Agent-token persistence layer — `data/config.json`-backed token CRUD, cache reset |
| `test_agent_token_cli.py` | `scripts/agent/agent_token.py` CLI — token issue/list/revoke command surface |
| `test_auth_session.py` | Pure `auth_session` helpers — session token hashing/validation |
| `test_api_auth_endpoints.py` | `/api/v1/auth/*` endpoints — login + session cookie rotation (Phase 4) |
| `test_api_auth_middleware.py` | Bearer-auth middleware — scope enforcement, token validation |
| `test_api_headless_toggle.py` | Headless deployment toggle (Phase 0) — `SERVE_FRONTEND` / `CORS_ALLOWED_ORIGINS` env behavior |
| `test_api_merchant_aliases.py` | Merchant aliases API — alias CRUD endpoints |
| `test_api_category_management_cascade.py` | Category-management cascade helpers — rename/delete cascade across overrides + groups |
| `test_api_search_by_filter.py` | `POST /api/v1/transactions/search-by-filter` — structured filter search |
| `test_api_transactions_patch.py` | `PATCH /api/v1/transactions/{tx_id}` — partial transaction updates |
| `test_api_transactions_stable_id.py` | `tx_id`-shaped transaction endpoints + 308 redirects from legacy composite-key URLs |
| `test_api_statements_stable_row_id.py` | Statements PATCH `row_id` contract — stability of row_id-keyed updates |

```bash
# Run all unit tests
uv run pytest tests/ -m "not integration"

# Run a specific test file
uv run pytest tests/unit/test_rbc_parser.py -v

# Run with coverage report
uv run pytest tests/ -m "not integration" --cov-report=html
```

## Frontend Tests

Frontend tests run on Vitest — mostly pure utility functions, plus a growing set of hook tests (`use*.test.tsx`) and the odd component test. As with the backend table, `ls frontend/src/**/*.test.*` is the authoritative inventory.

| Test File | What It Covers |
|-----------|---------------|
| `format.test.ts` | Currency formatting, date parsing, month shifting, percent display |
| `categoryGroups.test.ts` | Category → group mapping, case insensitivity, duplicate detection |
| `budgetCalc.test.ts` | Monthly↔yearly conversion, target derivation, edge cases |
| `cashFlow.test.ts` | Sankey cash-flow graph builder — income → income hub → expense groups + savings/drawdown |
| `filters.test.ts` | Filter logic — category group filtering, search, precedence rules |
| `severity.test.ts` | Budget severity tier mapping — pace thresholds, attention bands |
| `sort.test.ts` | Transaction sort comparators — date, amount, company, stable secondary keys |
| `demoApi.test.ts` | Demo-mode API shim — fixture loading, response shape parity with real `api.ts` |
| `demoOverlay.test.ts` | Demo session overlay — sessionStorage mutations layered over static fixtures |
| `useDebouncedValue.test.tsx` | `useDebouncedValue` hook — leading/trailing edge, cancellation on unmount |
| `useMediaQuery.test.tsx` | `useMediaQuery` hook — match changes, SSR fallback |
| `navPreferences.test.ts` | Nav preferences zustand store — persisted tab order, hidden tabs |
| `omniQuery.test.ts` | Omnibar query parser — month tokens, merchant totals, category-budget intents (35+ table-driven cases) |
| `merchantNormalize.test.ts` | `normalizeMerchant` — store-number stripping, location cleanup (frontend mirror of the backend normalizer) |
| `categorySuggest.test.ts` | `suggestFromHistory` — category suggestion derived from prior user edits |
| `statementTransform.test.ts` | `transformDetailToUploadFormat` — statement detail → upload-form reshaping |
| `parseFailures.test.ts` | Parse-failure view helpers — `failureStageLabel`, status → human-label mapping |
| `demoEmails.test.ts` | `buildDemoEmail` — deterministic synthetic bank-email bodies per institution × type |
| `apiParity.test.ts` | `api` / `demoApi` export parity — demo shim exposes the same surface as the real client |
| `theme.test.ts` | Theme zustand store — light/dark toggle, persistence |
| `preferences.test.ts` | Preferences zustand store — persisted user settings |
| `freshness.test.ts` | Freshness store — health/last-poll staleness signal for the sidebar indicator |
| `editedTransactions.test.ts` | Edited-transactions store — optimistic local edits layered over fetched rows |
| `omnibar.test.ts` | Omnibar recents store — dedupe, cap at 8, persisted |
| `demoTour.test.ts` | Demo tour store — opt-in guided-tour step state |
| `useParseFailureActions.test.tsx` | `useRetryParseFailure` hook — the three retry outcomes (recovered / still-failing / gone) |
| `useResolveParseFailure.test.tsx` | `useResolveParseFailure` hook — manual-entry resolve outcomes (created / duplicate / error) |

```bash
cd frontend && pnpm test              # run all frontend tests
cd frontend && pnpm test:watch        # watch mode
```

## Integration Tests

Integration tests call external services (OpenAI API) and require credentials.

| Test File | What It Covers |
|-----------|---------------|
| `test_openai_categorization.py` | Real OpenAI API categorization with 3 fixtures |

```bash
# Run integration tests (requires OPENAI_API_KEY env var)
OPENAI_API_KEY=sk-... uv run pytest tests/integration/ -m integration -v --no-cov
```

Integration tests are marked with `@pytest.mark.integration` and automatically skip when `OPENAI_API_KEY` is not set.

## API Test Patterns

New API tests must use the shared helpers below (the agent-loaded quick reference is [`tests/CLAUDE.md`](../tests/CLAUDE.md)). Old tests still using ad-hoc patterns will be migrated by `scripts/checks/migrate_api_tests.py`; do not introduce new ones — `scripts/checks/check_test_conventions.py` (in `make verify-backend` and CI) pins the legacy `TestClient(` counts so they can only go down.

### Required helpers for new API tests

| Helper | Where it lives | Use it for |
|--------|---------------|------------|
| `api_client` fixture | `tests/conftest.py` | TestClient with automatic `app.dependency_overrides` cleanup. Do **not** hand-roll `client = TestClient(app)` at module scope. |
| `assert_ok(resp)` / `assert_problem(resp, status, code=None)` | `tests/asserts.py` | Body-aware status assertions. Do **not** write bare `assert resp.status_code == 200`; the failure message swallows the response body. |
| `mock_run_sync` parametrized fixture | `tests/conftest.py` | Replaces `@patch("src.api.routers.<name>.run_sync", new_callable=AsyncMock)`. Drive it via `@pytest.mark.parametrize("mock_run_sync", ["<router_name>"], indirect=True)`. |
| `tests/factories.py` factories | `tests/factories.py` | Single source of truth for `make_transaction_item`, `make_budget_targets_item`, `make_groups_item`, `make_parse_result`, `make_reconcile_result`. Do **not** copy these helpers into individual test files. |

### Canonical example

```python
import pytest
from unittest.mock import AsyncMock

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_transaction_item


class TestListTransactions:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_returns_two(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [make_transaction_item()]
        body = assert_ok(api_client.get("/api/v1/transactions?month=2026-02"))
        assert body["count"] == 1

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_404_envelope(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        assert_problem(api_client.get("/api/v1/transactions/missing"), 404, "NOT_FOUND")
```

### Mocking `run_sync` (legacy pattern)

The FastAPI routers delegate blocking I/O to `run_sync()` (from `src/api/dependencies.py`), which runs a synchronous function in a thread pool. The `mock_run_sync` indirect-parametrize fixture above wraps the equivalent `@patch(..., new_callable=AsyncMock)` pattern; `new_callable=AsyncMock` is required because `run_sync` is an `async def`. Without it, `patch` creates a regular `MagicMock` which raises `TypeError: object MagicMock can't be used in 'await' expression` at runtime.

## Adding Test Data

Test fixtures live in `tests/test_data/<institution>/` with paired files:

- **`<name>.txt`** — raw email body text
- **`<name>.json`** — expected parsed output (institution, name, amount, company, transaction_type)

Redact real emails manually before committing as test data — replace amounts with `$XX.XX`, merchant names with `[MERCHANT]`, card last-4 digits with `[XXXX]`, and account numbers with `[ACCOUNT]`. **Preserve the original formatting, field ordering, and whitespace** — that is what the parser matches on. The `.github/ISSUE_TEMPLATE/parser_broken.md` template documents the same redaction rules.

## End-to-End Lambda Testing

Two opt-in integration tests in `tests/integration/` exercise the real
pipelines end to end, one per backend. Both are excluded from every gate
(`make test` / `test-ci` / `verify` run `-m "not integration"`) and skip
cleanly when their env is absent:

- `test_lambda_e2e.py` — the AWS round-trip: uploads the fictitious fixture
  `tests/fixtures/e2e_test_email.eml` (`E2E TEST CAFE`, `$1.23`) to the
  inbound S3 bucket, invokes the Lambda, verifies the DynamoDB record and
  `TransactionContext` enrichment, and cleans up after itself — even on
  failure. Requires `E2E_EMAIL_BUCKET` + `E2E_USER_ID` (optional
  `E2E_LAMBDA_FUNCTION` / `E2E_TRANSACTIONS_TABLE` / `E2E_BUDGET_TABLE`).
- `test_imap_poller.py` — the self-hosted round-trip: fetches one message
  from a real inbox (read-only `BODY.PEEK`), runs the parse → store → enrich
  pipeline against an isolated temp SQLite DB, verifies the row, cleans up.
  Requires `IMAP_USER` + `IMAP_PASSWORD`.

```bash
uv run pytest tests/integration/test_lambda_e2e.py -m integration   # AWS path
uv run pytest tests/integration/test_imap_poller.py -m integration  # IMAP path
```

Unit coverage for the Lambda handler itself lives in
`tests/unit/test_lambda_handler.py`.

## Local Pipeline Testing

To iterate on a parser without deploying, save a representative email body to `tests/test_data/<institution>/sample.txt` (with expected output in `sample.json`) and run `uv run pytest tests/unit/test_<institution>_parser.py -v`. This exercises the same `parse_email_body()` code path the Lambda and IMAP daemon use, in a tight feedback loop with no AWS calls.

## Pre-Deployment Checklist

For the default Docker path there is one gate: `make verify` green before a
release — the [release ritual](guides/releases.md) runs it and CI re-runs it.
The checklist below is the extra mile for the **AWS Lambda variant** only.

Before pushing a new Docker image to ECR:

- [ ] `make test-ci` — all unit tests pass with the 90% branch-coverage gate enforced
- [ ] `uv run ruff check src/ tests/` — no lint errors
- [ ] `uv run ruff format --check src/ tests/` — no format issues
- [ ] `bash docker/email_parsing/2_build_image.sh` — Docker image builds
- [ ] `uv run pytest tests/integration/test_lambda_e2e.py -m integration` with the `E2E_*` env set — the round-trip passes and cleans up (see [End-to-End Lambda Testing](#end-to-end-lambda-testing))

## Scripts Reference

Repo and CI tooling lives in `scripts/`; operator CLIs — the break-glass
tools you run by hand against your own data (category maintenance, insights
context, the DynamoDB backup/restore pair) — live in `dev/cli/`, and the
prompt-eval Streamlit harness in `dev/eval_harness/` (`make
dev-eval-harness`, needs `uv sync --extra eval`). Every script carries a
header docstring; the `scripts/` entries that matter for testing and
release:

| Script | Purpose |
|--------|---------|
| `checks/check_canon_links.py` | Canon markdown link checker — first step of `make verify` |
| `checks/check_test_conventions.py` | Test-convention ratchet — bans ad-hoc `TestClient(app)` in favour of the shared `api_client` fixture |
| `demo/check_demo_api.py` | Structural gate for the hosted demo API artifacts (CI `demo-smoke`) |
| `demo/check_demo_fixtures.py` | Cross-fixture consistency gate for the static demo (CI `demo-smoke`) |
| `demo/generate_demo_openapi.py` | Regenerate the demo OpenAPI schema served at `/demo/api/openapi.json` |
| `demo/generate_demo_fixtures.ts` | Snapshot read-only backend responses into static demo fixtures |
| `agent/agent_token.py` | Issue / show / revoke agent bearer tokens (wrapped by `make agent-token*`) |
| `pii/audit_oss_release.py` | PII / secret audit of the tracked tree (pre-push hook and CI) |

See `scripts/README.md` for the full inventory, including the
marketing-asset generators under `scripts/media/`.
