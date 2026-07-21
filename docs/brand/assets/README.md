# Brand Assets

Canonical home for the Tidings logo, mark, and wordmark. Four files live here; everywhere else they appear is a derived copy or a code renderer that must stay in sync.

## Files

| File | Use |
|---|---|
| [`logo-mark.svg`](logo-mark.svg) | Envelope-trend mark, **brand-rust hard-coded** (`#C4532C`). Use when the mark is rendered against a known light surface and the rust color must be exact (favicon, OG image, external embeds). |
| [`logo-mark-ink.svg`](logo-mark-ink.svg) | Same paths, `stroke="currentColor"`. Use when the mark sits inside HTML / SVG that drives color from the surrounding context (theme-aware UIs, dark / light mode, palette overrides). This is what `frontend/src/components/Wordmark.tsx` mirrors inline. |
| [`logo-wordmark.svg`](logo-wordmark.svg) | Mark + serif "Tidings" wordmark (Source Serif 4, weight 600, optical size 54, **outlined to paths** so it renders identically without the font installed — GitHub falls back to Georgia for `<text>`). Theme-adaptive: an internal `prefers-color-scheme` media query flips the text from light ink to dark-mode ink. Use for full-lockup placements: README header, marketing footer, partner / press kits. |
| [`logo-wordmark-dark.svg`](logo-wordmark-dark.svg) | Static dark-surface variant: mark stays rust, wordmark text fixed at dark-mode ink (`#FAFAFA` ≈ `oklch(0.985 0 0)`, the dark `--foreground` token). For renderers and surfaces where media queries do not apply (slides, print, image pipelines). Same outlined paths as `logo-wordmark.svg`. |

## The three-location model

The mark exists in three places. Treat them as a fan-out from this folder:

| Location | Role | Sync rule |
|---|---|---|
| `docs/brand/assets/` (here) | **Source of truth.** | Edit here first. |
| `frontend/public/favicon.svg` | Build-time mirror of `logo-mark.svg`. Served as the browser favicon at `/favicon.svg`. | Manually copy on change. The mark changes ~never; a sync script would be over-engineered. |
| `frontend/src/components/Wordmark.tsx` | React renderer. Inlines the SVG path data so its stroke can inherit `currentColor` and be tinted per-palette via `text-brand`. | Path data must match `logo-mark-ink.svg` byte-for-byte (the three `d=` strings + the `<rect>` attributes). The component carries a one-line comment pointing here. |

Why inline the SVG in TSX instead of `import`-ing it? Because importing through Vite's URL loader serves the file via `<img>`, which loses `currentColor` inheritance. Importing through `vite-plugin-svgr` works but adds a build dependency for one component. Inline is the smaller cost.

## Usage rules

- **Clearspace** — minimum padding around the mark equals the height of the rectangle inside it (~`16/64` of the mark's rendered size). Do not crop closer.
- **Minimum size** — mark alone: 16px. Wordmark lockup: 80px wide. Below 80px the serif "T" terminals stop rendering legibly.
- **Color** — use brand rust `oklch(0.58 0.15 40)` (≈ `#C4532C`) on light surfaces. On dark surfaces the rust still reads but `text-foreground` (palette-aware ink) is preferred for the wordmark; the mark may stay rust.
- **What never happens** — no drop shadow, no stroke recolor outside the brand-rust / ink / currentColor options, no rotation, no gradient fills, no decorative outline.
- **Wordmark typography** — Source Serif 4, weight 600, tracking `-0.015em`. Never set the wordmark in a sans typeface. Never set it in italic. The italic on the marketing tagline ("delivered.") is a different surface and unrelated to the wordmark.

## When you change a mark

1. Edit the file here in `docs/brand/assets/`. The two wordmark files are **generated** — do not hand-edit their text paths. Regenerate both with `scripts/media/outline_wordmark.py` (header comment has the one-liner); it downloads nothing, so fetch the Source Serif 4 variable font from [google/fonts](https://github.com/google/fonts/tree/main/ofl/sourceserif4) first. Mark changes are hand-edits to the nested `<svg>`, mirrored into the script's `MARK` constant.
2. Copy `logo-mark.svg` to `frontend/public/favicon.svg`.
3. Update the inline SVG `d=` paths and `<rect>` attributes in `frontend/src/components/Wordmark.tsx` to match `logo-mark-ink.svg`.
4. Verify visually: dev server's marketing entry (`make dev-marketing`) plus the dashboard sidebar (`make dev-frontend`) — the mark should look identical at both sizes, in both light and dark mode, across every palette.
