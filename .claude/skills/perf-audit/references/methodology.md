# Methodology — how this audit thinks

Read fully before measuring. This file is project-agnostic; every repo-specific anchor lives in
[`project-overlay.md`](./project-overlay.md). All numbers referenced here are defined in
[`thresholds.md`](./thresholds.md).

## 1. Problem statement first (Gregg)

Before opening any tool, answer in writing:

1. What makes you (or the user) think it's slow? A number, a feeling, a complaint?
2. Has it ever been fast? What changed — deps, data volume, a feature, a refactor?
3. Can the symptom be expressed as latency ("click → paint = 1.2 s") or run-time?
4. Who/what else is affected — one page, one interaction, everything?
5. What's the environment — device, CPU class, network, dev build vs production build?

"What changed" is usually the highest-information answer; for data-driven dashboards it is
usually data growth, which points at list rendering before anything else.

## 2. Classify into a RAIL bucket

Each bucket has a different instrument and fix family. Misclassifying wastes the audit
(code-splitting to fix a re-render problem, etc.).

| Bucket | Symptom | Primary metric | Primary instrument |
|---|---|---|---|
| **Response** | click/type/switch lags | INP + subparts | DevTools trace of the interaction |
| **Animation** | scroll/drag stutters | frame time | trace, Rendering panel |
| **Load** | first paint slow | LCP, TBT | Lighthouse |
| **Bundle** | everything slow to arrive | JS bytes, coverage | build stats, treemap |

For an already-loaded interactive dashboard, the pain is almost always Response + Animation —
weight the audit accordingly, and check the overlay's weighting rule before spending time on
backend or bundle work.

## 3. The Metric-Honesty Rule (non-negotiable)

Never fabricate a number from static code reading. Every value in the scorecard and every
finding's impact line is labeled with its source:

- **`Lab (Lighthouse)`** — a Lighthouse run you executed.
- **`Trace (DevTools)`** — a performance trace / network log / script evaluation you captured.
- **`Field (CrUX)`** — real-user data. For localhost/self-hosted targets this is
  **structurally unavailable**: omit the Field column or mark it `—`, and say why once.

Unmeasured scorecard cells say **`not measured`** — never a guess, never an extrapolation.
Findings from static analysis alone are tagged **`potential impact`**, not given an invented
millisecond value. Lab and field data are not interchangeable; presenting one as the other is
a form of fabrication.

**Violating this rule is worse than returning no scorecard at all.**

## 4. Quick vs Deep mode

- **Deep (default when a live target + Chrome DevTools MCP are available):** static pass +
  live traces. The scorecard has real numbers.
- **Quick (degraded mode — no browser available):** static pass only. Every finding is
  `potential impact`; the scorecard's value column is `not measured` throughout; say plainly
  at the top that no measurement was possible and what to re-run to get one.

Never silently pretend Quick mode produced Deep-mode evidence.

## 5. The measurement loop

1. **Baseline artifact before touching anything** (Knuth's actual point: chase the critical
   3% *after* measurement identifies it; intuition "is reliably wrong" — Pike's Rule 1:
   bottlenecks turn up in surprising places). A trace or Lighthouse JSON with a specific
   number attached ("INP for month-switch = 640 ms, 4× CPU, dev build").
2. **Profile to attribute.** Understand every trace frame above ~1% of the interaction.
   Decompose INP into its three subparts and name the dominant one.
3. **Amdahl-bound every candidate.** A fix on 5%-of-trace code cannot win more than ~5%.
   Rank by the measured share `p`, not by how famous the fix pattern is.
4. **Isolate by bisection** where attribution is ambiguous — stub the chart vs stub the
   table, re-measure once, learn which subtree owns the cost.
5. **One hypothesis at a time, with a predicted number.** "Removing the container dim should
   cut the recalc from ~659 ms to <100 ms" — then verify.
6. **Re-measure under identical conditions** — same throttle, same build, same run count.
   A change that doesn't beat the ~10% noise floor across ≥3 runs is reverted, not kept
   "just in case."

Named anti-methods to refuse: Random Change ("turn a knob, keep it if it seems better"),
Traffic-Light ("dashboard's green, ship it"), and Lighthouse-Only (lab *load* score standing
in for the interaction the user actually complained about).

## 6. Prioritize

Severity is CWV-anchored, five tiers:

| Tier | Meaning |
|---|---|
| **Critical** | causes a Core Web Vital to fail "Good" at the measured p75-equivalent, or a deterministic P0 scanner hit |
| **High** | user-perceivable on every use of a common interaction (breaks the 0.1 s / 1 s NN/g bars) |
| **Medium** | measurable cost, intermittent or secondary path |
| **Low** | real but small; batch with other work |
| **Info** | observation / regression-guard note; no action needed now |

Rank recommendations by **impact × effort**: impact = predicted metric delta from the trace
(Amdahl-bounded), reach = how often the interaction fires, effort = dev-time. Present the top
3–5; park the rest with an explicit "not now" note. Deterministic P0 scanner hits additionally
go on a same-day "anti-patterns to remove" list regardless of ranking.

**Weighting rule:** Souders' Golden Rule says most response time is frontend — but verify per
repo. The overlay records the measured split; if TTFB/Server-Timing shows the backend is fast,
say so once and spend the audit's depth client-side.

## 7. Common rationalizations (rebut on sight)

| Rationalization | Reality |
|---|---|
| "We'll optimize later" | performance regresses the moment feature work resumes; later never has a baseline |
| "It's fast on my machine" | a dev laptop at 1× hides exactly the jank users report; sweep 4×/6× |
| "This optimization is obvious" | obvious fixes on unmeasured code are how memo-fog and dead `useMemo` accumulate |
| "The framework handles performance" | frameworks schedule work; they don't shrink your DOM or your payloads |
| "A fetching library makes the app performant" | React Query removes *classes* of bugs (races, refetch storms); it does not fix render cost or render-gated waterfalls |

## 8. Failure patterns (for the auditor)

- **Optimize-without-measuring** — any fix proposed with no baseline number and no
  `potential impact` tag violates §3.
- **Wrong metric** — quoting LCP for an interaction-lag complaint; TBT for scroll jank.
- **Over-optimizing the wrong axis** — shaving 10 ms of TTFB while CLS is 0.4.
- **Lighthouse-only** — the trace of the actual interaction is the instrument; Lighthouse is
  a load-time backstop.
- **Single-page-only** — the reported page may not be the worst page.
- **Treating every byte as equal** — JS costs parse+compile+execute; images don't.
- **Bundle-size obsession** — for an already-loaded SPA, render cost usually dominates.
- **Ignoring third parties** — attribute trace time to origin before blaming app code.
- **Decorating the wait** — proposing a spinner/skeleton/shimmer where the fix is removing
  the wait (the §0 brand rule in SKILL.md; NN/g skeleton floor in `thresholds.md`).

## 9. When to call it done

The audit ends when: the reported symptom has a measured cause and an Amdahl-ranked fix list;
each Now-tier fix has a predicted delta and a verification recipe (same throttle + run
count); remaining findings are explicitly parked; and a regression gate exists (the scanner's
guards, a budget, or at minimum "re-run this skill after each fix"). Perfection is not the
bar — an honest scorecard and a short, correct Now list is.
