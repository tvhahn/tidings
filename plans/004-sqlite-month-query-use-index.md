# Plan 004: Make SQLite month queries use the `date_file_name` index instead of scanning the whole table

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 69adcfa..HEAD -- src/finance/spending_summary_local.py src/finance/transaction_db_local.py src/finance/local_db.py tests/unit/test_spending_summary_local.py tests/unit/test_transaction_db_local.py`
> If any of these files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before you start. If
> they don't match, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `69adcfa`, 2026-09-23

## Why this matters

SQLite is the default backend for self-hosted installs. Every month-scoped
read goes through `SpendingSummaryLocal.query_month`: the dashboard summary,
journal, search (up to 24 months per request), budgets and insights (about
46 month queries per briefing). That method filters with
`date_file_name LIKE 'YYYY.MM%'`.

SQLite's `LIKE` is case-insensitive by default, so it **cannot** use the
BINARY-collated index `idx_transactions_date_file_name`. The query plan is a
full table scan, and `SELECT *` pulls every row's raw email `body` along with
it. A 24-month search is therefore 24 full passes over the table.

`GLOB 'YYYY.MM*'` is case-sensitive, so SQLite rewrites it into an index
range. Since `date_file_name` month prefixes contain only digits and a dot,
the results are identical.

Measured at planning time against the real schema (`local_db._SCHEMA_SQL`,
in-memory):

```
LIKE '2026.09%'                      → SCAN transactions
GLOB '2026.09*'                      → SEARCH transactions USING INDEX idx_transactions_date_file_name (date_file_name>? AND date_file_name<?)
forwarded_to=? AND LIKE '2026.09%'   → SEARCH ... USING INDEX idx_transactions_date_prefix (forwarded_to=?)          (partition scan)
forwarded_to=? AND GLOB '2026.09*'   → SEARCH ... USING INDEX idx_transactions_date_prefix (forwarded_to=? AND date_file_name>? AND date_file_name<?)
MAX(...) WHERE GLOB '2026.09*'       → SEARCH ... USING COVERING INDEX idx_transactions_date_file_name (...)
```

## Current state

All three `LIKE` month filters in `src/` (from `grep -rn " LIKE " src --include=*.py`):

1. `src/finance/spending_summary_local.py:34-44`, `SpendingSummaryLocal.query_month`:

   ```python
           prefix = year_month.replace("-", ".")
           conn = get_connection(self._db_path)
           try:
               rows = conn.execute(
                   "SELECT * FROM transactions WHERE date_file_name LIKE ?",
                   (f"{prefix}%",),
               ).fetchall()
   ```

2. `src/finance/transaction_db_local.py:671-691`, `TransactionsDBLocal.query_month_partition`:

   ```python
           prefix = year_month.replace("-", ".")
           ...
                   """SELECT forwarded_to, date_file_name, amount, category, company,
                             transaction_type, deleted_at, ignored
                      FROM transactions
                      WHERE forwarded_to = ? AND date_file_name LIKE ?""",
                   (forwarded_to, f"{prefix}%"),
   ```

   Its docstring says "Uses LIKE prefix matching ... The composite index
   idx_transactions_date_prefix covers this query." That is only half true:
   the index covers the `forwarded_to` equality, not the prefix.

3. `src/finance/transaction_db_local.py:703-717`, `TransactionsDBLocal.get_latest_date_file_name`:

   ```python
                   row = conn.execute(
                       "SELECT MAX(date_file_name) AS latest FROM transactions WHERE date_file_name LIKE ?",
                       (f"{prefix}%",),
                   ).fetchone()
   ```

Schema: `src/finance/local_db.py:338-349` defines
`PRIMARY KEY (forwarded_to, date_file_name)` and the indexes
`idx_transactions_date_prefix(forwarded_to, date_file_name)` and
`idx_transactions_date_file_name(date_file_name)`.

`date_file_name` values look like `2026.02.15_10.30_fixture.eml`. The month
prefix is `YYYY.MM`, derived from a `YYYY-MM` string. Month strings are
validated at the API boundary (see `docs/guides/api-conventions.md`, "month
validation").

Existing behavioural coverage that must stay green:
`tests/unit/test_spending_summary_contract.py::...::test_query_month_scopes_to_the_requested_month`
runs on both backends. `tests/unit/test_spending_summary_local.py` and
`tests/unit/test_transaction_db_local.py` cover the local methods.

Conventions: SQL strings live inline in the method today. This plan pulls
the three statements into module-level constants so a test can run
`EXPLAIN QUERY PLAN` on the exact SQL the code executes. Name them
`_QUERY_MONTH_SQL`, `_QUERY_MONTH_PARTITION_SQL` and `_LATEST_IN_MONTH_SQL`,
and keep them next to the module's other module-level names.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Deps | `uv sync` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_spending_summary_local.py tests/unit/test_transaction_db_local.py tests/unit/test_spending_summary_contract.py -q` | all pass |
| Full backend tests | `uv run pytest tests/ -m "not integration" -q -n 8` | all pass |
| Lint / format / types | `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` | exit 0 |

## Scope

**In scope**:

- `src/finance/spending_summary_local.py`
- `src/finance/transaction_db_local.py`: only `query_month_partition` and `get_latest_date_file_name`, plus the new constants
- `tests/unit/test_spending_summary_local.py`, `tests/unit/test_transaction_db_local.py`: new tests

**Out of scope** (do NOT touch; each is a separate, deliberately deferred change):

- `src/finance/local_db.py`: do not add or drop indexes. The duplicate
  `idx_transactions_date_prefix` (same columns as the PK) is real waste, but
  dropping it needs a schema migration.
