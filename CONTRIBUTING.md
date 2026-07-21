# Contributing

Tidings is an email-first, self-hosted finance dashboard. It turns the
transaction-alert emails your bank already sends into a private spending
journal — no Plaid, no shared credentials, no manual entry. Five parsers ship
today (RBC, CIBC, MBNA, Simplii, PC Financial — all Canadian, because that's
what the maintainer banks with), and the architecture is built so anyone can add
a parser for their own bank, in any country or language.

The highest-leverage contribution is a parser for a bank we don't yet support.
That has its own guide: [`docs/guides/add-a-parser.md`](docs/guides/add-a-parser.md).

Please read the [Code of Conduct](./CODE_OF_CONDUCT.md) before opening an issue
or PR.

## Dev environment setup

**DevContainer (recommended).** Open the folder in VS Code with the Dev
Containers extension and choose "Reopen in Container." The first build takes a
few minutes; the create step runs `uv sync` and `pnpm install && pnpm build`, so
the environment is ready when it finishes. The contributor stack lives at
`.devcontainer/docker-compose.yml`; the root `docker-compose.yml` is the
self-hoster production stack and is not what the DevContainer uses.

**Manual (without VS Code).** You need Python 3.12+ with
[uv](https://docs.astral.sh/uv/) and Node 20. `make verify` runs the frontend
gates and Playwright too, not just the backend, so both toolchains matter:

```bash
# Backend
uv sync
source .venv/bin/activate

# Frontend toolchain (pnpm via corepack, deps, Playwright's chromium)
corepack enable
cd frontend && pnpm install && pnpm e2e:install && cd ..
```

`make env` does the backend half and wires the repo's git hooks
(`git config core.hooksPath .githooks/`). The tracked `.githooks/` directory
holds a `pre-push` guard that release-audits the tree for secrets before every
push (a maintainer-only remote allowlist also lives there, but it stays
dormant on public clones — pushing to your fork is never blocked). Hooks are
advisory — CI is the authoritative gate, and any hook is bypassable with
`git push --no-verify`.

Dependencies live in `pyproject.toml`; edit that file and re-run `uv sync` to
add or change anything. Run Python through `uv run` (never bare `python`/`pip`)
— only `uv run` sees the project's dependencies.

Commands you'll lean on:

| Command | What it does |
|---|---|
| `make verify` | Full regression gate: canon-doc links, backend pytest + ruff + pyright, frontend lint/typecheck/format/vitest + de-slop P0 gate, Playwright e2e, OpenAPI drift. ~3–5 min. |
| `make dev` | Starts the FastAPI backend and the Vite frontend (port 5173). |
| `make dev-frontend` | Frontend only. |
| `uv run pytest tests/unit/ -v` | Fast backend unit tests. |
| `ruff check src/ tests/ --fix` | Lint + auto-fix. |
| `ruff format src/ tests/` | Format. |

**Opt-in host resources.** By default the DevContainer mounts none of your host
AWS credentials, Docker socket, or Claude config — a fresh clone stays isolated.
To enable any of them, copy
[`.devcontainer/docker-compose.override.yml.example`](.devcontainer/docker-compose.override.yml.example)
to `.devcontainer/docker-compose.override.yml` (gitignored) and uncomment what
you need: `~/.aws` (read-only, required for Lambda/DynamoDB paths),
`/var/run/docker.sock` (host Docker daemon — host-escape risk, enable only when
building or running the prod stack), or `~/.claude` (your host Claude config).
Rebuild the container to apply.

**Other conveniences.** The image ships a `c1` helper that opens Claude Code in a
persistent tmux session (survives reconnects). OpenAI Codex and Google Gemini
CLIs are off by default — enable them in your gitignored
`.devcontainer/docker-compose.override.yml` (auto-copied from the `.example` on
first open) by uncommenting the "Extra AI CLIs" snippet, which sets the
`INSTALL_EXTRA_AI_CLIS: "true"` build arg. Rebuild the container to apply.
(Build args in `devcontainer.json` are ignored for compose-based
devcontainers — the compose file owns the build.)

## Contribution paths

In rough order of leverage:

- **Bank parsers** — the primary path. Most banks send transaction-alert emails,
  and parsing them is the product's core. Full walkthrough:
  [`docs/guides/add-a-parser.md`](docs/guides/add-a-parser.md). The same guide
  also covers PDF statement parsers, for banks that send no alert emails or for
  reconciling uploaded statements.
- **Everything else** — bug fixes, frontend work, documentation, test coverage.
  Open an issue first if the change is non-trivial, so we can align on direction.

## Running tests

- Full gate: `make verify` (~3–5 min) — run this before every PR.
- Backend only (faster loop): `uv run pytest tests/ -m "not integration"`
- Single file: `uv run pytest tests/unit/test_rbc_parser.py -v`
- Keyword filter: `uv run pytest tests/unit/ -v -k purchase`
- Frontend only: `cd frontend && pnpm test`

Sub-gates for tighter loops: `make verify-backend`, `make verify-frontend`,
`make verify-e2e`, `make verify-openapi`.

## PR conventions

- Fill out [`.github/PULL_REQUEST_TEMPLATE.md`](./.github/PULL_REQUEST_TEMPLATE.md)
  — GitHub pre-populates it when you open a PR.
- Use conventional commits with an emoji prefix (full set in `CLAUDE.md`):
  ✨ `feat`, 🐛 `fix`, 📝 `docs`, ⚡ `perf`, 🧪 `test`, ♻️ `refactor`,
  🔧 `chore`, 🎨 `style`, 🔒 `security`. The `/commit` slash command in Claude
  Code assembles the prefix, body, and file manifest for you.
- Keep PRs focused. One parser per PR is ideal.
- For any user-facing copy (error messages, empty states, tooltips, README
  prose), read [`docs/brand/README.md`](./docs/brand/README.md) and apply the
  voice rules in [`docs/brand/voice.md`](./docs/brand/voice.md). The `/review`
  slash command and the `brand-voice` skill both check copy against them.
- `make verify` must be green before you request review.

## Where to ask

Check the GitHub Discussions tab first. If Discussions aren't enabled yet, open
an issue instead and we'll triage it. For deeper system context (data flow,
storage backends, design decisions), read
[`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).
