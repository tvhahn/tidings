# Frontend checklist — React render, interaction latency, data fetching

Framework truths (React), project-agnostic. Repo anchors, carve-out lists, and scanner config
live in [`project-overlay.md`](./project-overlay.md); all numeric bars in
[`thresholds.md`](./thresholds.md).

**Citations:** when the overlay says the *Advanced React* book is present, cite findings with
the file + § given in the pointer map (§6 below) and quote the mechanism from the chapter.
When it is not, use the fallback citations (developerway.com is the same author; react.dev for
API semantics). Rules never depend on the book — only depth and quotation do.

Two strata of checks:

- **Deterministic (scanner)** — `scripts/perf-grep.mjs` encodes the high-precision subset;
  its hits are the audit's floor. Don't re-derive them by eye; run it.
- **Guided grep + judgment (this file, §5)** — patterns the scanner can't decide alone. Run
  the grep, then judge each hit against the stated carve-outs.

## 1. Rule inventory

Each rule: **id · what · why it costs · how to detect · fix direction**. Fix directions must
pass the §0 brand rule in SKILL.md (remove/prefetch/defer/scope — never decorate).

### Re-render model (R)

- **R1 — State update is the only initial re-render trigger.** Re-renders cascade *down* the
  whole subtree from the state owner, never up. "Props changed" is not a trigger for
  un-memoized components — the parent re-rendering is. Detect: trace/profiler shows a wide
  subtree re-rendering on a small interaction. Fix: find the state owner, then R2/R3.
- **R2 — Move state down (composition before memoization).** State only one region needs
  (search text, hover, modal flag) belongs in a small child. Detect: typing/hovering
  re-renders siblings unrelated to the input. Fix: colocate the state; only then consider memo.
- **R3 — Elements passed as props/children don't re-render with the receiver.** An element
  created in the parent's scope is referentially stable (`Object.is`) when the *receiver's*
  state changes — free isolation, no memo. Fix direction for "slow wrapper around cheap
  children": pass the heavy subtree as `children` to the state-owning wrapper.
- **R4 — Custom hooks hide state but not its re-renders.** State inside a hook re-renders the
  *host component*, transitively through hook chains. High-frequency sources (resize, scroll,
  interval, mousemove) inside a hook used by a page-level component are a classic finding.
  Detect: grep `addEventListener\|setInterval` inside `hooks/`; check who consumes the hook.
- **R5 — False-positive guard: creating an element is cheap.** `const footer = <Footer/>` or a
  route `element={<Page/>}` creates an object; it renders nothing until placed. Do NOT flag
  element creation before a conditional.

### Memoization (M)

- **M1 — One unstable non-primitive prop silently defeats `React.memo` entirely.** Inline
  object/array/function/JSX, or an unmemoized value derived in the parent. Detect: memoized
  component still re-renders every parent render (profiler), or guided grep §5. Fix:
  stabilize *all* non-primitive props, or drop the memo (M4).
- **M2 — Never spread upstream props into a memoized child** (`<Memo {...props}/>`) — any
  unstable member re-breaks it invisibly. Scanner: `spread-into-memo`.
- **M3 — Inline `children` break a memoized parent.** `<MemoParent><div/></MemoParent>` makes
  a fresh element object per render; memoizing the child *component* doesn't help — the
  element must be stable (`useMemo` it or hoist it).
- **M4 — Dead memoization is pure cost.** `useMemo`/`useCallback` whose result never crosses a
  memoized boundary or a dep array does nothing but allocate. Fix: delete it. Do NOT
  recommend adding `useCallback` to plain DOM handlers.
- **M5 — `useMemo(fn(), deps)` runs every render** — the first argument must be a function,
  not a call. Scanner: `memo-first-arg-invocation`.
- **M6 — "Expensive calculation" requires measurement.** Re-render cost usually dominates JS
  cost (sorting hundreds of items is ~ms; re-rendering the list is tens of ms). Before
  blessing a `useMemo` as "expensive," check the trace.

### Reconciliation & keys (K)

- **K1 — Component declared inside another component = remount every render.** New function
  identity = new element `type` = full unmount/mount (state loss, effects refire). One of the
  biggest React performance killers. Detect: guided grep §5 (needs judgment — render-prop
  callbacks are fine).
- **K2 — Same type + same position across a conditional shares state wrongly.** Two sibling
  `<Input/>`s swapped by a ternary keep each other's state. Fix: distinct `key`s or distinct
  slots.
- **K3 — `key={index}` on dynamic lists** (reorder/insert/remove) breaks state association and
  defeats item memoization. Fine on static arrays — scanner flags for review, you decide.
- **K4 — `key`-reset forces a full remount** — legitimate technique, not free on heavy
  subtrees; flag only when the subtree is large and the reset fires per keystroke/hover.