- Honouring the `projection` argument / removing `SELECT *` in
  `query_month`. Callers may depend on columns. That's a separate plan.
- The DynamoDB modules (`spending_summary.py`, `transaction_db.py`). They already use `begins_with` on the sort key.
- Any `LIKE` outside these three sites, for example a user-facing text search. Don't convert those.

## Git workflow

- Commit on the current branch. Don't create branches (root `CLAUDE.md` §Committing).
- Use the `/commit` skill if available. Otherwise use the house format, for example
  `⚡ perf(sqlite): Use the date index for month-scoped queries`.
- This is an internal performance change with no user-visible contract
  change, so a changelog entry is optional. Follow the `/commit` changelog
  gate. Do not push unless told to.

## Steps

### Step 1: Add query-plan tests that fail today

In `tests/unit/test_spending_summary_local.py`, add:

```python
class TestQueryPlans:
    """Month filters must hit an index — a LIKE prefix silently degrades to SCAN."""

    def _plan(self, sql: str, params: tuple) -> str:
        import sqlite3
        from src.finance import local_db
        conn = sqlite3.connect(":memory:")
        conn.executescript(local_db._SCHEMA_SQL)
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
        return " | ".join(str(r[-1]) for r in rows)

    def test_query_month_uses_date_index(self) -> None:
        from src.finance.spending_summary_local import _QUERY_MONTH_SQL
        plan = self._plan(_QUERY_MONTH_SQL, ("2026.02*",))
        assert "SCAN transactions" not in plan
        assert "USING INDEX" in plan or "USING COVERING INDEX" in plan
```

Add the equivalent for `_QUERY_MONTH_PARTITION_SQL` (params
`("user@example.com", "2026.02*")`) and `_LATEST_IN_MONTH_SQL` (params
`("2026.02*",)`) to `tests/unit/test_transaction_db_local.py`. For the
partition query, assert `"date_file_name>"` appears in the plan, which proves
the prefix is used in the index range.

Also add a behavioural edge-case test to `test_spending_summary_local.py`,
using that file's `_add_purchase` helper and the `tmp_db_path` fixture. Insert
purchases dated `01/31/2026`, `02/01/2026`, `02/28/2026` and `03/01/2026`,
each with a distinct `file_suffix`. Assert `query_month("2026-02")` returns
exactly the 2 February rows.

**Verify**: the new tests fail with `ImportError` because the constants don't
exist yet. The edge-case test passes already, since behaviour is unchanged.

### Step 2: Switch the three statements to GLOB via constants

In `src/finance/spending_summary_local.py`, add near the top of the module:

```python
# GLOB (case-sensitive) lets SQLite turn the month prefix into an index range on
# idx_transactions_date_file_name; LIKE is case-insensitive and forces a full SCAN.
# The prefix is 'YYYY.MM' — digits and a dot, no GLOB metacharacters.
_QUERY_MONTH_SQL = "SELECT * FROM transactions WHERE date_file_name GLOB ?"
```

Use it in `query_month` with the parameter `f"{prefix}*"`.

In `src/finance/transaction_db_local.py`, add `_QUERY_MONTH_PARTITION_SQL`
(same column list as today, `... WHERE forwarded_to = ? AND date_file_name GLOB ?`)
and `_LATEST_IN_MONTH_SQL`
(`SELECT MAX(date_file_name) AS latest FROM transactions WHERE date_file_name GLOB ?`).
Use them in the two methods with `f"{prefix}*"`. Update the
`query_month_partition` docstring to say GLOB, and explain why.

**Verify**: `uv run pytest tests/unit/test_spending_summary_local.py tests/unit/test_transaction_db_local.py tests/unit/test_spending_summary_contract.py -q` → all pass, including the new query-plan tests.
`grep -rn "date_file_name LIKE" src/` → no output.

### Step 3: Full gate

**Verify**: `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures. `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` → exit 0.

## Test plan

- 3 query-plan tests pin index use for each statement.
- 1 month-boundary behavioural test.
- The existing both-backend contract test `test_query_month_scopes_to_the_requested_month` stays green.

## Done criteria

- [ ] `grep -rn "date_file_name LIKE" src/` → no output
- [ ] `grep -n "_QUERY_MONTH_SQL\|_QUERY_MONTH_PARTITION_SQL\|_LATEST_IN_MONTH_SQL" src/finance/*.py` → each defined once and used once
- [ ] `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures, with 4 new tests present
- [ ] Lint, format and pyright → exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` row 004 set to DONE

## STOP conditions

- `grep -rn " LIKE " src --include=*.py` finds month-prefix filters beyond
  the three listed. Report them rather than converting them silently.
- A caller passes a `year_month` that is not `YYYY-MM`, such as a bare year
  `"2026"` used as a prefix. Check callers of `query_month`,
  `query_month_partition` and `get_latest_date_file_name` with grep. GLOB
  still works for any digit prefix, but report anything containing `*`, `?`
  or `[`.
- Any existing test fails after Step 2. The semantics should be identical,
  so a failure means an assumption here is wrong.

## Maintenance notes

- Any new month-scoped SQLite query must use `GLOB 'prefix*'` or an explicit
  `>= / <` range, never `LIKE`. The query-plan tests only guard the three
  statements they import.
- Follow-ups, deliberately deferred:
  - Drop the redundant `idx_transactions_date_prefix`. It has the same columns as the PK, and every write maintains it. This needs a migration in `local_db.py`.
  - Honour `projection` in `query_month` so summaries stop reading email `body` columns.
  - Insights fetches about 46 month queries for 24 unique months (`src/finance/insights_context.py:547-573`). Deduplicating that is a separate optimisation.
