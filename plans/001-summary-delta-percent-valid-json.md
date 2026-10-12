# Plan 001: Make `/summary` and `/insights/context` return valid JSON when the previous month has no spending

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 69adcfa..HEAD -- src/finance/spending_summary_base.py src/api/routers/summary.py src/api/models/summary.py src/api/models/insights.py src/api/main.py frontend/src/lib/summaryPace.ts frontend/src/lib/demoApi.ts tests/unit/test_spending_summary.py tests/unit/test_spending_summary_local.py tests/unit/test_spending_summary_contract.py tests/unit/test_api_summary.py tests/unit/test_api_insights.py`
> If any of these files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before you start. If
> they don't match, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `69adcfa`, 2026-09-23

## Why this matters

When the previous month's spending is 0 and this month's is above 0, the
backend sets `delta_percent = float("inf")`. Python's `json.dumps` then writes
the bare token `Infinity` into the response body, which is not valid JSON.

The frontend parses every response with `JSON.parse`, which throws on
`Infinity`. The dashboard's main summary query therefore fails for every new
user's first month with data, and for any month that follows an empty month.

`GET /api/v1/insights/context` embeds the same value, so it breaks the same
way. The demo fixture generator already strips `Infinity` with a regex. That
workaround treats the symptom, and the real API still emits invalid JSON.

The fix makes "no baseline" an explicit `null`. It also makes the JSON
renderer refuse non-finite floats, so this class of bug fails loudly on the
server in future instead of silently breaking clients.

## Current state

Files involved:

- `src/finance/spending_summary_base.py`: shared month-over-month comparison
  used by both the SQLite and DynamoDB backends. The bug is at lines 82–86.
- `src/api/routers/summary.py`: `GET /api/v1/summary`. Line 98 coerces the
  value with `float(...)`.
- `src/api/models/summary.py`: `SummaryComparisonResponse.delta_percent: float` at line 148.
- `src/api/models/insights.py`: `InsightsContextResponse.delta: dict[str, float]` at line 215.
- `src/finance/insights_context.py:640-643`: copies `delta_percent` into
  `context["delta"]["percent"]`. **No change is needed there.** Once the base
  returns `None`, it passes through automatically.
- `src/api/main.py:62-66`: `DecimalJSONResponse`, the app's default response class.
- `frontend/src/lib/summaryPace.ts`: reads `delta_percent` in `completeMonthCards` (≈line 140–150) and `buildHeadline` (≈line 205–212).
- `frontend/src/lib/demoApi.ts:944`: the demo-mode insights context. It already does `summary.delta_percent ?? 0`.
- Generated files, which are regenerated and never hand-edited: `openapi.json`,
  `frontend/src/types/api.generated.ts` and `frontend/public/demo-api/*`.

`src/finance/spending_summary_base.py:72-93` (current):

```python
    def get_summary_with_comparison(self, year_month: str) -> dict[str, Any]:
        ...
        delta_amount = current["total_spending"] - previous["total_spending"]
        if previous["total_spending"] > 0:
            delta_percent = float(delta_amount / previous["total_spending"] * 100)
        else:
            delta_percent = float("inf") if current["total_spending"] > 0 else 0.0

        return {
            "current": current,
            "previous": previous,
            "delta_amount": delta_amount,
            "delta_percent": delta_percent,
        }
```

`src/api/routers/summary.py:93-99` (current):

```python
    raw = await run_sync(summary.get_summary_with_comparison, month)
    current = _to_month_summary(raw["current"])
    response = SummaryComparisonResponse(
        current=current,
        previous=_to_month_summary(raw["previous"]),
        delta_amount=float(raw["delta_amount"]),
        delta_percent=float(raw["delta_percent"]),
    )
```

`src/api/main.py:62-66` (current):

```python
class DecimalJSONResponse(JSONResponse):
    """JSONResponse that automatically converts Decimal values to float."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, cls=DecimalEncoder, ensure_ascii=False).encode("utf-8")
```

`frontend/src/lib/summaryPace.ts` (current, two sites):

```ts
function completeMonthCards(data: SummaryComparisonResponse): SummaryCardModel[] {
  const { current, previous, delta_amount, delta_percent } = data;
  ...
    sub:
      previous.total_spending === 0
        ? ""
        : `${formatPercent(delta_percent)} vs ${formatMonthLabel(previous.year_month)}`,
```

```ts
  if (data.previous.total_spending <= 0) return null;
  ...
  if (Math.abs(data.delta_percent) <= 2 + EPSILON) {
```

Existing tests pin the `inf` behaviour and must be updated:

- `tests/unit/test_spending_summary.py:379`: `assert result["delta_percent"] == float("inf")`
- `tests/unit/test_spending_summary_local.py:151-152`: the same assertion
- `tests/unit/test_spending_summary_contract.py:208-214`:
  `test_comparison_zero_previous_yields_infinite_delta_percent`

The Python tests pass today only because Python's `json` module accepts
`Infinity`. Browsers do not.

Conventions:

- API tests use the `api_client` fixture plus `assert_ok` from
  `tests/asserts.py`. Router tests mock services with the indirect-parametrized
  `mock_run_sync` fixture. Model after `tests/unit/test_api_summary.py::TestGetSummary`.
- Never write a bare `assert resp.status_code == 200`. Use `assert_ok(resp)`.
- `openapi.json` and `frontend/src/types/api.generated.ts` are generated.
  Regenerate them with `make openapi` and `cd frontend && pnpm codegen`.
  Never hand-edit them.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend deps | `uv sync` | exit 0 |
| Frontend deps | `cd frontend && pnpm install --frozen-lockfile` | exit 0 |
| Targeted backend tests | `uv run pytest tests/unit/test_spending_summary.py tests/unit/test_spending_summary_local.py tests/unit/test_spending_summary_contract.py tests/unit/test_api_summary.py tests/unit/test_api_insights.py -q` | all pass |
| Full backend tests | `uv run pytest tests/ -m "not integration" -q -n 8` | all pass (baseline at planning: 3350 passed, 21 skipped) |
| Lint / format / types | `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` | exit 0, `0 errors` |
| Regenerate API schema | `make openapi && (cd frontend && pnpm codegen)` | exit 0 |
| Regenerate demo API | `(cd frontend && pnpm demo:api-manifest) && uv run python scripts/demo/generate_demo_openapi.py && uv run python scripts/demo/check_demo_api.py` | exit 0 |
| Frontend typecheck | `cd frontend && pnpm exec tsc -b` | exit 0 |
| Frontend tests | `cd frontend && pnpm test` | all pass |
| Frontend lint/format | `cd frontend && pnpm lint && pnpm format:check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `src/finance/spending_summary_base.py`
- `src/api/routers/summary.py`
- `src/api/models/summary.py`
- `src/api/models/insights.py`
- `src/api/main.py` (only `DecimalJSONResponse.render`)
- `frontend/src/lib/summaryPace.ts`
- `frontend/src/lib/summaryPace.test.ts` (add tests)
- `tests/unit/test_spending_summary.py`, `tests/unit/test_spending_summary_local.py`, `tests/unit/test_spending_summary_contract.py`, `tests/unit/test_api_summary.py`, `tests/unit/test_api_insights.py`, `tests/unit/test_api_main.py` (add or update tests)
- Regenerated: `openapi.json`, `frontend/src/types/api.generated.ts`, `frontend/public/demo-api/*`
- `CHANGELOG.md` (one `### Fixed` bullet under `## [Unreleased]`)

**Out of scope** (do NOT touch):

- `scripts/demo/generate_demo_fixtures.ts`: its `Infinity` → `null` regex becomes a harmless no-op. Leave it for a separate cleanup.
- `frontend/public/demo-data/*.json`: the committed demo fixtures already contain `null` where `Infinity` would have been.
- `frontend/src/lib/format.ts`: `formatPercent` already handles non-finite input.
- `src/finance/insights_context.py`: the value passes through unchanged. `briefing_validator.py` ignores `None` leaves because it only walks `int`/`float`.
- Any other response model's float fields.

## Git workflow

- Commit on the current branch. This repo forbids auto-creating branches (root `CLAUDE.md` §Committing).
- Prefer the `/commit` skill (`Skill` tool, `skill: "commit"`). Otherwise match the house format, `<emoji> <type>(<scope>): <Capitalized subject>`, for example `🐛 fix(api): Surface manually added transactions in the dashboard`.
- Stage files by name. Never use `git add -A` or `git add .`.
- Do NOT push or open a PR unless the operator told you to.

## Steps

### Step 1: Return `None` for "no baseline" at the source

In `src/finance/spending_summary_base.py`, change the `else` branch so it
returns `None` when `previous["total_spending"] <= 0` **and**
`current["total_spending"] > 0`. Keep `0.0` when both are 0, since "no change"
is a true statement in that case. Update the docstring to say
`delta_percent` is `None` when the previous month has no spending to compare
against.

Target shape:

```python
        if previous["total_spending"] > 0:
            delta_percent: float | None = float(delta_amount / previous["total_spending"] * 100)
        elif current["total_spending"] > 0:
            delta_percent = None  # no baseline: a percent change is undefined
        else:
            delta_percent = 0.0
```

Then update the three tests that assert `float("inf")` so they assert
`is None`. Rename the contract test to
`test_comparison_zero_previous_yields_null_delta_percent`.

**Verify**: `uv run pytest tests/unit/test_spending_summary.py tests/unit/test_spending_summary_local.py tests/unit/test_spending_summary_contract.py -q` → all pass.
Then `grep -rn 'float("inf")' src/finance/spending_summary_base.py tests/unit/test_spending_summary*.py` → no output.

### Step 2: Make the response models nullable and stop coercing

- `src/api/models/summary.py`: `delta_percent: float | None`. Keep it
  required, with no default: the field is always present and sometimes null.
- `src/api/routers/summary.py:98`: pass the value through without calling `float()` on `None`:
  `delta_percent=None if raw["delta_percent"] is None else float(raw["delta_percent"]),`
- `src/api/models/insights.py:215`: `delta: dict[str, float | None]`.

**Verify**: `uv run pyright src/` → `0 errors`.

### Step 3: Refuse non-finite floats in the JSON renderer

In `src/api/main.py`, add `allow_nan=False` to the `json.dumps` call in
`DecimalJSONResponse.render`. Update the docstring to say it also rejects
NaN/±Infinity, because those are invalid JSON that browsers cannot parse.

**Verify**: `uv run pytest tests/ -m "not integration" -q -n 8` → all pass.
If anything fails with `ValueError: Out of range float values are not JSON compliant`,
see the STOP conditions.

### Step 4: Add regression tests

1. In `tests/unit/test_api_summary.py`, add a test to `TestGetSummary`, using
   the same decorator as the existing tests. Set `mock_run_sync.return_value`
   to `{**_make_comparison(), "delta_percent": None}` and request
   `/api/v1/summary?month=2026-02`. Assert `assert_ok(resp)` and
   `resp.json()["delta_percent"] is None`. Also parse strictly:
   `json.loads(resp.text, parse_constant=_reject)`, where `_reject` raises
   `AssertionError` for `Infinity`/`NaN`.
2. In `tests/unit/test_api_insights.py::TestContextEndpoint`, add a test like
   `test_context_returns_gathered_dict`, but with
   `"delta": {"amount": 234.5, "percent": None}`. Assert the body has
   `body["delta"]["percent"] is None`.
3. In `tests/unit/test_api_main.py`, add a test that
   `DecimalJSONResponse({"x": float("inf")})` raises `ValueError`. Use
   `pytest.raises(ValueError)` around the constructor, which calls `render`.

**Verify**: `uv run pytest tests/unit/test_api_summary.py tests/unit/test_api_insights.py tests/unit/test_api_main.py -q` → all pass, including 3 new tests.

### Step 5: Regenerate the API contract

Run `make openapi && (cd frontend && pnpm codegen)`.
Then regenerate the demo API artifacts with the "Regenerate demo API" command above.

**Verify**: `git diff --stat` lists `openapi.json` and
`frontend/src/types/api.generated.ts`, and possibly files under
`frontend/public/demo-api/`. `grep -n '"delta_percent"' -A6 openapi.json`
shows the schema now allows null (an `anyOf` with `"type": "null"`).

### Step 6: Handle `null` in the frontend

After codegen, `delta_percent` is `number | null`. `pnpm exec tsc -b` will
flag the sites in `frontend/src/lib/summaryPace.ts`. Fix them without changing
the rendered text for non-null values:

- `completeMonthCards`: render the `sub` as `""` when
  `previous.total_spending === 0 || delta_percent == null`.
- `buildHeadline`: return `null` when `data.previous.total_spending <= 0 || data.delta_percent == null`.
  After that guard, TypeScript narrows the type, so the later
  `Math.abs(data.delta_percent)` lines compile unchanged.
- `frontend/src/lib/demoApi.ts:944` already uses `?? 0`. Leave it unless tsc complains.

Add two tests to `frontend/src/lib/summaryPace.test.ts`, following that
file's existing complete-month cases (search for `delta_percent: 15.4`).
One test covers `buildHeadline` returning `null`, and the other covers the
"Total spending" card's `sub` being `""` when `delta_percent: null` and
`previous.total_spending: 0`.

**Verify**: `cd frontend && pnpm exec tsc -b && pnpm test && pnpm lint && pnpm format:check` → exit 0.

### Step 7: Changelog and commit

Add one bullet under `## [Unreleased]` → `### Fixed` in `CHANGELOG.md`.
Create the `### Fixed` subsection if it is absent. The allowed subsection
names are `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` and `Security`.
Suggested wording, in sentence case with no exclamation marks:
"The dashboard summary no longer fails to load for a month that follows a month with no spending. The month-over-month percent is now `null` when there is no baseline."

**Verify**: `uv run python scripts/checks/check_changelog.py` → exit 0. Then commit.

## Test plan

- Updated: 3 backend tests now assert `None` instead of `inf`, on both backends through the contract test.
- New backend tests: summary endpoint with a null delta, strictly parsed. Insights context with a null percent. The renderer rejects `inf`.
- New frontend tests: 2 in `summaryPace.test.ts`.
- Full gate: `uv run pytest tests/ -m "not integration" -q -n 8` and `cd frontend && pnpm test`.

## Done criteria

- [ ] `grep -rn 'float("inf")' src/` → no output
- [ ] `grep -n "allow_nan=False" src/api/main.py` → 1 match
- [ ] `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures
- [ ] `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` → exit 0
- [ ] `make verify-openapi` → exit 0 after the regenerated files are committed
- [ ] `cd frontend && pnpm exec tsc -b && pnpm test && pnpm lint && pnpm format:check` → exit 0
- [ ] `git status --short` shows no modified files outside the in-scope list
- [ ] `plans/README.md` row 001 set to DONE

## STOP conditions

Stop and report back. Do not improvise if:

- Step 3's `allow_nan=False` makes a test outside this plan's files fail with
  "Out of range float values". That means another endpoint also emits
  NaN/Infinity. Report the failing test and endpoint. Do not remove
  `allow_nan=False` to make the failure go away.
- The regenerated `openapi.json` diff touches schemas other than
  `SummaryComparisonResponse` and `InsightsContextResponse`, which means the
  schema had already drifted.
- `pnpm install --frozen-lockfile` fails, or the frontend baseline
  (`pnpm test` before your changes) is already red.
- Any in-scope file doesn't match the "Current state" excerpts.

## Maintenance notes

- Any new ratio field (for example a budget variance percentage) should use
  the same convention: `None` when the denominator is 0, never `inf`.
  `allow_nan=False` now turns a mistake here into a 500 with a clear
  traceback instead of a silent client-side parse failure.
- Reviewers: check that the frontend strings for non-null deltas are
  byte-identical to before. Only the null path is new.
- Deferred: removing the `Infinity` regex in
  `scripts/demo/generate_demo_fixtures.ts`. It's harmless and would need a
  fixture regeneration to prove, so it stays for a separate change.
