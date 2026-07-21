# CLAUDE.md

## Quick Start
- **Running Python:** Always go through `uv` — `uv run python …`, `uv run pytest …`, `uv run <tool>`. Never invoke bare `python`/`python3`/`pip`; system Python lacks the project's dependencies.
- **Environment:** DevContainer auto-runs `uv sync`. Local: `uv sync && source .venv/bin/activate`
- **Dependencies:** Edit `pyproject.toml`, then `uv sync`
- **Test (backend):** `uv run pytest tests/ -m "not integration"` or `uv run pytest tests/unit/ -v`
- **Test (frontend):** `cd frontend && pnpm test` (Vitest — utilities plus hook/component tests)
- **Verify (all gates):** `make verify` — canon-doc links, backend pytest + ruff + pyright, frontend lint/typecheck/format/vitest + de-slop P0 gate, Playwright e2e, openapi drift. Runs the sub-targets as a parallel dependency graph; about a minute on a many-core box, a few minutes on a typical laptop. Use before committing non-trivial changes.
- **Lint:** `ruff check src/ tests/` (auto-fix: `--fix`)
- **Format:** `ruff format src/ tests/`
- **Build Lambda image:** `bash docker/email_parsing/2_build_image.sh`
- **Frontend dev:** `make dev-frontend` (port 5173) or `make dev` (frontend + API)

## Technical decisions

Effort estimates calibrated to human teams are wrong here — implementation time is nearly free for agents. Never reject the better, more complete design because it "would take days," and never pick a band-aid because the proper fix "is a big refactor." Optimize for quality, robustness, and long-term maintainability. Simplicity still matters, but it means no speculative generality — accept all the complexity the complete solution genuinely needs, and none that it doesn't.

## Authority

This file plus the nested agent guides (`frontend/CLAUDE.md`, `src/api/CLAUDE.md`, `src/finance/CLAUDE.md`, `tests/CLAUDE.md` — each with an `AGENTS.md` symlink alongside), `BRAND.md`, `README.md`, `CONTRIBUTING.md`, `INSTALL.md`, the skills under `.claude/skills/`, and everything under `docs/` (except `docs/specs/`) is **canon** — current source-of-truth about how the system works today. `openapi.json` and `frontend/src/types/api.generated.ts` are canon but generated — regenerate (`make openapi` / `pnpm codegen`), never hand-edit. `docs-site/` is the human-facing rendering of the docs; where it and `docs/` disagree, `docs/` wins. `docs/specs/` is **intent / history** (local-only; see File layout): each spec's status in `docs/specs/INDEX.md` (`Implemented` / `Mostly Implemented` / `Partially Implemented` / `Pending` / `Not Implemented` / `Analysis`) is the authoritative read of where that work actually stands. `ROADMAP.md` and `CHANGELOG.md` are exploratory or historical — read on demand, never as commitments. Landing-page copy lives in `frontend/src/marketing/sections/*.tsx` — there is no extracted mirror to keep in sync.

## Dev surfaces (frontend port map)

`make dev-frontend` (**:5173**, real dashboard + real backend; pairs with `make dev-api`) is the daily surface. The five other targets (marketing :5175, static demo :5176, production preview :4173, Astro docs :4321, Streamlit eval harness :8501), port-override flags, and the `BrowserRouter` basename rules live in [`docs/guides/dev-surfaces.md`](docs/guides/dev-surfaces.md). Ports are pinned so a second worktree's `pnpm dev` (:5174) never collides.

## Worktrees

Use Claude Code's built-in worktrees (`EnterWorktree` / `claude --worktree <name>`);
`.claude/settings.json` sets `worktree.baseRef: "head"` (branch from local HEAD).
Outside Claude Code, plain `git worktree add <path>` from local HEAD works the same.
A worktree is a clean checkout — hydrate it (`cd frontend && pnpm install
--frozen-lockfile`; `uv sync`), never copy `data/` or `.env` (real financial data /
credentials), and run dev servers on offset ports (see [`docs/guides/dev-surfaces.md`](docs/guides/dev-surfaces.md)).

## Architecture
Self-hosted by default: Docker Compose runs FastAPI + React with an IMAP-poller sidecar; parser → categorizer → SQLite on a shared volume. Advanced AWS variant swaps the ingestion/storage edges: S3 → Lambda → parser → DynamoDB + SNS. Same parser pipeline in both. Full picture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Voice & Brand

Before writing any user-facing copy — marketing strings, error messages, empty states, tooltips, toasts, button labels — read [`docs/brand/README.md`](docs/brand/README.md). The voice constants in [`docs/brand/voice.md`](docs/brand/voice.md) are non-negotiable (no exclamations, sentence case, no growth-copy verbs, no gamification, no alarmist framing) — self-check any copy against the 5-bullet checklist there before it lands. [`BRAND.md`](BRAND.md) at the repo root is the one-page summary; the kit at `docs/brand/` is the depth.

## File layout

The tree is discoverable with `ls` — only the non-obvious parts are recorded here:

