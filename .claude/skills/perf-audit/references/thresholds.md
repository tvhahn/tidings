# Thresholds — single source for every number

Every numeric bar the skill uses lives HERE and only here. Checklists, the scanner, SKILL.md,
and reports reference these by name — never restate a literal that could drift. Each entry
carries its source and the date it was last checked. If a number here disagrees with anything
else in this skill, this file wins; if it disagrees with the live tool's output, trust the tool
and flag the drift.

**Last verified: 2026-07-02.** Core Web Vitals thresholds change rarely but do change
(INP replaced FID on 2024-03-12); re-verify against web.dev when citing in a report older
than ~a year.

## Core Web Vitals (assessed at p75; field metrics — lab values are proxies)

| Metric | Good | Needs improvement | Poor | Source |
|---|---|---|---|---|
| INP | ≤200 ms | 200–500 ms | >500 ms | web.dev/articles/inp |
| LCP | ≤2.5 s | 2.5–4 s | >4 s | web.dev/articles/lcp |
| CLS | ≤0.1 | 0.1–0.25 | >0.25 | web.dev/articles/cls |
| TTFB | ≤800 ms | 800–1800 ms | >1800 ms | web.dev/articles/ttfb |

Localhost/self-hosted apps have **no field (CrUX) data** — these bars still anchor severity,
but every value you report against them is Lab or Trace and must be labeled as such
(see `methodology.md` § Metric-Honesty Rule).

## Interaction & main thread

| Bar | Value | Meaning | Source |
|---|---|---|---|
| Long task | >50 ms | blocks input; investigate anything >100 ms | web.dev/articles/optimize-long-tasks |
| TBT (Lighthouse, lab load proxy) | good <200 ms · poor >600 ms | sum of (task − 50 ms) after FCP, emulated mid-tier mobile | web.dev/articles/tbt |
| Frame budget | 16.7 ms (60 fps); ~10 ms for your own work | any interaction commit >16 ms is suspect | web.dev/articles/rendering-performance |
| INP subparts | input delay / processing / presentation | fix the dominant subpart, not the total | web.dev/articles/manually-diagnose-slow-interactions-in-the-lab |
| LCP subparts | TTFB / load delay / load duration / render delay | any subpart **≥40% of total** is dominant → its canned fix direction | web.dev/articles/optimize-lcp |

## Perceived response (NN/g — the UX bars the §0 brand rule scores against)

| Bar | Value | Meaning | Source |
|---|---|---|---|
| Instantaneous | 0.1 s | direct manipulation; **first visual acknowledgement of a click must land here** | nngroup.com/articles/response-times-3-important-limits |
| Flow of thought | 1 s | no feedback needed below this; the worst place to sit is right at/over it | same |
| Attention limit | 10 s | beyond this users task-switch; needs progress indication | same |
| Skeleton/spinner floor | 1 s | below ~1 s a skeleton/spinner just flashes — do not recommend one | nngroup.com/articles/skeleton-screens |

## DOM & presentation

| Bar | Value | Source |
|---|---|---|
| DOM node count | Lighthouse warns ~800, errors ~1,400 total nodes | web.dev/articles/dom-size-and-interactivity |
| DOM depth / width | depth >32, parent with >60 children | same |
| Style recalc (local convention) | flag a recalc >16 ms (one frame) or touching >~1,000 elements during an interaction | derived from frame budget; see snappy-navigation benchmark |

## Network & bundle

| Bar | Value | Source |
|---|---|---|
| Parallel requests | ~6 per HTTP/1.1 host — non-critical t=0 requests can queue critical ones | Advanced React ch. 14; browser networking docs |
| Main bundle | ~170 KB min+gz (mobile guidance) | addyosmani.com/blog/performance-budgets |
| Single dependency | scrutinize anything >30–50 KB gz; flag `moment` on sight | bundlephobia.com; you-dont-need-momentjs |
| Unused JS at load | >40% of initial JS unused (Coverage tab) → split | web.dev/articles/code-splitting-suspense |

## Backend latency

| Bar | Value | Source |
|---|---|---|
| Reporting | p50/p95/p99 + max from ≥20 repeated requests — **never the mean** | sre.google/sre-book/monitoring-distributed-systems; Gil Tene, How NOT to Measure Latency |
| Localhost API expectation | an endpoint >250 ms mean on localhost with local storage deserves a look; >1 s is a finding | local convention (this repo measured 3–161 ms) |

## Measurement discipline

| Rule | Value | Source |
|---|---|---|
| Noise floor | ~10% run-to-run; a change must beat it across ≥3 runs or it is reverted | brendangregg.com/methodology |
| Re-measurement | same CPU throttle, same build (dev vs preview), same run count as the baseline | methodology.md § scientific loop |
| CPU throttle sweep | 1× (daily-driver desktop), 4× (mid-range laptop), 6× (stress) | web.dev INP guidance; snappy-navigation practice |
| Amdahl bound | a fix on code that is p of the trace can win at most ~p | UC Berkeley CS61C notes on Amdahl's law |
