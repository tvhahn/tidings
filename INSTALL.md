# Install Tidings (LLM agent edition)

> **You — the LLM reading this — are about to install Tidings on the user's
> machine.** Read this whole file before you start. Branch on what you find,
> ask the user one question when you must, and verify the result when you're
> done. Don't narrate every step; do the work.

This file is a prompt addressed to you, not a script the user runs. Tidings is a self-hosted personal finance dashboard — email-first, privacy-first, no Plaid. The repo is `github.com/tvhahn/tidings`; the product name is Tidings. The installation target is "a working `localhost:8000` running Tidings" with the install posture the user picks.

## Before you begin

Confirm the user has these on their machine. If anything is missing, point them at the official install page and pause — **do not try to install Docker, Git, or shell utilities yourself**.

| Tool | Check | If missing |
|---|---|---|
| `git` | `git --version` | <https://git-scm.com/downloads> |
| `docker` + `docker compose` | `docker compose version` (note the space) | <https://docs.docker.com/get-docker/> |
| `curl` | `curl --version` | Standard on macOS/Linux; on Windows, suggest WSL2 or PowerShell |
| `jq` (optional) | `jq --version` | Used to pretty-print JSON in the verify commands below. If missing, drop the `\| jq .` from those commands and read the raw JSON — do not install it yourself. |

OS family matters. Ask `uname -s` if you can't tell. Tidings runs on Linux, macOS, and Windows-via-WSL2. On bare Windows (no WSL2), tell the user to install WSL2 first — Docker Desktop on Windows uses it under the hood — and pause.

## Step 1 — Clone at a stable version

The repo is `https://github.com/tvhahn/tidings.git`.

```bash
git clone https://github.com/tvhahn/tidings.git tidings
cd tidings
```

**Machine already running Tidings?** (Check: `docker ps | grep tidings`.) Clone into a differently-named directory — the directory name becomes the Docker Compose project name, and a second project named `tidings` would collide with the running one's containers and `finance_data` volume. A second instance also shares the host's `ghcr.io/…/tidings:latest` image tag: `docker compose up` will silently reuse a cached image instead of pulling or building, and a local build retags `:latest` out from under the other instance. For a side-by-side install, set `GITHUB_REPOSITORY_OWNER=<something-unique>` in this clone's `.env` to give it its own image namespace.

If `git tag` returns at least one tag, check out the latest one. The repo's tag scheme is `v<MAJOR>.<MINOR>.<PATCH>`:

```bash
LATEST_TAG=$(git tag --sort=-version:refname | head -n 1)
git checkout "$LATEST_TAG"
```

If `git tag` returns nothing (early state), stay on `main` and warn the user that they're on the development branch — installs may break on any commit.

`main` is the explicit opt-in for users who specifically asked for bleeding edge. Otherwise prefer the tag.

## Step 2 — Decide the install posture

Ask the user **one question**, then commit to the answer:

> "Three postures available — pick one:
> 1. **Bundled UI on localhost** (default — open the dashboard in a browser).
> 2. **Headless API for agents** (no UI; expose `/api/v1/` for Claude / n8n / curl / a custom agent).
> 3. **Both** (UI on localhost; API also reachable for agents)."

Most users want #1. Pick #3 for users who explicitly want agent access; pick #2 for users who said "no UI, just the API" out loud.

**Posture #1 needs no configuration at all** — skip straight to Step 3. First run boots in demo mode with a seeded SQLite database; no `.env`, no edits. (One exception: if something on the machine already listens on port 8000, you'll create the compose override to re-home the port — see the first row of Step 3's table. Checking `ss -tln | grep :8000` before `up` saves a failed first attempt.)

Postures #2 and #3 set env knobs, and those knobs reach the container through a compose override (the root `docker-compose.yml` deliberately passes almost nothing from the host environment):

```bash
cp .env.example .env
cp docker-compose.override.yml.example docker-compose.override.yml
```

Then edit both: in `docker-compose.override.yml`, uncomment the `env_file: .env` block ("Feed credentials from .env"); in `.env`, set the posture knobs:

| Posture | `SERVE_FRONTEND` | `CORS_ALLOWED_ORIGINS` |
|---|---|---|
| 2. Headless API | `false` | leave default for loopback-only; set to the agent's origin only if the user explicitly wants LAN access |
| 3. Both | `true` (default) | set to the agent's origin if it's not loopback |

First run always defaults to local SQLite (demo mode), even when AWS credentials are present on the machine — DynamoDB is an explicit opt-in via `storage: "dynamodb"` in `data/config.json`. Only raise the DynamoDB option if the user says they already run the AWS Lambda stack.

## Step 3 — Bring it up

```bash
docker compose up -d
```

The services are `finance` (API + dashboard) and `imap-poller` (email sidecar, idle until credentials exist). Read the output. The most common failures and what to do:

