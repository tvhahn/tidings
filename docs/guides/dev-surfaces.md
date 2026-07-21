# Dev surfaces (frontend port map)

One Vite build produces three of these surfaces (dashboard, marketing, demo); two
more dev targets stand up separate tools — an Astro docs site and a Streamlit eval
harness. Each `make` target pins a stable port so a second worktree's `pnpm dev` on
:5174 does not collide:

| Make target            | Port  | What it serves |
|------------------------|-------|----------------|
| `make dev-frontend`    | 5173  | **Real dashboard** with the real backend (`basename "/"`). Daily app. Pairs with `make dev-api`. |
| —                      | 5174  | _Reserved by convention for a second worktree's `pnpm dev`._ |
| `make dev-marketing`   | 5175  | Marketing landing only — for editing copy/CSS in `frontend/src/marketing/`. |
| `make dev-demo`        | 5176  | Static-fixture demo SPA (mode=demo). No backend; reads `frontend/public/demo-data/`. What marketing CTAs land on in production. |
| `make dev-preview`     | 4173  | Production preview — `pnpm demo:build` then `serve dist`. Marketing at `/`, demo SPA at `/demo/`. Exactly what ships. |
| `make dev-docs`        | 4321  | Astro Starlight docs site (not the Vite build). No backend; reads `docs/` + `openapi.json`, synced into `docs-site/`. |
| `make dev-eval-harness`| 8501  | Streamlit prompt-evaluation harness (`dev/eval_harness/`, not the Vite build). Forwarded in `.devcontainer/docker-compose.yml`; not shipped. |

Override any port with `make dev-demo DEMO_DEV_PORT=5180` etc. The `BrowserRouter`
basename in `frontend/src/main.tsx` is `/` in dev (any mode) and `/demo` only in
the production demo build, so the demo SPA mounts at `/` on `:5176/` but at
`/demo/` on `:4173/demo/`.

## Worktrees and ports

A second worktree should run its dev servers on offset ports so it never collides
with the main checkout — e.g. `make dev-marketing MARKETING_DEV_PORT=5185`. Never
reuse the main checkout's ports from the table above. See the **Worktrees** section
in the repo-root [`CLAUDE.md`](../../CLAUDE.md) for the full hydration checklist.

`make verify-e2e` and `make docs-screenshots` are not in the port table on
purpose: each run serves `dist/` on a fresh ephemeral port and gates readiness
on a per-run build stamp, so concurrent runs (a second worktree, an orphaned
`serve`) can never collide with the fixed dev ports or silently test the wrong
build. Only `make dev-preview` still pins `:4173`.
