# Backend agent guide (finance + storage)

Backend-specific addendum to `/workspace/CLAUDE.md`. Covers the dual-backend
storage layer, per-bank parsers, and finance domain rules that govern
`src/finance/` and the API routers that consume these services.

## Dual-backend storage

Two backends — **DynamoDB** (production/AWS) and **SQLite** (local/demo) —
selected by `src/finance/app_config.py` from `data/config.json`:
- `storage: "dynamodb"` — explicit opt-in for the AWS path; never auto-selected (first run always defaults to SQLite, even with AWS credentials present)
- `storage: "sqlite"` — default local mode, uses `data/finance.db`
- `demo_mode: true` — uses `data/demo.db` with seeded sample data

`src/finance/storage.py` routes each `create_*()` factory to the right
implementation. **Routers consume services only via these factories through
`src/api/dependencies.py` — never import a service class directly.**

**Service pairs — 9 services have dual implementations:**

| Service | Base/DynamoDB | SQLite | Factory |
|---------|--------------|--------|---------|
| Overrides | `override_service.py` | `override_service_local.py` | `create_override_service()` |
| Categories | `category_service.py` | `category_service_local.py` | `create_category_service()` |
| Merchant Aliases | `merchant_alias_service.py` | `merchant_alias_service_local.py` | `create_merchant_alias_service()` |
| Ignore Rules | `ignore_rule_service.py` | `ignore_rule_service_local.py` | `create_ignore_rule_service()` |
| Category Icons | `category_icon_service.py` | `category_icon_service_local.py` | `create_category_icon_service()` |
| Transactions | `transaction_db.py` | `transaction_db_local.py` | `create_transactions_db()` |
| Spending Summary | `spending_summary.py` | `spending_summary_local.py` | `create_spending_summary()` |
| Budget | `budget_service.py` | `budget_service_local.py` | `create_budget_service()` |
| Parse Failures | `parse_failure_store.py` | `parse_failure_store_local.py` | `create_parse_failure_store()` |

- **Config services** (Override, Category, MerchantAlias, IgnoreRule,
  CategoryIcon) share business logic via a base class (the `*ServiceBase` class
  living in the DynamoDB module, which both pair members inherit) — only storage
  methods differ. **Edit the base class for logic; `*_local.py` / the DynamoDB
  class only for storage-specific changes.**
- **Transaction, summary, budget, and parse-failure stores** each share an
  abstract base class (`*_base.py` — `transaction_db_base.py`,
  `spending_summary_base.py`, `budget_service_base.py`,
  `parse_failure_store_base.py`) that both pair members inherit. The ABC pins
  the common contract, plus any storage-agnostic logic worth sharing (summary
  aggregation, budget defaults, the parse-failure classifier coercion); the
  per-backend storage internals still differ. **When changing one, check its
  `*_local.py` counterpart and update both if the change touches the public
  API, and change the `*_base.py` ABC when you change the shared contract.**

## Parsers

Each bank (RBC, CIBC, MBNA, Simplii, PC Financial) has a parser in
`src/finance/parsers/` inheriting from `TransactionParser` in `parser_base.py`.
All parsers must implement the abstract `parse_email()` method — enforced by
`tests/property/test_parser_invariants.py`, which parametrizes every parser.

## Domain rules

- Transaction amounts are normalized to float.
- Dates use the configured `timezone` from `data/config.json`
  (`src/finance/app_timezone.py`, default Pacific).
- SMS notifications are filtered by the blocked-companies list.

## DynamoDB schema

Table `Transactions` — PK: `ForwardedTo` (String), SK: `DateFileName` (String).
Auto-created.
