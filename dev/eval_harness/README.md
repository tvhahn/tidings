# Prompt evaluation harness

A self-contained Streamlit app for A/B testing prompt + context + model variants
for the Tidings daily summary feature. The user is the judge; rankings
accumulate across sessions and aggregate by Borda count.

**Spec:** `docs/specs/_archive/2026-05-07-prompt-eval-harness/spec.md` (local-only, absent in the public repo).

Lives in `dev/`. Not shipped. Writes to `data/eval-harness/` (gitignored).

## Quick start

```bash
# 1) Install eval extras
uv sync --extra eval

# 2) CLI smoke test — writes one cache cell
uv run python -m dev.eval_harness.runner V0_baseline 2026-04-01 1 --demo

# 3) Streamlit UI on 0.0.0.0:8501
make dev-eval-harness
```

The UI defaults to `data/demo.db` (toggle in sidebar to use `data/finance.db`).
First run picks ≤6 diverse April 2026 days via the heuristics in `picker.py`.

### Port

The UI binds `0.0.0.0:8501`. Override with
`make dev-eval-harness EVAL_HARNESS_PORT=8520` if 8501 is taken — if you change
it permanently, update the devcontainer `docker-compose.yml` `ports:` block to
match.

## What lives where

```
dev/eval_harness/
├── app.py              # Streamlit grid, drag-rank, persistence
├── variants.py         # Variant dataclass + V0–V5 instances
├── windowed_context.py # gather_as_of(year_month, day_n) — windows monthly insights
├── picker.py           # pick_diverse_days(month) → list[date]
├── runner.py           # run_variant(...) + cache I/O + CLI entry
├── voice_gate.py       # detect_voice_violations(text) per docs/brand/voice.md §3
├── aggregate.py        # borda_score / borda_per_day over rankings/*.jsonl
└── README.md           # this file

data/eval-harness/      # gitignored, created on first run
├── session.json                            # last-write-wins UI state
├── cache/<variant>__<YYYY-MM-DD>__<N>.json # one file per (variant, day, sample)
└── rankings/<YYYY-MM-DD>.jsonl             # ranking events, one per line
```

## Variants (initial six)

| Name | Hypothesis | Model | Context | Prior days | Parse |
|---|---|---|---|---|---|
| **V0_baseline** | DAY_PROMPT_TEMPLATE as-shipped is the bar | sonnet | full (17 keys) | 0 | identity |
| **V1_terse** | ≤15 words beats ≤25 | sonnet | full | 0 | identity |
| **V2_thin** | Monthly insights add noise | sonnet | drop trend / anomalies / deltas | 0 | identity |
| **V3_json** | Forcing a `why` field disciplines the headline | sonnet | full | 0 | `json.loads(s)["headline"]` |
| **V4_haiku** | Haiku 4.5 is good enough at fraction of cost | haiku | full | 0 | identity |
| **V5_continuity** | Yesterday's summaries help today's framing | sonnet | full | 2 | identity |

`temperature` is intentionally absent — the Claude Code CLI doesn't expose it.
V3's structured output is JSON-via-prompt + manual parse (instructor is API-only).

## Adding a new variant

1. Edit `variants.py`. Either:
   - Reuse `DAY_PROMPT_TEMPLATE` and tweak `context_field_set` / `model` / `prior_day_summaries`, or
   - Build a new template by `.replace()`-ing parts of `DAY_PROMPT_TEMPLATE`.
2. Append the instance to `ALL_VARIANTS` so the app picks it up.
3. Editing an existing variant's `prompt_template`, `context_field_set`, or
   `model` changes its `Variant.hash()` → only that variant's cells go stale on
   next read; everything else stays.

The harness reuses the production prompt machinery via two small refactors in
`src/finance/summary_provider.py`:

- `prepare_template_fields(ctx)` (extracted from `build_day_prompt`) — derives
  `top_items`, `actual_pace_line`, `budget_line`, etc., from a context dict.
  Variants get to swap in their own template while still benefiting from the
  same derivations.
- `run_cli_provider(..., model="sonnet")` — the model kwarg is what makes V4
  reachable.

## Windowed context

Production batches the whole month into one prompt, so every day sees every
other day's transactions. The harness optimizes the per-day case:
`gather_as_of(month, day_n)` returns a context where anomalies and category
deltas are computed using only transactions through day_n. The trick is a thin
`WindowedSpendingSummary` shim that filters `query_month` results by
`date_file_name[:10] <= "<year-month>.<day_n>"`. `BudgetService.get_category_anomalies`
and `gather_context` are reused unchanged — they just see fewer rows.

`trend`, `previous_month`, and `historical_averages` are unaffected by the
windowing — they're already prior-window.

## Voice gate

`voice_gate.detect_voice_violations(text)` flags four families of brand-voice
issues, verbatim from `docs/brand/voice.md` §3:

- **Forbidden words** — `unlock, supercharge, crush, …, disrupt`
- **Exclamation marks** — any `!`
- **ALL-CAPS labels** — 3+ consecutive uppercase, allowlist for `USD, MTD, AWS, CIBC, …`
- **Evaluative phrases** — `solid start, nice job, keep an eye on, …`

The sidebar checkbox **Hide voice-violating outputs from ranking** filters
flagged cells out of the drag list and the Borda totals.

## Aggregation (Borda)

Each saved ranking is one JSONL line in `rankings/<day>.jsonl`. For an event
with `N` ranked variants, position-`i` (1-indexed) earns `N - i` points.
`aggregate.borda_score(events)` sums across every event in the log; older and
newer events count equally. To recover from a changed mind, re-rank — newer
events stack on top.

## Caveats

- **CLI cost.** Each cell hits the Claude Code CLI. A full grid (6 variants × 6
  days × 3 samples = 108 calls) at ~10s/call is about 18 minutes wall-clock.
- **V5 prior-day source.** Reads `data/journal/<DD>.txt` directly, which were
  generated by the production batch path that leaks future-day info. Truly
  clean continuity would regenerate prior-day summaries with V0 first; v1
  accepts the leak.
- **Single-user.** No auth, no concurrent ranking; one filesystem, one judge.
