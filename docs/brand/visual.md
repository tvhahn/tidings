# Visual

> Combines the **Visual Foundations** section of `docs/specs/_archive/2026-04-24-design-system-refactor/design_handoff_tidings/design_system/DESIGN_SYSTEM_GUIDE.md` with the component recipes in `docs/specs/_archive/2026-04-23-ui-refinement/STYLE_GUIDE.md`. Both originals are local-only historical records (absent in the public repo) and now point here.

The interface is a warm, off-white sheet on which financial facts are set like type on paper. Every choice biases toward **calm, spacious, restrained**. Most screens should feel almost empty at first glance; information reveals itself with attention.

Five aesthetic words — quote them when arguing about a visual decision: **clean, premium, restrained, data-calm, subtly friendly.**

This page is split into:

1. **Foundations** — color, typography, spacing, motion, etc. (intent + design rules).
2. **Tokens — where they live in code** — pointers, not redeclarations.
3. **Component recipes** — copy-paste TSX patterns for cards, ledger rows, chips, severity, month selector.
4. **Anti-patterns** — what to refuse.

---

## 1. Foundations

### Color

- **Warm Paper neutrals** — cream / ivory, never cool gray. Surface is off-white `oklch(0.985 0.008 80)`; cards are pure white floating on paper; borders are soft warm gray.
- **Brand rust** `oklch(0.58 0.15 40)` is the signature accent — the envelope+trend in the logo. It appears sparingly: page-title underline, "Today" pill, sidebar count badges, sparkline current-month bar, sync dot. (Not the active-nav row — that's a neutral `--accent` pill, no rust, no edge stripe.) **Never** on a primary button or large fill.
- **Primary buttons are warm ink**, not rust — warm-paper `--primary` is `oklch(0.27 0.028 52)` (deep espresso) with cream text; dark mode inverts to cream-on-dark. Rust-family primaries drift back in easily (the Insights "Generate briefing" and Search CTAs shipped rust for a while) — if a filled button reads as a warm color rather than near-black, it's wrong.
- **Muted text must still pass AA.** `--muted-foreground` styles meaningful 11–14px meta text (journal "27% of budget", visit counts, captions), so it needs ≥4.5:1 on both white cards and the paper surface. For warm-paper that floor is `oklch(0.55 0.022 58)` — the older `0.62` measured 3.67:1 on the journal. Decorative-only uses (chevrons, dividers) may go lighter via opacity modifiers.
- **Status hues are palette-stable** — green = under budget, red = over, amber = warning, blue = info. `*-muted` backgrounds derive from `--surface-card` via `color-mix` so a warning banner sits on a cream-tinted-amber card on light mode and a dark-tinted-amber card on dark mode with no per-theme code.
- **Severity is calm.** Over-budget days get a **2.5% alpha** pink tint on the card — a hint, not an alarm. The pace bar uses `--status-danger-calm` (desaturated) at ≥90% because a wall of bright-red bars stops reading as alarm.

### Typography

- **Serif display** — Source Serif 4. Page titles, hero, big amounts in marketing. Editorial feel.
- **Serif prose (`t-prose`)** — Source Serif 4 italic, 16px/1.4, weight 400, tabular numerals. The "entry sentence" role: a single written line of prose on the journal headline card. In prose the hedge word is "about" — the `~` estimate mark stays on data surfaces (tooltips, chart marks). Reserve for one sentence per surface; it is not a body style.
- **Sans body** — Inter, weights 400/500/600. Default for UI, amounts in tables, meta.
- **Mono** — JetBrains Mono. Rare; reserved for debug / dev console.
- **Tabular numerals everywhere.** `font-variant-numeric: tabular-nums` on `body`. Amounts right-align and line up vertically.
- **Weight discipline** — 400 body, 500 for labels / merchants, 600 for amounts and headings. No 700 / 800 in product UI.
- **Letter spacing** — subtle negative tracking on headings (`-0.015em` h1, `-0.01em` h2). Never positive tracking. Never uppercase in body.

### Spacing & layout

- **4px grid.** Common rhythm: 8 / 12 / 16 / 20 / 24 / 32.
- **Generous whitespace.** Page content caps at `max-w-6xl` (1152px). Left sidebar is 240px. Cards pad 20px on desktop, 16px on mobile.
- **One thing per row.** Transaction rows are ledger-style: icon (32px circular muted slot) · merchant (500) · category pill · meta chips · spacer · amount (right-aligned, semibold, tabular).

### Backgrounds

- **No gradients** anywhere in product UI. No full-bleed images. No patterns, textures, grain.
- Marketing may use a single subtle warm-paper-tinted hero backdrop, no gradient stops.
- **Tints, not fills.** When a card needs state, use ~2.5% alpha of the state color on top of the card surface.

### Borders & shadows

- Borders are soft — `oklch(0.89 0.015 70)` at ~50–60% opacity on cards. Never 1px-solid-gray.
- **Every visible outline on a page uses the same `border-border/50` token** — day cards, monthly summary, sidebar rail (`border-r`), sidebar footer panels — so no hue shift reads across surfaces.
- **No shadows on cards, buttons, or page surfaces.** Shadows are reserved for **floating elements only**: popovers, dialogs, sheets, toasts, menus. Override the default `<Card>` with `shadow-none` explicitly.

### Imagery

- **No stock photos.** No illustrations. No mascots. No dashboards-of-charts hero art.
- Product screenshots themselves are the marketing art — a clean journal card tells the story. Captures ship on the base `default` palette a new user actually lands on, light and dark, so the art matches the surface it sits on rather than advertising a palette nobody has selected yet.
- **Marketing surfaces only:** restrained still-life photography is permitted — at most two per page, warm-ivory palette matching the page surface, quiet domestic subjects, no people, no text, no screens. Photographs are commissioned/art-directed (never stock-watermark generic). Product UI remains photo-free.
- **Photographs never fade in dark mode.** A CSS-dimmed photograph reads as a rendering error, not a design choice. Every marketing photograph ships as a light/dark pair: the dark variant is the *same scene re-lit* (dusk, one warm low lamp, deep warm shadows), generated as a composition-preserving reference-image edit — see `.claude/skills/generate-image/` §1b (`--edit`), which keeps geometry identical so the theme switch doesn't jump. Theme-swap the asset (`<picture>`, paired `<img>`s, or a CSS `image-set`). Fading out in dark mode remains fine for *decorative generated SVG graphics* — vector ornament tolerates opacity; photographs don't.

### Motion

- **Fades and small translates.** Day summary fades / slides up 4px over 150ms. Month change: 150ms ease-out opacity + 4px translate. Popovers fade 120ms.
- **No bounces. No spring physics. No parallax.** Never.
- Scroll: native, no custom scrollbar styling.

### Interaction states

- **Hover** — bg shifts to `--surface-muted` or adds a translucent hover class (`bg-brand/10`). Never color-shift on text for general links.
- **Pressed** — no scale-down. Slight darkening of background.
- **Focus** — 2px `--ring` outline, offset 2px. Keyboard-visible always.
- **Disabled** — 50% opacity, `cursor-not-allowed`.
- **Hover-only actions** — transaction-row action cluster is `opacity: 0` at rest, `opacity: 1` on `group-hover`. Keeps rows quiet. Wrap in `shrink-0` so reserved width is constant and neighbours do not shift on reveal.

### Blur & transparency

Used sparingly. Mobile bottom nav uses `bg-card` with border; no blur. Dialog backdrop is solid color at low alpha, no `backdrop-filter`.

### Corner radii

- `4` input inner
- `6` buttons
- `12` cards (default — `--radius-tidings-md` via `<Card>`; page-level strips like the
  journal headline and empty state match it)
- `10` dialogs (`rounded-lg` → `--radius`)
- `999` (full) on pills, chips, nav-buttons, sync-dot

### Iconography

- **System** — [Lucide](https://lucide.dev) via `lucide-react`. Stroke-based line icons, 1.5–2px stroke, rounded joins.
- **Transaction icons** sit in a **circular muted slot** (`32×32`, `bg-muted`, `text-muted-foreground`). Glyph is 16×16 (`h-4 w-4`).
- **Row action cluster** (`CheckCircle2`, `EyeOff`, `MessageSquare`, `Pencil`, `Mail`, `Trash2`) — all `h-4 w-4` ghost buttons with 2px padding, hover: faint tinted background matching action semantic.
- **Nav icons** — 16×16, sit to the left of nav label, inherit text color.
- **Sparkles** is the marker for AI-generated content (day summaries, briefings). Always tinted with `--brand`.
- **Category → icon map** — `frontend/src/lib/categoryIcons.ts`. Fallback: `MoreHorizontal`. Add new entries lower-case keyed to the canonical category name.
- **No emoji. No unicode-character icons. No icon-font files embedded.**

---

## 2. Tokens — where they live in code

Tokens are not redeclared in this document. Code is the implementation source of truth:

| What | Where |
|---|---|
| Color scale, semantic surfaces, status hues | `frontend/src/index.css` |
| Palette themes (warm-paper, nord, midnight, solarized, gruvbox) + dark mode | `frontend/src/styles/themes.css` |
| Theme switcher (palette + light/dark toggle) | `frontend/src/stores/theme.ts` |
| Severity helpers (`paceSeverity`, `severityTextClass`, `severityPillClass`, `PACE_BG`) | `frontend/src/lib/severity.ts` |
| Category → icon map | `frontend/src/lib/categoryIcons.ts` |
| Tailwind theme bridge (`@theme` block exposing CSS variables as utilities) | `frontend/src/index.css` (top of file) |

**Do not use Tailwind's built-in palette** (`bg-gray-100`, `bg-zinc-100`, etc.) — those are fixed hex values and will not swap in dark mode or under palette overrides. Always reach for a semantic token. When a specific shade isn't available, prefer adding a new CSS custom property in `index.css` and exposing it via `@theme` over an opacity-derived hack like `bg-muted-foreground/15`.

Five palettes ship — every visual rule below must hold under all five plus dark mode.

---

## 3. Component recipes

### Card chrome

```tsx
// Standard surface (day card, page-level summary):
<Card className="border-border/50 shadow-none">…</Card>

// Over-budget container (soft pink wash):
<Card className="border-status-danger/25 bg-status-danger/[0.025] shadow-none">…</Card>

// Today / contextual highlight (brand tint):
<Card className="border-brand/40 bg-brand/[0.03] shadow-none">…</Card>
```

Always drop the default shadow on these surfaces. Reserve shadow for popovers, dialogs, and floating elements.

### Severity rule (under a header)

```tsx
// pct = current / expected daily budget * 100
// tone = paceTone(pct) — success <80, warning 80–100, danger >100
<div className="mt-2 h-1.5 w-full rounded-full bg-muted-foreground/15 overflow-hidden">
  <div
    className={cn("h-1.5 rounded-full transition-all", PACE_BG[tone])}
    style={{ width: `${Math.min(pct, 100)}%` }}
    aria-hidden
  />
</div>
```

This is the canonical severity signal on the day card. The matching monthly bar uses `<PaceBar size="sm" />` for visual kinship. Do not stack this with a left border stripe — pick one signal, and that signal is the rule.

### Ledger row

Single line on desktop (`lg:flex`), two lines below (`lg:hidden`). Desktop layout clusters merchant + category + meta on the left and uses a `flex-1` spacer to push the amount to the right. Merchant gets a fixed `w-56`, category a fixed `w-48`, each meta span a fixed `w-28` — fixed widths keep column x-positions aligned across rows without the amount drifting.

The breakpoint is `lg:` (1024px), not `md:` — the fixed-column desktop layout needs ~1024px to coexist with the merchant name; below that the two-line layout reads better.

```tsx
// Desktop (≥1024px)
<div className="hidden lg:flex items-center gap-3 min-w-0">
  <span className="shrink-0 flex h-8 w-8 items-center justify-center rounded-full bg-muted text-muted-foreground">
    <Icon className="h-4 w-4" aria-hidden />
  </span>
  <span className="font-medium text-sm truncate shrink-0 w-56">{label}</span>
  <div className="shrink-0 w-48">{categoryPicker}</div>
  <EnrichmentBadges context={context} />   {/* two w-28 text columns */}
  <div className="flex-1" />                {/* push amount right */}
  <div className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
    {hoverActions}
  </div>
  <span className="font-semibold tabular-nums text-sm shrink-0">{amount}</span>
</div>

// Mobile / small desktop (<1024px)
<div className="lg:hidden">
  <div className="flex items-center gap-2 min-w-0">
    <Icon /> <label flex-1 truncate /> {amount} {kebab}
  </div>
  <div className="mt-1.5 flex items-center flex-wrap gap-x-2 gap-y-1 pl-10">
    {metaChips}
  </div>
</div>
```

The `pl-10` on the two-line layout's line 2 aligns the chips under the merchant (32px icon + 8px gap = 40px), not under the icon.

### Chip vocabulary

Filled pills are reserved for the **category picker** and high-emphasis surfaces (e.g. Transactions page filters). Informational meta on ledger rows — budget %, frequency — is rendered as **plain text** in the row's fixed-width columns, with severity carried by text color via `severityTextClass`. Meta text and the pill use the **same `text-xs` size** so the row reads as one visual line.

```tsx
// Filled pill (category picker, filter chips): one size, no uppercase, no border.
const chipBase = "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium";
<span className={`${chipBase} bg-muted text-muted-foreground`}>Groceries</span>

// Row meta (budget % + frequency): plain text in fixed-width columns.
<div className="flex items-center text-xs tabular-nums">
  <span className={cn("w-28 text-left", severityTextClass[paceSeverity(pct)] || "text-muted-foreground")}>
    {Math.round(pct)}% of budget
  </span>
  <span className="w-28 text-left text-muted-foreground">
    {n === 1 ? "1st visit" : `${n}× this month`}
  </span>
</div>
```

`paceSeverity` / `severityTextClass` / `severityPillClass` all live in `frontend/src/lib/severity.ts`.

### Category pill (inline picker variant)

Soft muted fill, title-case, no border. Chevron is the only affordance hint.

```tsx
<span className={cn(
  "inline-flex items-center gap-0.5 text-xs font-medium rounded-full px-2 py-0.5 transition-colors cursor-pointer",
  needsAttention
    ? "text-status-warning bg-status-warning-muted hover:bg-status-warning/20"
    : "text-muted-foreground bg-muted hover:bg-muted-foreground/15 hover:text-foreground"
)}>
  {titleCase(value)}
  <ChevronDown className="h-2.5 w-2.5 text-muted-foreground/60" aria-hidden />
</span>
```

### Category icon slot

```tsx
const Icon = iconForCategory(category);
<span className="shrink-0 flex h-8 w-8 items-center justify-center rounded-full bg-muted text-muted-foreground">
  <Icon className="h-4 w-4" aria-hidden />
</span>
```

The 16px glyph inside an 8-unit circle leaves enough ring that the circle reads as a chip, not a tight halo. Circle fill matches the category pill (`bg-muted`) so the row reads as one unified tone.

### Month / segment selector

A single pill, not three separate buttons. Ghost chevrons flank it.

```tsx
<Button variant="ghost" size="icon"><ChevronLeft /></Button>
<button className="min-w-[140px] inline-flex items-center justify-center gap-2 text-sm font-medium rounded-full border border-border/60 px-3 py-1 hover:bg-accent hover:text-accent-foreground">
  {statusDot}
  <span>{label}</span>
  <Calendar className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
</button>
<Button variant="ghost" size="icon"><ChevronRight /></Button>
```

### Typography scale (de-facto)

- **Page title** — `text-[26px] font-semibold tracking-tight` (via `PageHeader`)
- **Big numbers** — `text-2xl font-semibold tabular-nums tracking-tight` (month total)
- **Section titles** — `text-base font-medium` (day card header)
- **Row labels** — `text-sm font-medium` (merchant name)
- **Amounts (row)** — `text-sm font-semibold tabular-nums`
- **Meta / chips** — `text-[11px] font-medium`
- **Captions** — `text-xs text-muted-foreground`

---

## 4. Anti-patterns

- `shadow` on day cards, page summaries, sidebar panels, or any surface that isn't elevated from the page. Override the default `<Card>` with `shadow-none`.
- Uppercase + wide tracking pills (`uppercase tracking-[0.08em] text-[10px]`) — replaced by soft muted pills at 11px.
- *Heavy* severity fills (e.g. `bg-status-danger-muted/40`) on containers — the approved wash is `/[0.025]`, a whisper. Anything heavier reads as alarming and breaks "data-calm".
- Left-border stripes (`border-l-4 border-status-danger`) — the thicker pace rule plus the soft card wash already signal severity.
- Pill backgrounds on row meta (budget %, frequency) — plain text in fixed columns is the pattern. Reserve pill fills for the category picker.
- Amount on the left of a row — it pins right, always.
- Hover-action cluster that shifts neighbours on reveal — use `opacity-0 group-hover:opacity-100` inside a `shrink-0` flex child.
- Explicit borders on chips — the soft fill does the work.
- Shrink-wrapped row meta that drifts with text length — when rows repeat, use fixed-width column slots.
- Tailwind built-in palette (`bg-gray-100`, `bg-zinc-200`, `bg-slate-50`) — fixed hex, won't swap with palette / dark mode. Always reach for a semantic token.
