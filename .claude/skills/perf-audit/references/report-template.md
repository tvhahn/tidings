# Report template — fill every section

Copy this skeleton into the saved report and fill it. **Empty sections signal an incomplete
audit** — if a section is legitimately N/A (e.g. no backend findings), write one line saying
why, never delete the heading silently. No emoji, no letter grades, no "executive dashboard"
chrome; brand voice applies to every sentence.

---

# Performance audit — <target> — <YYYY-MM-DD>

**Status:** Analysis
**Mode:** Deep (live traces) | Quick (static-only — every impact is `potential impact`)
**Scope:** <pages/interactions audited, and what was explicitly out of scope>

## Scorecard

> Artifacts used: <trace files / Lighthouse runs / scanner output — enumerate them>
> Surface / build: <dev :5173 | preview :4173>, CPU <1×/4×/6×>, <n> runs per number

| Metric | Value | Source | Target | Status |
|---|---|---|---|---|
| INP — <interaction 1> | <ms or `not measured`> | Trace (DevTools) | ≤200 ms | |
| INP — <interaction 2> | | Trace (DevTools) | ≤200 ms | |
| First acknowledgement — <interaction> | | Trace (DevTools) | ≤100 ms | |
| Long tasks during interaction (count / max) | | Trace (DevTools) | 0 >50 ms | |
| Biggest style recalc (ms / elements) | | Trace (DevTools) | <16 ms | |
| DOM nodes (at rest) | | Trace (DevTools) | <1,400 | |
| TBT (load) | | Lab (Lighthouse) | <200 ms | |
| Main bundle (gz) | | Lab (build) | ~170 KB | |

Field (CrUX) column omitted: localhost target — no field data exists. Unmeasured cells say
`not measured`. Targets from `thresholds.md`; do not restate numbers from memory.

## Five-question summary

1. What did the user report, in one line?
2. What is the measured cause? (one sentence, with the dominant INP subpart or trace event)
3. What single fix has the largest Amdahl-bounded win?
4. What regressed vs the overlay's baselines, if anything?
5. What was NOT measured, and why?

## Deterministic findings (scanner)

`perf-grep.mjs` output summary: <P0/P1/P2 counts, files scanned, caps hit if any>.
P0 hits are the **same-day removal list**:

| Rule | Where | Why it costs | Counter-move |
|---|---|---|---|

## Findings

Ordered by severity (Critical → Info), then impact × effort. Each finding:

### <n>. <title>
- **What:** <one sentence>
- **Where:** `file:line` or trace insight name
- **Impact:** `measured: <number, source label, throttle>` or `potential impact`
- **Why:** <mechanism, one or two sentences; cite the checklist rule + book §/fallback>
- **Fix:** <specific, §0-compliant direction; name the file(s) to touch>
- **Verify:** <the exact re-measurement: same interaction, same throttle, expected delta>

## Positive observations

What is already well-decided (seed from the overlay preserve-list, plus anything newly found
that's working). This tells the next audit what to preserve.

## Recommendations

### Now (this week — highest impact × effort, measured)
| # | Fix | Predicted delta | Effort |
|---|---|---|---|

### Next (this month)
| # | Fix | Rationale |
|---|---|---|

### Later / parked (explicit "not now" notes)
| # | Item | Why parked |
|---|---|---|

## Regression guard

How these wins stay won: scanner `requiredPatterns` added/updated, budgets proposed
(size-limit / Lighthouse CI), or at minimum "re-run `/perf-audit` after each Now-tier fix
with the same throttle + run count."

## Methodology appendix

Baseline conditions (build, throttle, runs, date), tools + versions, what Quick mode skipped
(if applicable), noise-floor note (~10%), and any Lighthouse audits that could not be parsed
(v13 insight-audit drift).
