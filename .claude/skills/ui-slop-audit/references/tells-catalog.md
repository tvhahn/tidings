# AI-Tells Catalog — Tidings-calibrated

This is the rubric content for `ui-slop-audit`. It adapts two public sources — the
[`awesome-claude-design` audit-live-site rubric / Anti-Slop fingerprint table](https://github.com/rohitg00/awesome-claude-design)
and the ["100 AI tells" forbidden-patterns catalog](https://github.com/bnd-1/taste-skill) — and
**recalibrates them for Tidings**, whose brand is the opposite of the maximalist aesthetic those
catalogs assume. Read this file in full before scoring.

---

## 0. The two directions of slop

"AI slop" is not one failure mode. It is two opposite ones, and Tidings can only ever fail in one of them.

- **Over-slop (maximalist):** purple gradients, glassmorphism, holographic cards, perpetual
  micro-animation, magnetic buttons, GSAP scrolltelling, blinking "live" dots. This is what most
  public anti-slop skills are built to *prevent* — and, perversely, what they then *prescribe* as
  the cure. **Tidings almost never fails this way, and the fix is never to add any of it.**
- **Under-slop (default-shaped):** the shadcn/ui starter that was shipped without ever being given
  a point of view. Inter because it was the default. Lucide on every surface. Cards inside cards.
  Equal-thirds grids. `Get Started` CTAs. Round fake numbers. This is **Tidings' entire risk
  surface.** It reads as AI not because it is loud but because it is *un-decided*.

> **Hard rule for every recommendation this skill makes:** the counter-move to a tell is always
> *more intentional restraint or more specific character* — never more decoration. If a proposed
> fix would add animation, gradient, glass, or ornament, it is wrong for this brand. Re-derive it.
> When in doubt, read `docs/brand/voice.md` and `BRAND.md` — calm, sentence case, no exclamations,
> no growth verbs, no gamification, no alarmist framing are **non-negotiable** and enforced in PR review.

---

## 1. Intentional-restraint carve-outs (do NOT flag these)

Tidings deliberately overlaps with some "default" choices. These are decisions, not slop. Only flag
them if restraint has tipped into *genericness* — and say explicitly why, with evidence.

| Looks like a tell | Why it's actually intentional here | Flag only if… |
|---|---|---|
| Zero-chroma neutral base (`oklch(… 0 0)` greys) | The neutral foundation is a deliberate calm canvas; the warmth lives in `--brand` (oklch 0.58 0.15 40, a warm terracotta) and the ramp `--brand-50…200` | …the warm brand accent never actually appears on screen, so the UI reads as a colorless wireframe |
| Very little motion | Calm brand; motion is functional only (month-fade 150ms, collapsible 200/150ms) | …a state change that *needs* feedback has none (save, delete, load) |
| Restrained, low-saturation status colors; `--status-danger-calm` exists | Over-budget should not feel alarmist — this is a brand principle, not laziness | …danger is so muted it fails to read as danger at all |
| No hero gradients, no decorative imagery | This is a tool, not a landing page; the marketing surface is separate (`frontend/src/marketing/`) | n/a — never flag this in the app |

---

## 2. The tell families

Score each family 0–10 (§3). For every tell you assert, capture: **what** (the tell), **where**
(`file:line` + which screenshot/state), **why it reads as AI here**, **severity** (P0/P1/P2), and a
**counter-move** that respects §0. Don't assert a tell you can't see in the running UI or the code.

### A. Typography

- **Inter as the default-and-only face.** `--font-sans` is `"Inter"` (`frontend/src/index.css:276`).
  Inter is the single most common AI tell. It is not *wrong* — it's *undecided*. A `--font-serif`
  and `--font-mono` (JetBrains Mono) are already defined; check whether they're ever used to create
  intentional contrast, or whether everything is one undifferentiated Inter wall.
- **Flat hierarchy** — headings that differ from body only by a notch of size, not by deliberate
  weight/tracking/color. Watch for an amount and a label sharing the same weight so money doesn't
  dominate (a recurring note in `/aesthetic-critique`).
- **Oversized hero H1** that "screams" — rare here, but check marketing surfaces.
- **Arbitrary one-off sizes** (`text-[26px]`, `text-[13px]`) scattered instead of a scale. Grep for
  `text-\[` and judge whether a system exists or each component improvised.
- **Numbers in the proportional sans** instead of `font-mono`/tabular — money columns that shimmer
  because digits don't align is a data-UI tell.

### B. Color & surface

- **Purple/blue gradient** anywhere in the app — the canonical AI fingerprint. (Expected absent; if
  present, P0.)
- **Teal default-accent fingerprint** — the Claude-Design `#16d5e6`-adjacent action color on CTA +
  focus ring + chart fill at once. Tidings has a real `--brand`; verify the accent on screen is the
  *brand*, not a leftover default, and that it's applied with intent rather than sprayed everywhere.
- **Pure `#000` / `#fff`** instead of the near-black/near-white tokens (`oklch(0.145 0 0)` /
  `oklch(0.985 0 0)`). Grep for `#000`, `#fff`, `black`, `white` in component classes.
- **Gradient text fills** on headers.
- **Oversaturated status colors** that fight the calm brand — but remember the carve-out: muted is
  the goal, so only flag the *opposite*.

### C. shadcn / component defaults (Tidings' highest-risk family)

This is where an under-slop app actually gets caught. The stack is Radix + shadcn/ui + CVA + Lucide
+ Recharts + Sonner — a *great* starting point that becomes a tell when shipped un-customized.

- **Un-customized shadcn radii / shadows / focus rings** — the default `rounded-md`, the default
  ring, the default border. Did anyone give these a point of view, or is it the `npx shadcn add`
  output verbatim?
- **Lucide on every surface.** 67 files import `lucide-react`. A single committed icon family is
  *fine* (it's a decision); the tell is Lucide used as a reflex — a generic icon stuffed into every
  empty state, button, and nav item where type or nothing would be stronger. Look for the default
  "user egg," generic file/upload glyphs, decorative icons that carry no information.
- **Container soup** — `Card > Card > div` nesting, padding stacking 24/24/24, a pill wrapping a
  card wrapping content. Cap mental budget at ~2 levels of nesting.
- **4px accent bar on every card** regardless of meaning — decoration masquerading as semantics.
  Reserve a colored left-rule for *one* role (e.g. severity) or drop it.
- **Generic rounded buttons** with default variant styling — the shadcn `default` button that was
  never themed to the brand.
- **Three equal cards in a row** (`grid-cols-3` of identical summary cards) — the single most
  recognizable layout tell. Check `SummaryCards.tsx`.

### D. Layout & composition

- **Everything centered** — centered H1, centered empty states, centered everything. Centering is
  the default; asymmetry and deliberate left-alignment read as decided.
- **Symmetric equal-thirds grids** as the only structural idea.
- **Card-grid monotony** — every section is the same card in the same grid. Vary by importance.
- **Predictable empty/scaffold layout** — a centered icon + one line + a button, identical
  everywhere.

### E. Motion & state (both directions)

- **Under:** missing loading / empty / error states; a generic spinner where a skeleton matching the
  layout would read as intentional; a save or delete with no feedback. The app already has
  skeletons and month transitions — verify coverage, don't assume it.
- **Over:** a blinking green "live" status dot, perpetual pulse/float/shimmer, motion for its own
  sake. Any of these is a tell *and* a brand violation. Counter-move is removal, never tuning.

### F. Content & data realism (demo-data tells)

This app ships a static-fixture demo (`frontend/public/demo-data/`, served at `:5176`). Audit it too.

- **"John Doe" / "Acme" / "SmartFlow"** placeholder names; generic merchant names that don't read
  like real Canadian transactions.
- **Round fake numbers** — `$1,234.56`, `99.99%`, `$100.00` everywhere. Real money is messy
  (`$47.21`, `$8.63`). Suspiciously clean data is a tell.
- **Emoji in UI** — banned by brand voice; also a generic-AI tell. Grep components for emoji.
- **Lorem ipsum** or vague aspirational filler in any shipped copy.

### G. Microcopy & voice

Overlaps with the `brand-voice` skill and `docs/brand/voice.md` — defer to those as canon, and
cross-reference rather than re-deciding. AI-tell-specific items:

- **Generic CTAs** — `Get Started`, `Learn More`, `Submit`. Concrete verbs beat filler.
- **AI copywriting clichés** — "Elevate," "Seamless," "Unleash," "Next-Gen," "Effortless,"
  "Powerful." Grep marketing + component strings.
- **Voice violations that are also tells** — exclamation marks, Title Case On Buttons, growth verbs,
  gamified praise, alarmist over-budget framing. These fail PR review *and* read as AI.

---

## 3. Scoring rubric — two strata (criterion-resolved)

Each family's 0–10 splits into two strata that behave differently (the TASTE lesson): a
**deterministic** floor a stranger would agree on, and a **judgment** call that is pure feel. Score
them separately, then combine — the deterministic stratum *gates*, the judgment stratum *fills*.

### Deterministic stratum (checkable against tokens, high agreement)

The [`references/static-checks.md`](static-checks.md) registry rules for the family, run by
`scripts/slop-grep.mjs` — pass/fail, not a feeling. These are the tells a stranger would flag on
sight (a raw `#000`, a gradient, a `backdrop-blur`, an off-ramp radius), so they **gate** the score
rather than average into it: **any P0 deterministic failure caps the family at ≤3** ("Default-
shaped"), regardless of how good the rest feels. P1/P2 deterministic hits weigh on the judgment
score but do not hard-cap it. The rules, allow-lists (parsed from `index.css`), and the §1
carve-outs the detector suppresses all live in `references/static-checks.md`.

### Judgment stratum (pure feel, lower agreement)

The genuinely subjective calls the detector can't make — does money dominate the hierarchy, does the
warm `--brand` actually appear on screen, is restraint reading as *decided* vs. colorless-wireframe,
is empty/loading coverage intentional. Score 0–10 **within the band the deterministic cap allows**,
using these four bands:

- **0–3 — Default-shaped.** Reads as an un-customized starter. Multiple P0 tells; a stranger would
  guess "AI-generated" on sight.
- **4–6 — Decided but generic.** Choices were made but few are *distinctive*; several P1 tells. The
  most common honest score for a competent shadcn app.
- **7–8 — Intentional.** Clear point of view, restraint reads as deliberate, only P2 nits remain.
- **9–10 — Distinctive & coherent.** A specific character no starter would produce, executed
  consistently across light/dark/mobile, with zero brand-voice violations.

Report each family as `{ family, deterministic: [pass/fail…], judgment_score, capped_score, verdict }`,
where `capped_score = min(judgment_score, 3)` when a P0 deterministic failure is present, else it
equals `judgment_score`.

A high score for *restraint* is fully earned here — calm and decided beats loud and distinctive for
this brand. Do not penalize Tidings for failing to be flashy; penalize it only for being *undecided*.