| Symptom | Fix |
|---|---|
| `port is already allocated` on 8000 | `lsof -i :8000` (or `ss -tlnp '( sport = :8000 )'` on Linux without `lsof`). As a non-root user `ss` shows the listener but hides the owning PID — `docker ps` often identifies the culprit when it's a container publishing 8000, and `sudo` is the fallback. Report what you found to the user. Do not kill it without confirmation. Instead, re-home the port: uncomment the `ports: !override` snippet in `docker-compose.override.yml` (copy it from the `.example` if needed), pick a free host port, and substitute that port for `8000` in every URL and curl for the rest of this install — Steps 4–6 included. |
| `permission denied` under `data/` | Data lives in a named volume owned by the container user. This usually means a leftover bind mount from an older setup; `docker compose down -v` resets the volume — **it deletes any data in it**, so confirm with the user first (a fresh install has nothing to lose). |
| `manifest unknown` or `denied` pulling images | Not fatal — `docker compose up -d` falls back to building from source (the compose file carries `build:` blocks). Warn the user the first build takes a few minutes, then proceed. |
| `network … connection refused` pulling images | Tell the user; do not loop. They might be offline or behind a corporate proxy. |
| Build errors with frontend assets | `docker compose logs finance`. Paste the last 20 lines back to the user before guessing. |

If the up command exits non-zero and the cause is unclear, paste `docker compose logs --tail=50` back to the user before troubleshooting. **Don't fabricate a fix.**

## Step 4 — Verify

```bash
curl -fsS http://localhost:8000/api/v1/health | jq .
```

Expect HTTP 200 and a JSON body with `status: "ok"` (or `degraded` / `stale` — both are healthy enough to mean the install worked; they describe the IMAP poller's state, not the API). The body also carries `auth_required: bool`.

If the curl fails:
- container not up → `docker compose ps` and check for `restarting` or `exited`
- 404 → the SPA mount is in the way; check `SERVE_FRONTEND` in `.env` and that the override's `env_file` block is uncommented
- connection refused → still booting; wait 10 seconds and retry once

If after retry it's still not 200, paste the container logs back to the user. Don't claim success.

## Step 5 — Configure (only if posture = headless or both)

The bundled-UI posture (#1) is finished at Step 4 — open `http://localhost:8000` in a browser and the dashboard loads in TOFU mode. The user sets a password from Settings → Password; the `agent-access.md` guide is optional from there.

For postures #2 and #3, mint a bearer token so agents have something to authenticate with. Mint it **inside the container** — that writes the hash into the config the stack actually reads (the named volume, not the checkout's `data/`):

```bash
docker compose exec finance python -c \
  "from src.finance.agent_tokens import add_token; rec, raw = add_token(label='install-md-bootstrap'); print(raw)"
docker compose restart finance
```

The restart is required: the API loads tokens at startup, and the `exec` writes past the running process — without it the new token answers 401 until the next restart. Save the printed token. **It is shown once; only the sha256 hash is persisted.** Common patterns:

- Claude Code / Claude Desktop → put the token in the agent's environment as `FINANCE_API_TOKEN`.
- n8n → store in the credential vault as a "Header Auth" credential, header `Authorization: Bearer <token>`.
- curl / scripts → `export FINANCE_API_TOKEN=fin_…` in the user's shell.

(For a dev checkout running outside Docker, the equivalent is `make agent-token LABEL='install-md-bootstrap'` on the host — it needs `uv` and a synced environment.)

Read [`docs/guides/agent-access.md`](docs/guides/agent-access.md) for the full token + scopes + LAN-exposure walkthrough. If you are a Claude Code agent working inside this checkout, the `headless-backend-bootstrap` skill automates this step — it detects the running stack (including a re-homed port), mints the token, performs the required restart, and verifies the auth contract.

## Step 6 — Hand off

Print three things to the user, plain prose, no bullet points:

1. **The URL** — `http://localhost:8000` (or the port they remapped to).
2. **Auth status** — for posture #1, "TOFU mode — set a password in Settings → Password before exposing this anywhere"; for postures #2/#3, "Bearer auth active. Token saved as `FINANCE_API_TOKEN`."
3. **A working curl** the user can paste themselves, with their actual token interpolated, e.g. `curl -H "Authorization: Bearer $FINANCE_API_TOKEN" http://localhost:8000/api/v1/categories | jq .`

That's the install. Tell the user where to read more (`README.md` for product features, `docs/guides/` for the depth) and stop.

If the user plans to push changes back, mention the optional one-time
`git config core.hooksPath .githooks/`, which enables the tracked `pre-push`
guard (a release-audit of the tree; on the maintainer's own clone it also
enforces a remote allowlist). The hooks are advisory — CI is the authoritative
gate, and any hook is bypassable with `--no-verify`.

## Notes on what NOT to do

- **Don't try to "fix" parser errors during install.** The parsers run on real bank emails; you have none yet.
- **Don't generate fake data.** Demo mode (`demo_mode: true` in `data/config.json`) seeds a fixture DB; real data arrives via the IMAP forwarder once the user wires that up later.
- **Don't push the demo as the install target.** The user installed Tidings to track real spending; demo mode is for screenshots and trying features without touching real transactions.
- **Don't expose the API off-localhost without TLS.** If the user wants LAN access, point them at the `agent-access.md` "Exposing the API on a LAN" section. TLS is the reverse proxy's job, not the app's.
