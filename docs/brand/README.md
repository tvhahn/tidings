# Tidings Brand Kit

The canonical home for everything Tidings sounds, looks, and stands for. Every fact in here has exactly one URL — the spec folders that originally drafted this material now point here as the source of truth.

If you are an AI agent, start with [`voice.md`](voice.md) before writing any user-facing string. If you are a contributor, start here.

## What lives where

| Page | When to read it |
|---|---|
| [`positioning.md`](positioning.md) | Why Tidings exists, who it is for, who it is not for, the line in the sand. Also: launch copy (Show HN, subreddit pitches), name rationale. |
| [`voice.md`](voice.md) | How Tidings talks. Voice constants (invariant), tone flexes (contextual), approved/banned words, product-name rules, PR review checklist. |
| [`visual.md`](visual.md) | How Tidings looks. Color, typography, spacing, motion, component recipes (cards, ledger rows, chips, severity, month selector). |
| [`assets/README.md`](assets/README.md) | Logo / wordmark / mark files and the rules for using them. Three-location model: canonical here, build mirror in `frontend/public/`, React renderer in `frontend/src/components/Wordmark.tsx`. |

For a one-page summary that loads in agent context immediately, see [`/BRAND.md`](../../BRAND.md) at the repo root.

## How this folder relates to the rest of the repo

- **Design tokens** (color, type, spacing values) live in `frontend/src/index.css` and `frontend/src/styles/themes.css`. Code is the implementation source. [`visual.md`](visual.md) describes intent and links to the CSS — it does not redeclare values.
- **Marketing copy** lives inline in `frontend/src/marketing/sections/*.tsx`. Voice rules in [`voice.md`](voice.md) apply to every string in those files.
- **Spec folders** under `docs/specs/` (local-only, absent in the public repo) are dated decision records. Several originally hosted brand content (`2026-04-24-design-system-refactor/`, `2026-04-23-ui-refinement/`, `00_open-source-migration/2026-03-21-dhh-philosophy/`, `00_open-source-migration/2026-04-19-branding-naming-panel/`); their content has been promoted into this kit and they now carry DO-NOT-EDIT banners pointing back here.

## Contributor governance

Two kinds of changes touch brand surfaces. They have different bars:

- **Voice changes** — adding or removing voice constants, tone flexes, banned words; changing the tagline; renaming the product. These shape every future contribution and require maintainer approval. Open an issue first.
- **Copy edits** — changing the wording of a specific marketing string, FAQ item, or empty state, while staying inside the existing voice rules. Run the [`voice.md`](voice.md) review checklist on the diff before it lands — in review for contributor PRs, via the `brand-voice` skill for direct commits.

Asset changes (logo, wordmark, mark) are voice-equivalent: maintainer approval, then update [`assets/`](assets/) plus the three sync targets noted in [`assets/README.md`](assets/README.md).

## When in doubt

The voice is **calm financial clarity**: a private journal, not a fintech dashboard. If a phrase sounds like it could appear on a SaaS landing page that promises to "supercharge your savings", it is wrong for Tidings. If it sounds like a thoughtful monthly statement from your bank if your bank cared about typography, it is closer.