### Context (C)

- **C1 — Any provider-value change re-renders every consumer.** `React.memo` on a consumer
  cannot stop it. Blast radius = consumer count × their subtrees.
- **C2 — Always memoize the provider `value`** (and `useCallback` the functions in it). Inline
  `value={{…}}` re-renders all consumers on every provider render — the one place "memoize by
  default" is correct. Scanner: `context-provider-inline-value`.
- **C3 — Split state-context from API-context.** Consumers that only call actions shouldn't
  re-render on data changes; `useReducer` gives a dependency-free API value (`useMemo(…, [])`).
- **C4 — Context "selectors" via `useMemo` don't work** — the consumer still re-renders. The
  only emulation is an HOC whose inner component is `React.memo` fed the slice as a prop. Do
  NOT recommend `useMemo`-as-selector.

### Closures & debounce (L, D)

- **L1 — `eslint-disable react-hooks/exhaustive-deps` is a high-signal target.** A suppressed
  dep is either a latent stale closure or the reason someone later "fixes" it by breaking
  memoization. Scanner reports every suppression (report-only); review each.
- **L2 — `useRef(fn)` freezes the closure at mount** — needs a `useEffect` refresh to stay
  current.
- **L3 — Custom `React.memo` comparator = latent stale-closure bug** — a comparator that
  ignores some props keeps old closures alive. Scanner: `memo-custom-comparator`
  (review-always).
- **L4 — Recognize the ref escape hatch; don't flag it.** A depless effect refreshing
  `ref.current = fn` + a `useCallback([], (…) => ref.current(…))` is the *prescribed* pattern
  for stable-yet-fresh callbacks. Its empty deps are correct.
- **D1 — `debounce()`/`throttle()` created un-memoized in a component body is silently just a
  delay** — a new timer per render, so nothing ever coalesces. Scanner: `debounce-in-render`.
- **D2 — Never debounce the controlled input's `setValue`** — the input lags the keyboard.
  Debounce the slow side effect (the fetch, the filter) instead.
- **D3 — The sanctioned fix is the ref-escape `useDebounce`** (debounce built once in
  `useMemo([])` around `ref.current`). `.cancel()`-in-cleanup works for debounce but breaks
  throttle semantics.

### Paint & flicker (F)

- **F1 — DOM-measure → `setState` in `useEffect` = two paints = flicker.** That narrow case
  (geometry read + immediate state write) is what `useLayoutEffect` is for. Scanner:
  `dom-measure-in-useEffect`.
- **F2 — `useLayoutEffect` is synchronous and blocks paint** — a scalpel, not a default. Flag
  any use with no geometry read inside. Scanner: `useLayoutEffect-no-measure`.

### Data fetching & waterfalls (W)

- **W1 — Waterfalls come from render-gating.** `if (!data) return <Spinner/>` above a child
  that fetches means the child's query can't even mount — **React Query does not auto-fix
  this.** Detect: stair-step in `list_network_requests` where request N starts as N−1
  finishes. Fix: hoist/parallelize (`useQueries`), prefetch at the router/parent, or lift the
  gate below the fetch.
- **W2 — ~6 parallel requests per HTTP/1.1 host.** Non-critical requests fired at t=0 can
  queue critical ones. Detect: >6 simultaneous requests at load with critical data waiting.
- **W3 — Module-scope `fetch()` is a red flag** — uncontrolled, steals connection slots,
  un-deduped. Sanctioned forms: router-loader / `prefetchQuery`, and prefetch inside lazy
  chunks. Scanner: `module-scope-fetch` (with those carve-outs).
- **W4 — Raw `fetch`+`setState` in `useEffect` outside the API layer** is both a convention
  violation and the only place fetch race conditions can live (a query library makes them
  structurally impossible). Scanner: `raw-fetch-in-effect`, allow-list from the overlay.
- **W5 — "Performant" is the story the screen tells while loading.** Decide what appears
  first / while-loading / when-done, in reading order — this is the product framing for
  scoping Phase 0, and the lens for judging loading affordances in §4.

### Interaction latency (I) — the folded-in responsiveness layer

- **I1 — Whole-subtree dim as a loading affordance is a style-recalc bomb.** Toggling
  `opacity-*`/`transition-opacity` on a container wrapping a large `.map` forces computed-style
  recalculation for every descendant — the affordance meant to mask the wait *causes* it, and
  it fires before the fetch can start. Scanner: `dim-container-loading-affordance` (**P0**).
  Fix: small fixed-size hint outside the subtree (never a spinner overlay per §0).
