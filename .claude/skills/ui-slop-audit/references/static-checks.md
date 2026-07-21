# Static checks — deterministic rule registry (ui-slop-audit v2)

The **deterministic stratum** of the audit (tells-catalog §3): the checkable-against-tokens
tells that a stranger would flag on sight, so they *gate* a family's score rather than average
into it. These rules were **hand-transcribed from the *shape* of Impeccable's `antipatterns.mjs`
at a pinned commit** (`github.com/pbakaus/impeccable`, Apache-2.0) and rewired to Tidings' own
`@theme` tokens. Nothing was installed: no `npx impeccable`, no `npx skills`, no plugin, no
PostToolUse hook — the research README §3 finding is that the risk is always the *install
channel*, not the bytes, so we vendor static text only (research README §3, spec README §"Security
constraints").

`scripts/slop-grep.mjs` **runs this registry** (Node built-ins only — `node:fs`/`node:path`/
`node:url` — read-only, no network, no code-exec, no deps). **This table is the source of truth
if the two ever diverge** (locked decision D3): the minimum-viable v2 is this file, runnable by
hand with `grep`; the script mechanizes it. If you edit a regex in one, mirror it in the other.

## The 12 rules

Severities: **P0** default-shaped on sight (gates — caps the family at ≤3); **P1** a clear tell;
**P2** a nit or a pointer needing human confirm. `allow_from_tokens` / carve-out is what the rule
suppresses. `baseline` is the hit count over `frontend/src` on 2026-07-01 (spec README baseline:
88 total — P0=1, P1=17, P2=70).

| id | family | sev | pattern (regex core) | allow_from_tokens / carve-out | counter_move | baseline |
|---|---|---|---|---|---|---|
| `font-literal-off-token` | A | P1 | `font-family:` / `font-[…]` literal | `var(--font-{sans,serif,mono})` | swap-for-type | 0 |
| `arbitrary-type-size` | A | P2 | `text-[<n>px]` off the type scale | scale `{11,12.5,14,15,16,20,26,28,44}` | align-to-token | 64 |
| `raw-bw-literal` | B | P1 | `#000`/`#fff`, `{text,bg,border,…}-{black,white}` | none — use oklch tokens; `#0000` transparent excluded | align-to-token | 5 |
| `gradient-anywhere` | B | **P0** | `bg-gradient-to-*`, `bg-{linear,radial,conic}`, `bg-clip-text`, `*-gradient(` | `.scroll-shadow-x` functional gradient (CSS selector) | remove | 0 |
| `glass-blur` | B/E | **P0** | `backdrop-blur*`, `backdrop-filter:` | marketing surface excluded by default | remove | 1 |
| `colored-glow-shadow` | C/E | P1 | `shadow-[…]` / `drop-shadow-[…]` carrying a color | colorless `shadow-[0_1px_0]` ignored | align-to-token | 1 |
| `equal-thirds` | D | P2 | `grid-cols-3` (± responsive prefix) | pointer only — human confirms card identity | tighten-spacing | 2 |
| `perpetual-motion` | E | P1 | `animate-{bounce,ping,pulse,spin}` | `spin`/`pulse` near a loader or in `*skeleton*` suppressed; `bounce`/`ping` always fire | remove | 10 |
| `radius-off-token` | C | P2→P1 | `rounded[-side]-[<n>px]` off the radius ramp | ramp `{4,6,10,12,14,20,999}`; `rounded-[var(--radius-*)]` and CSS `border-radius` untouched | square | 5 |
| `round-fake-number` | F | P2 | `$X.00`, `99.99`, `X.00%`, placeholder names | `example.com` (RFC-2606) kept; test/spec/story fixtures excluded | align-to-token | 0 |
| `emoji-in-ui` | F/G | P1 | emoji codepoints in strings | arrows U+2190–21FF / typographic marks excluded | swap-for-type | 0 |
| `generic-cta` | G | P2 | `Get Started`/`Learn More`/`Submit`/… as a label | code `Submit` (`type="submit"`/`onSubmit`/`handleSubmit`) excluded | swap-for-type | 0 |

**The fingernails.** `radius-off-token` **escalates P2→P1 on data-viz elements** — when the
file basename or the matched line matches `spark|chart|bar|recharts|sankey|graph|viz`. This is
what upgrades `frontend/src/components/InsightsSparkline.tsx:65` (`rounded-t-[2px]`, a decorative
cap that misrepresents the data shape) to **P1**. It is the tell the 2026-06-09 audit missed
(spec README §"Why"); the cure is **square** the bars, never a gradient fill or hover-grow.

### Exact patterns (verbatim from `scripts/slop-grep.mjs` — keep in sync)

```
font-literal-off-token   /font-family\s*:\s*([^;{}]+)|font-\[([^\]]+)\]/g
                         keep: drop if value matches var(--font-(sans|serif|mono))
arbitrary-type-size      /text-\[([\d.]+)px\]/g
                         keep: flag if <n> ∉ type scale (parsed from --t-*-size)
raw-bw-literal           /#(?:fff|000|ffffff|000000)\b|\b(?:text|bg|border|ring|fill|stroke|from|
                          to|via|divide|outline|decoration|caret|accent|placeholder)-(?:black|white)\b/g
gradient-anywhere        /\bbg-gradient-to-[a-z]{1,2}\b|\bbg-(?:linear|radial|conic)(?:-to-[a-z]{1,2})?\b|
                          \bbg-clip-text\b|\bbg-\[(?:linear|radial|conic)-gradient|(?:linear|radial|conic)-gradient\s*\(/g
                         keep: in CSS, drop under a .scroll-shadow-x selector (functional overflow affordance)
glass-blur               /\bbackdrop-blur(?:-[a-z0-9]+)?\b|backdrop-filter\s*:/g
colored-glow-shadow      /\b(?:drop-)?shadow-\[([^\]]+)\]/g
                         keep: flag only if the arbitrary value carries a color
                               (value ~ /oklch|rgb|hsl|#|\bvar\(|color-mix|\/\d/) — a glow, not shadow-[0_1px_0]
equal-thirds             /\b(?:sm:|md:|lg:|xl:|2xl:)?grid-cols-3\b/g
perpetual-motion         /\banimate-(bounce|ping|pulse|spin)\b/g
                         keep: bounce|ping always fire; spin|pulse dropped if the file basename is *skeleton*
                               or a LOADING_CONTEXT signal is within ±2 lines
radius-off-token         /\brounded(?:-(?:t|b|l|r|tl|tr|bl|br|s|e|ss|se|es|ee))?-\[([\d.]+)px\]/g
                         keep: flag if <n> ∉ radius ramp
                         escalate: P2→P1 when basename or line ~ /spark|chart|\bbar\b|recharts|sankey|graph|\bviz\b/i
round-fake-number        /\$\d{1,3}(?:,\d{3})*\.00\b|\b99\.99\b|\b\d+\.00%|
                          \b(?:John Doe|Jane Doe|Acme|Lorem ipsum|SmartFlow|Foo Bar)\b/g
emoji-in-ui              /[\u{1F000}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]\u{FE0F}?/gu
generic-cta              /(?<![A-Za-z])(Get Started|Learn More|Read More|Click Here|Sign Up Now|
                          Discover More|Start Now|Try It Free|Submit)(?![A-Za-z(])/g
                         keep: drop if the line has type="submit" | on…Submit | handleSubmit | submitting

LOADING_CONTEXT          /Loader2?\b|Spinner|Skeleton|isLoading|isPending|isFetching|
                          \bloading\b|role=["']status["']|aria-busy/i
```

## Closed cure set (this enforces catalog §0, structurally)

Every rule's `counter_move` is drawn from a **closed set**:

> **`{ remove, square, align-to-token, swap-for-type, tighten-spacing }`**

and cures in **`{ gradient, glow, glass, animation, ornament }`** are **forbidden**. This makes
catalog §0 — *the counter-move to a tell is always more intentional restraint or more specific
character, never more decoration* — a structural property of the registry rather than a reminder.
It is the deliberate inverse of Impeccable's maximalist "motion-materials" guidance (glow/blur/
backdrop-filter as "premium materials"), which we read and **did not import** (research README §3).
A "fix" that lowers a finding count by adding a decorative cure has not de-slopped anything — it
fails §0 even though the number dropped (see the pairwise mode in `SKILL.md` Phase 4).