- `src/api/routers/` — one module per `/api/v1/*` resource
- `docs/specs/` — local-only dated feature specs in `YYYY-MM-DD-<slug>/` folders (primary
  file `README.md`; some also carry `GOAL.md` / `IMPLEMENTATION_PLAN.md` /
  `AUDIT.md`). `INDEX.md` is the master index.
  **Local-only:** excluded via `.git/info/exclude` — never tracked or pushed.
  **Finding a spec when asked** (e.g. "refer to the ___ spec"): the dir is
  git-excluded, so it never shows in `@` autocomplete and an empty grep/glob
  sweep does **not** mean a spec is absent. Resolve the name via the
  local-only `docs/specs/INDEX.md` (read it by path) → open that folder's `README.md`. To
  search spec *contents*, name the path explicitly — `rg <pat> docs/specs/` or
  Grep with `path: docs/specs` (a repo-root sweep won't reach it).
- `docs/specs-public/` — **git-tracked** spec folders that ship with the
  public repo (launch assets, published references). Same
  `YYYY-MM-DD-<slug>/` convention; its `README.md` is the index.
- `data/` — gitignored **real** user financial data (config, SQLite DBs)

### Backend (finance + storage)
Dual-backend storage (DynamoDB/SQLite), per-bank parsers, the 7 service-pair
implementations, and finance domain rules (amounts, timezone, DynamoDB schema)
live in [`src/finance/CLAUDE.md`](src/finance/CLAUDE.md).

### Frontend Data Layer
Query-config, hook-wrapper, and API-client conventions are owned by [`frontend/CLAUDE.md`](frontend/CLAUDE.md) and enforced by ESLint — read it before editing `frontend/src/lib` or `frontend/src/hooks`.

## Critical Rules
- Docker image is built from repo root: `docker build -f docker/email_parsing/Dockerfile .`
- **Backend/parser/storage rules** — parser `parse_email()` contract, dual-backend edit discipline, amounts/timezone, DynamoDB schema — live in [`src/finance/CLAUDE.md`](src/finance/CLAUDE.md); read it before editing `src/finance/`
- **API contract & conventions** — router/model/dependency patterns, unified error shape, bearer scopes, openapi regen — live in [`src/api/CLAUDE.md`](src/api/CLAUDE.md); read it before editing `src/api/`
- **Before declaring a task complete:** run `make verify` (the full gate from Quick Start). Sub-targets `verify-backend` / `verify-frontend` / `verify-e2e` / `verify-openapi` for tighter loops.
- After any change that affects the UI (frontend or API), follow the **Visual verification** procedure in [`frontend/CLAUDE.md`](frontend/CLAUDE.md) — mandatory, not optional
- **Product screenshots are generated, never hand-taken.** `make screenshots` regenerates all of them from the static demo — docs-site pages, the marketing landing, and README `<picture>` pairs. If a UI change moves any captured surface, rerun it and commit the refreshed images. `scripts/checks/check_docs_coverage.mjs` (part of `make verify`) catches missing or renamed screenshot files, but visual staleness is only caught by regenerating.

## Committing

Use the `/commit` slash command to create commits. It assembles a conventional commit with emoji prefix (✨ feat, 🐛 fix, 📝 docs, ⚡ perf, 🧪 test, ♻️ refactor, 🔧 chore, 🎨 style, 🔒 security) and a staged-files manifest.

**Agents:** `/commit` is self-invocable via the `Skill` tool — call it with `skill: "commit"` and an optional argument for scope/message hints. The command handles the analyze → stage → compose → run sequence end-to-end; prefer it over manually running `git commit` when it applies.

**Branching:** Do not create a branch automatically when committing — commit directly to the current branch, `main` included. This repo runs multiple agents against a single shared working tree, so silently branching strands work and moves everyone's HEAD. Only create a branch when the user explicitly asks for one.

## Reference

Read on demand (not auto-loaded):
- `docs/ARCHITECTURE.md` — system design, data flow, parser system, schema, design decisions
- `docs/TESTS.md` — testing guide and pre-deployment checklist
- `docs/specs/INDEX.md` — feature specs (local-only, not in the public repo)
- `docs/guides/add-a-parser.md` — the parser tutorial: add support for a new bank's alert emails or PDF statements
- `docs/guides/agent-access.md` — bearer-token auth: issuing tokens, scopes, curl/n8n/Python snippets, LAN-exposure checklist
- `docs/guides/api-conventions.md` — the `/api/v1` contract rules: versioning, error shape, status codes, month validation, list/ack shapes, path identifiers
- `docs/guides/configuration.md` — canonical `data/config.json` key reference (types, defaults, behavior)
- `docs/guides/aws-deployment.md` — Docker build + full deployment workflow
- `docs/guides/dev-surfaces.md` — full frontend port map: five dev surfaces, port-override flags, BrowserRouter basename rules
- `docs/guides/devcontainer-startup.md` — DevContainer postCreate / postStart sequence and dependency hydration
- `docs/guides/dynamodb-cost-analysis.md` — on-demand vs provisioned DynamoDB cost model for the Transactions table
- `docs/guides/environment-management.md` — uv setup, dependencies, and environment management
- `docs/guides/notifications-setup.md` — configuring `NotificationService` providers (Ntfy, SNS, log-only)
- `docs/guides/releases.md` — versioning policy (SemVer, pre-1.0 rules), branching, and the cut-a-release ritual
- `docs/guides/self-hosted-email-setup.md` — IMAP polling daemon configuration for the self-hosted path
- `docs/guides/slash-commands.md` — category management, insights, statement parsing, test/doc review, and feature spec slash commands
- `docs/guides/static-hosted-demo.md` — building, previewing, and regenerating fixtures for the static Cloudflare-Pages demo