- **I2 — First acknowledgement within 0.1 s, separate from data-settled.** The header/controls
  should flip on the click's first frame (urgent state), with the heavy data subtree following
  at transition priority (two-state split / `startTransition` / `useDeferredValue`). Note:
  React Router v7 already transition-wraps navigations including `setSearchParams` — check the
  overlay before prescribing manual wrapping.
- **I3 — `content-visibility: auto` + `contain-intrinsic-size` on repeated off-screen
  cards/rows** caps style/layout to the viewport instead of the whole list. Pure CSS, zero
  visual change; typically the single cheapest presentation win on long list pages.
- **I4 — Data readiness:** month/page-scoped queries want a deliberate `staleTime`,
  `placeholderData: keepPreviousData` (in-place refresh for an oriented user beats a blank),
  and intent-based prefetch (hover/adjacent). Scanner: `staleTime-zero-on-month-query`,
  `keepPreviousData-regression-guard`, `month-prefetch-gap` (overlay-configured).
- **I5 — Both-layouts-in-DOM doubles row cost.** Shipping desktop (`hidden lg:flex`) and
  mobile (`lg:hidden`) trees simultaneously ≈ 2× nodes per row; hover-only button clusters
  mounted on every row add pure chrome. Fix: one layout behind a JS media query; lazy-mount
  hover chrome.
- **I6 — Virtualize only when measurements demand it** — after I3/I5, if INP is still over the
  bar on long lists. Variable-height cards make windowing risky; prefer content-visibility
  there.

## 2. Do NOT recommend (myth list — plausible and wrong)

