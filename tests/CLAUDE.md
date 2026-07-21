# tests/ — agent guide

Scoped addendum to the root [`CLAUDE.md`](../CLAUDE.md) for work under `tests/`.
Run: `uv run pytest tests/ -m "not integration"` (~60s). Full narrative + fixture-data
redaction rules: [`docs/TESTS.md`](../docs/TESTS.md).

## API tests — required helpers

New API tests **must** use the shared helpers. Old ad-hoc tests are being migrated by
`scripts/checks/migrate_api_tests.py`; **do not introduce new ad-hoc patterns** — a ratchet gate
(`scripts/checks/check_test_conventions.py`, in `make verify-backend` and CI) fails the build if
`TestClient(` appears outside `tests/conftest.py` beyond the pinned legacy baseline.

| Helper | Where | Use it for |
|--------|-------|------------|
| `api_client` fixture | `tests/conftest.py` | TestClient with automatic `app.dependency_overrides` cleanup. Never hand-roll `client = TestClient(app)` at module scope. |
| `assert_ok(resp)` / `assert_problem(resp, status, code=None)` | `tests/asserts.py` | Body-aware status assertions. Never write bare `assert resp.status_code == 200` — the failure message swallows the response body. |
| `mock_run_sync` fixture (indirect-parametrized) | `tests/conftest.py` | Replaces `@patch("src.api.routers.<name>.run_sync", new_callable=AsyncMock)`. Drive via `@pytest.mark.parametrize("mock_run_sync", ["<router>"], indirect=True)`. |
| Factories (`make_transaction_item`, `make_budget_targets_item`, …) | `tests/factories.py` | Single source of truth for item shapes — never copy these into test files. |

Canonical example: [`docs/TESTS.md`](../docs/TESTS.md) § API Test Patterns.

## Conventions

- **Assert specific values**, not truthiness — `assert got["status"] == "quarantined"`, never `assert got`.
- **Dual-backend changes need both backends tested** — contract tests parametrize a `["dynamodb", "sqlite"]` fixture (see `tests/unit/test_parse_failure_store.py` for the shape); a change to one backend without the parametrized contract is incomplete.
- **Parser changes**: the Hypothesis invariants in `tests/property/test_parser_invariants.py` parametrize every parser in its `PARSERS` list — a new parser must be added there (a membership test against `src/finance/email_pipeline.py`'s `build_parsers()` dispatch table enforces this).
- **Freeze time via the shared `freeze_clock` seam** (`tests/conftest.py`), never ad-hoc `datetime.now` patching.
- **Name call-state-asserted mocks** (`mock.name = "..."`) so failures read.
- **Skips must be condition-gated** (missing fixture, missing tool, missing key) — never bare `skip`/`xfail` debt.
- **Fixture data** lives in `tests/test_data/<institution>/` as paired `.txt`/`.json`, redacted per [`docs/TESTS.md`](../docs/TESTS.md) — amounts `$XX.XX`, merchants `[MERCHANT]`, last-4 `[XXXX]`; preserve original formatting/whitespace exactly.
- `tests/` is deliberately not type-checked by pyright (`pyproject.toml` scopes it to `src/`); ruff covers tests.
