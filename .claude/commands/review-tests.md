---
description: Review test suite for gaps, coverage issues, and improvements via a pre-configured testing expert panel
argument-hint: "[optional focus area, e.g. 'auth module' or 'input validation']"
---

# Test Suite Review

You are auditing this repo's test suite and analyzing it through a panel of testing experts. This is a **review, not a fix**: produce findings and a plan. Do not edit source, tests, or config, and do not run any git command that changes state (no checkout/stash/restore/commit).

**Focus area:** $ARGUMENTS

## Guardrails (read first)

- **Never run integration or private-fixture tests.** `-m integration` tests call external services (OpenAI etc.); `private_fixtures` tests read real bank statements. Always keep `-m "not integration"` and never set `RUN_PRIVATE_FIXTURES=1`.
- **Never read `tests/test_data/_private/` or `data/`** — real financial data. Committed fixtures under `tests/test_data/<institution>/` are redacted and fine to read.
- **Don't run Playwright e2e** (`make verify-e2e`) — enumerate `frontend/e2e/` specs and review them statically instead.
- **Every finding needs evidence you actually captured** — a `file:line` you read or command output from this session. If a command fails, report the failure verbatim; never estimate or invent a coverage number, test count, or quote from a file you didn't open.

## Phase 0: Scope

If `$ARGUMENTS` is empty, the scope is the whole suite (backend + frontend unit; e2e statically). Otherwise, resolve the focus area to concrete paths first (source modules + their test files) and list them before proceeding. If nothing matches, say so and stop — do not silently widen to the full suite.

## Phase 1: Ground truth

### House rules (canon — read before judging anything)

1. `tests/CLAUDE.md` — required API-test helpers (`api_client`, `assert_ok`/`assert_problem`, `mock_run_sync`, `tests/factories.py`), the `TestClient(` ratchet, dual-backend contract rule, parser `PARSERS` rule, `freeze_clock`, fixture-redaction rules.
2. `docs/TESTS.md` — testing narrative and canonical API test patterns.
3. If frontend is in scope: `frontend/CLAUDE.md` and `frontend/vitest.config.*` (coverage thresholds).

A recommendation that contradicts canon, or restates something a gate already enforces (`scripts/checks/check_test_conventions.py`, `--cov-fail-under=90`, strict markers), is a **non-finding** — drop it. The interesting findings are where reality drifts from canon, or where canon has a blind spot.

### Live data (run these; adapt only if the config has changed)

Backend — run in parallel where possible:

1. `uv run pytest tests/ -m "not integration" --co -q` — total count + test IDs (fast).
2. `make test` — runs the suite with `--cov=src --cov-report=term-missing` (branch coverage from `[tool.coverage.run]`). ~60–90s. Capture per-module % and missing lines. The CI gate is **90% branch** (`make test-ci`) — use 90% as the bar, not a generic threshold.
3. `uv run python scripts/checks/check_test_conventions.py` — the ad-hoc-`TestClient` ratchet baseline; remaining legacy count is a direct debt metric.

Frontend (if in scope):

4. `cd frontend && pnpm run test:coverage` — vitest with the configured thresholds. If it's not installed/hydrated, note that and fall back to static review.

If any of these commands no longer match the project config (`pyproject.toml [tool.pytest.ini_options]`, `Makefile`, `frontend/package.json`), trust the config and say what changed.

### Mapping

Build a source-module → test-file map for the scope. **Report only the exceptions**, not the full table: modules with no corresponding test file, or below the 90% branch bar, worst first (cap at ~15 rows; state how many more exist).

## Phase 2: Expert panel analysis

No interview — the panel is pre-configured. Each expert analyzes the Phase 1 ground truth through their lens, narrowed to the focus area if one was given. Experts must ground claims in Phase 1 evidence and the house rules — not generic testing folklore.

### The panel

**Mara Chen** — Test Architecture Lead
- Lens: structure, layering, isolation, maintainability
- Checks: test organization vs `tests/{unit,api,property,integration}` layout, fixture scoping in `conftest.py`, mock boundaries, test independence, dual-backend parametrization actually covering both backends where storage changed

**James Okafor** — Agent-Friendly Testing Specialist
- Lens: how well tests serve LLM coding agents (speed, failure messages, naming)
- Checks: suite wall-time and slowest tests (`--durations`), failure-message quality (`assert_problem` vs bare status asserts, named mocks), parametrize readability, whether `test-fast` / `test:fast` loops stay fast, condition-gated skips vs skip debt

**Priya Ramanathan** — Developer Experience Engineer
- Lens: factory ergonomics, boilerplate, assertion clarity
- Checks: adoption of `tests/factories.py` and shared helpers vs copy-pasted item shapes, repeated setup patterns worth a fixture, `freeze_clock` usage vs ad-hoc time patching, ratchet-baseline burn-down

**David Moreau** — Domain Coverage Analyst
- Lens: business-logic coverage, boundaries, error paths, mock fidelity
- Checks: uncovered branches in core finance/parser/API logic (from the coverage run's missing lines), validation boundaries (amounts, timezones, month validation), error-path coverage of the unified problem shape, whether mocks match real backend behavior, parser fixtures vs `PARSERS` invariants

### Output format for each expert

1. **Top 3 findings** (fewer is fine if the evidence only supports fewer) — each with a title, evidence (`file:line`, coverage lines, or captured output), and a short blockquote in the expert's voice.
2. **One actionable recommendation** — exact file paths, what to change, and which canon rule or gate it relates to.

### Disagreements

If experts disagree (e.g., Mara wants isolation where David wants integration seams), present both sides with a recommendation on which should win here. Don't force consensus.

## Phase 3: Synthesis and action plan

Deliver all of this in your **final message** (not scattered mid-turn):

1. **Convergence/divergence** — 3–5 sentences.
2. **Prioritized improvements** — deduplicated across experts (one row per underlying issue, credit multiple experts in one row):

   | # | Improvement | Files to change | Effort | Expert(s) |
   |---|-------------|----------------|--------|-----------|

   Effort: **S** (<30 min), **M** (1–2 h), **L** (half day+).
3. **Quick wins** — the S items, one line each, with paths you verified exist this session.
4. **What was not reviewed** — anything skipped (integration tests, e2e execution, unhydrated frontend) so the reader knows the review's edges.