## Token provenance & carve-outs

**Allow-lists are parsed from `frontend/src/index.css` at runtime** — a token edit updates the
checks with zero code change (the "lint-literals-against-a-token-spec" discipline, wired to *our*
`@theme`). A hardcoded fallback (extracted 2026-07-01) is used only if `index.css` can't be found.

- **Radius ramp** — `--radius-*` declarations (`index.css:120–126`) → `{4,6,10,12,14,20,999}`px.
- **Type scale** — `--t-*-size` declarations (`index.css:160–194`) → `{11,12.5,14,15,16,20,26,28,44}`px.
- **Fonts** — `--font-serif` (`:155`), `--font-mono` (`:157`), `--font-sans` (`:276`).

The catalog §1 intentional-restraint carve-outs are enforced as **explicit suppressions**, not
prose — a rule that would fire on decided restraint is turned off by token provenance:

1. **Zero-chroma neutrals.** `raw-bw-literal` targets raw `#000`/`#fff` and `black`/`white`
   utilities, never the sanctioned `oklch(… 0 0)` neutral tokens — the calm neutral base is never
   flagged. `#0000` (transparent) is excluded by the hex forms.
2. **`--status-danger-calm` and the status ramp.** No rule flags `var(--status-*)` references; the
   deliberately muted danger color is the sanctioned form, so calm-not-alarmist status never trips.