- Memoize-everything, or `useCallback` on plain DOM handlers (M4).
- `React.memo` on context consumers to stop context re-renders (C1 — it can't).
- `useMemo` as a context selector (C4 — it can't).
- **Suspense as a waterfall fix** — it changes *where* the fallback shows, not when fetches
  start; render-gating persists.
- **Refs to "avoid re-renders" of render-driving data** — a ref update doesn't render, so the
  screen is simply stale; refs are not a performance tool.
- `key`-remount as a race/staleness fix — it papers over a fetch-layer bug at remount cost.
- A spinner/skeleton/shimmer as the cure for sub-1 s lag (§0 brand rule + NN/g skeleton floor).
- Framework idioms the stack doesn't use (SSR/RSC advice for a Vite SPA, etc.).

Myth-bust in prose when they appear in the codebase's comments or the user's framing:
"props change causes re-renders" (false without memo); "`useMemo` is cheaper than
`useCallback`" (both recreate the first-arg function); "`key` improves list performance"
(identity only); "async/await avoids race conditions"; "a fetching library makes the app
performant by itself".

## 3. Do NOT flag (carve-outs)

- Elements created before a conditional (R5).
- `key={index}` on static, never-reordered arrays (K3).
- The L4/D3 ref-escape pattern's empty dep arrays.
- Stable-by-contract values omitted from deps: `useState` setters, `dispatch`, refs.
- `placeholderData: keepPreviousData` — present by design where the overlay says so.
- Calm restraint (no skeleton where content holds; quiet inline hints) — that's the brand
  working, not a gap.
- Everything on the overlay's preserve-list ("already well-decided — do not re-fix").
- One clarification if portals come up: a portal is a DOM relocation, **not** a re-render
  boundary — don't recommend portaling to cut re-renders.

## 4. Loading-affordance honesty (§0 applied)

For every loading state touched by an audited interaction: is it layout-stable (no CLS)? calm
(no shimmer/spin/whole-subtree dim)? honest (shows real prior content when the user is already
oriented — stale-while-revalidate — and a skeleton only for >1 s cold loads)? A metric
improved by *adding* decoration fails the audit even if the number dropped.

## 5. Guided greps (judgment required — not scanner rules)

Run these; each hit needs the stated human call:

| Grep | Judge |
|---|---|
| inline object/array/fn props at known-memoized call sites | is the prop actually unstable across renders? (M1) |
| `const [A-Z]\w* = ` or `function [A-Z]` *inside* a component body | component definition (K1 defect) vs render-prop callback (fine)? |
| state consumed only by a small region but owned by a page component | moving-state-down candidate (R2)? |
| `addEventListener\|setInterval\|ResizeObserver` inside `hooks/` + `setState` | high-frequency re-renders into a big host (R4)? |
| sequential `await`s of independent requests | parallelize with `Promise.all`/`useQueries`? |
| `if (!data) return` above children that fetch | render-gated waterfall (W1)? |
| `useMemo`/`useCallback` whose value hits no memo boundary/dep array | dead memoization (M4) — delete? |
| `useRef(` holding a function without an effect refresh | frozen closure (L2)? |
| debounced `setValue` of a controlled input | D2 violation? |

## 6. Pointer map — Advanced React book (when the overlay says it's present)

Read the cited § before writing a finding that leans on the mechanism; quote it, cite
`<file> § "<heading>"`. Fallback citations when absent: developerway.com/posts (same author,
same rules) and react.dev API pages.

| Need | Read |
|---|---|
| Re-render model, downward propagation, props myth | `03_ch01-intro-to-re-renders.md` §§ "State update, nested components, and re-renders", "The big re-renders myth" |
| Moving state down | `03_ch01…` § "Moving state down" |
| Custom-hook re-render danger | `03_ch01…` § "The danger of custom hooks" |
| Element identity / `Object.is` / children-as-props isolation | `04_ch02-elements-children-as-props.md` §§ "Elements, Components, and re-renders", "Children as props" |
| Elements-are-cheap false-positive guard | `05_ch03-configuration-with-elements-as-props.md` § "Conditional rendering and performance" |
| How memo breaks (props, spread, children) | `07_ch05-memoization.md` §§ "What is React.memo", "React.memo and props from props", "React.memo and children" |
| Dead memoization; measure-first | `07_ch05…` §§ "Antipattern: memoizing props", "useMemo and expensive calculations" |
| Type+position diffing; keys; remount killer | `08_ch06-diffing-and-reconciliation.md` §§ "Reconciliation and state update", "Why we can't define components inside other components", "\"Key\" attribute and memoized list", "State reset technique" |
| Context blast radius, memoized value, split providers, selectors | `10_ch08-context-and-performance.md` §§ "Context value change", "Preventing unnecessary Context re-renders: split providers", "Reducers and split providers", "Context selectors" |
| Stale closures; ref escape hatch | `12_ch10-closures-in-react.md` §§ "The stale closure problem", "Stale closures in React: useCallback/Refs/React.memo", "Escaping the closure trap with Refs" |
| Debounce/throttle in React | `13_ch11-debouncing-and-throttling.md` §§ "Debounced callback in React: dealing with re-renders", "…dealing with state inside" |
| Flicker / useLayoutEffect / paint model | `14_ch12-escaping-flickering-ui.md` §§ "What is the problem with useEffect?", "Why the fix works: rendering, painting, and browsers", "Back to useEffect vs useLayoutEffect" |
| Waterfalls, browser cap, module-scope fetch, Suspense | `16_ch14-data-fetching-and-performance.md` §§ "Requests waterfalls: how they appear", "Browser limitations and data fetching", "What if I fetch data before React?", "What about Suspense?" |
| Race conditions (why a query layer is safe; what bypasses look like) | `17_ch15-data-fetching-race-conditions.md` §§ "Promises and race conditions", "Fixing race conditions: cancel all previous requests" |
| Ref-vs-state semantics | `11_ch09-refs-storing-data-to-imperative-api.md` §§ "Ref update doesn't trigger re-render", "When can we use Ref then?" |

Deliberately omitted (no audit signal): ch. 7 (HOCs), ch. 13 (portals — see the §3
clarification), ch. 16 (error handling), ch. 12's SSR section for a Vite SPA.

## 7. Live interaction protocol (Deep mode)

Per audited interaction (e.g. month nav, filter typing, tab/route switch, long-list scroll):

1. `performance_start_trace` → perform the interaction → `performance_stop_trace` →
   `performance_analyze_insight`. Decompose INP into input delay / processing / presentation;
   attribute long tasks (>50 ms) to script vs Recalculate Style vs Layout.
2. **First-acknowledgement wall clock** vs the 0.1 s bar, reported separately from
   data-settled time.
3. **Style-recalc cost** — element count + duration of the biggest Recalculate Style event;
   DOM node count/depth via `evaluate_script`
   (`document.querySelectorAll('*').length`, max depth walk).
4. `list_network_requests` — fetch-start delta after the click (a fetch starting hundreds of
   ms late is the main-thread-blocked signature), stair-step waterfalls, t=0 request count vs
   the ~6-connection cap.
5. **CPU throttle sweep** via `emulate`: 1×, 4×, 6×. Re-verify magnitudes on the production
   preview build before trusting dev-build numbers (dev inflates scripting, but DOM/recalc
   costs persist).
6. `lighthouse_audit` as a coarse TBT/bundle backstop only — it measures lab *load*, not the
   interaction. Lighthouse v13+ consolidated many per-opportunity audits into insight audits:
   treat named audits as hints, parse what's actually in the JSON, and note anything you
   couldn't parse rather than inventing it.
7. Optional `evaluate_script` PerformanceObserver snippets for Trace-labeled attribution:
   LCP element, layout-shift sources, `event` entries with `durationThreshold: 40`.
8. `list_console_messages` — React errors/warnings during the interaction are their own
   finding.
9. §0 check on every loading affordance the interaction shows (see §4).

Report each number with its source label and the throttle/build it was captured under.
