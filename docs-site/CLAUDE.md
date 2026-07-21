# docs-site/ — agent guide

Scoped addendum to the root [`CLAUDE.md`](../CLAUDE.md) for the Astro Starlight docs site.

- **Adding a page** — ported: edit the source under `/docs/` and register it in the
  `pages` array of `scripts/sync-content.mjs`. Hand-written: new `.mdx` under
  `src/content/docs/` with `title` + `description` frontmatter. Either way, also list it
  in `astro.config.mjs` `sidebar` **and** in `scripts/generate-llms-txt.mjs` — both lists
  are manual; `scripts/checks/check_docs_coverage.mjs` (in `make verify` and CI) fails if one is missed.
- **Never edit synced copies.** Ported pages in `src/content/docs/` and the token copies in
  `src/styles/tidings-tokens/` are generated (`sync-content.mjs` / `sync-tokens.mjs`, run by
  `predev`/`prebuild`; force with `pnpm sync`). Edit the sources: `/docs/` and
  `frontend/src/index.css`.
- **Theming:** edit `src/styles/starlight-overrides.css` — never hand-tune Starlight defaults.
- **MDX gotcha:** component `<style>` blocks are silently dropped in content-collection MDX —
  put the CSS in `starlight-overrides.css`.
- **Screenshots** under `src/assets/screenshots/` are generated — `make docs-screenshots`
  (static demo on :4179), driven by `scripts/media/docs_screenshots.manifest.ts`; a
  `<ThemedScreenshot>` id needs both `-light` and `-dark` WebP files. Never hand-capture.
- **Dev:** `make dev-docs` (:4321). Narrative + font/token pipeline detail: [`README.md`](README.md).