3. **Functional-only motion.** `animate-spin`/`animate-pulse` within ±2 lines of a `LOADING_CONTEXT`
   signal, or inside a `*skeleton*` file, are suppressed — a spinner or skeleton is functional
   feedback. `animate-bounce`/`animate-ping` always fire (attention/decorative motion, a Family-E
   tell and a brand-voice issue).
4. **`.scroll-shadow-x` functional gradient.** A CSS selector carve-out: its gradient is an
   overflow affordance (a scroll-shadow), not decoration, so `gradient-anywhere` is suppressed
   under that selector.
5. **The `.page-title-rule` 2px hairline (`index.css:499–505`).** A named signature element defined
   in component CSS via `border-radius: 2px`, **not** an arbitrary per-component utility literal.
   `radius-off-token` scans only Tailwind `rounded-…-[<n>px]` utilities in code, never CSS
   `border-radius`, so this intentional brand hairline is never flagged — exactly the §1 distinction
   between decided restraint and an off-token utility. `rounded-[var(--radius-*)]` token references
   are likewise untouched (the regex requires a numeric `[<n>px]`).

The **marketing surface** (`frontend/src/marketing/`) is excluded by default — it is a landing
page, not the app (catalog §1: never flag the absence of hero decoration in the app). Pass
`--include-marketing` to audit it too. `node_modules`, `dist`, `build`, `coverage`, `__tests__`,
`e2e`, and `*.test`/`*.spec`/`*.stories` files are always excluded.

## Script contract

Invocation (from repo root — plain `node`, dep-free, runs on the CI Node 20 and local Node 22):

```
node .claude/skills/ui-slop-audit/scripts/slop-grep.mjs frontend/src
```

- **Default roots** (if none passed): `frontend/src` + `frontend/public/demo-data`, auto-detected
  relative to the script, so a bare `node slop-grep.mjs` also works.
- **Flags:** `--json` (structured output incl. resolved `allow_lists`), `--include-marketing`,
  `--index-css <path>` (override the parsed token source), `--report` (never gate — always exit 0),
  `--fail-on=<P0|P1|P2>` (gate when any finding at or above that severity exists; default `P0`).
- **Output:** the human report groups findings by rule — `file:line:col`, the matched token, and
  the source line — under a `rule-id · family · severity · cure` header, then a
  `P0/P1/P2` summary line. `--json` emits one object per finding
  (`{ rule, family, severity, counter_move, file, line, col, match, text }`) plus the resolved
  allow-lists and the gate config (`report`, `fail_on`, `gating`).
- **Exit codes:** default gates on **P0** — exit `2` if any P0 finding exists, else `0` (so P1/P2
  are non-blocking by default). `--report` always exits `0`. `--fail-on=<sev>` exits `2` when a
  finding at or above `<sev>` exists. An invalid `--fail-on` value exits `1`.

There is **no `pnpm slop:check`** and none is required — this is deliberately a plain-`node`
script (locked decision D2), so it runs unchanged in `make verify-frontend-slop` and CI without a
pnpm hop. During rollout the Make target uses `--report` (non-blocking); the gate flips to
`--fail-on=P0` only after the one live P0 (`StatementReview.tsx:962`, a functional sticky-bar
`backdrop-blur`) is triaged and the tree is P0-clean (locked decision D4).
