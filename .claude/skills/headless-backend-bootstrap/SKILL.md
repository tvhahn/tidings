---
name: headless-backend-bootstrap
description: |
  Set up the Tidings backend for agent / BYO-UI consumption of /api/v1/:
  detect Docker stack vs dev checkout, set the headless knobs, mint a
  bearer token the running process honors, verify the auth contract,
  print consumer snippets. Invoke on mentions of headless,
  bring-your-own-UI, agent access, BYO frontend, or calling the API
  from outside this repo.
disable-model-invocation: false
argument-hint: "[--no-auth]"
allowed-tools: Bash(docker:*), Bash(uv:*), Bash(make:*), Bash(curl:*), Read, Edit, Write
---

# Headless backend bootstrap

One invocation takes an external consumer (an LLM agent, a separate
frontend, n8n, a curl script) from "repo checkout" to "authenticated
`/api/v1/` calls that work." The facts — token lifecycle, scopes, public
endpoints, LAN exposure — live in
[`docs/guides/agent-access.md`](../../../docs/guides/agent-access.md);
this skill owns only the procedure and the context branching. When a
question is answered there, link it instead of restating it.

## Phase 0 — which backend is serving?

Two mutually exclusive contexts. Detect, don't ask:

- **Docker stack** — `docker compose ps finance` (from the repo root)
  shows a running `finance` container. Find the real host port with
  `docker compose port finance 8000` — installs re-home it via
  `docker-compose.override.yml`, so never assume 8000.
- **Dev checkout** — no compose stack running; the API runs via
  `make dev-api` (devcontainer or host with `uv`).

If neither is up, ask the user which they want — `docker compose up -d`
(the self-host stack, see `INSTALL.md`) or `make dev-api` — and start it.

Every later command branches on this. The production container ships
only `src/` and `data/demo/` — no Makefile, no `scripts/` — so in the
Docker context use the `python -c` one-liners below; `make` targets and
`scripts/agent/agent-bootstrap.py` exist only in the checkout.

## Phase 1 — detect the config posture

- Dev checkout:

  ```bash
  uv run python scripts/agent/agent-bootstrap.py --detect
  ```

- Docker:

  ```bash
  docker compose exec finance python -c \
    "from src.finance.app_config import get_config_with_features; import json; print(json.dumps(get_config_with_features(), indent=2))"
  ```

Read `storage`, `demo_mode`, and the provider flags from the JSON. The
script/function is the source of truth — never duplicate its detection
in prompt logic.

## Phase 2 — confirm storage / demo posture

Three valid resolutions; **ask once** if the user hasn't said which, and
never infer intent from credentials alone:

| User intent | What to do |
|---|---|
| "Play with fake data" (default for a new setup) | Leave `demo_mode: true`; the API serves the seeded `data/demo.db`. |
| "My real data is in `data/finance.db`" | Set `demo_mode: false` in `data/config.json`. Suggest a backup first. |
| "Talk to my AWS deployment" | Requires AWS credentials; `storage: "dynamodb"`. If creds are absent, stop and point at `aws configure`. |

## Phase 3 — headless toggle (optional)

Agents coexist fine with the bundled dashboard — bearer auth works
either way (posture 3 in `INSTALL.md`). Only flip this when the user
genuinely wants no UI served:

- **Docker:** set `SERVE_FRONTEND=false` in `.env`
  (`cp .env.example .env` first if absent), make sure
  `docker-compose.override.yml` exists (copy from the `.example`) with
  its `env_file: .env` block uncommented, then `docker compose up -d`.
- **Dev checkout:** `SERVE_FRONTEND=false make dev-api` (or export the
  variable and `make dev-restart`).

`CORS_ALLOWED_ORIGINS` stays default for loopback consumers; set it only
for a browser app on another origin (see the guide's LAN section before
exposing anything).

## Phase 4 — mint a bearer token

Skipped if the user passed `--no-auth` — warn that the API stays open
(fine on loopback, never on `0.0.0.0`).

- **Docker** — mint inside the container so the hash lands in the named
  volume, then restart:

  ```bash
  docker compose exec finance python -c \
    "from src.finance.agent_tokens import add_token; rec, raw = add_token(label='headless-bootstrap'); print(raw)"
  docker compose restart finance
  ```

  The restart is mandatory: the API loads tokens at startup, so without
  it the new token answers 401.

- **Dev checkout:**

  ```bash
  uv run python scripts/agent/agent-bootstrap.py --token   # idempotent; --force reissues
  ```

  If the dev API is already running, `make dev-restart` — the same
  startup-cache rule applies.

The raw token prints once; only its sha256 hash is persisted. Save it
now (`FINANCE_API_TOKEN` is the conventional env var).

## Phase 5 — verify

Run against the detected port, not a hardcoded 8000:

```bash
curl -fsS http://localhost:<port>/api/v1/health            # public, no token
curl -si -H "Authorization: Bearer $FINANCE_API_TOKEN" \
  http://localhost:<port>/api/v1/categories | head -1       # expect 200
curl -si -H "Authorization: Bearer garbage" \
  http://localhost:<port>/api/v1/categories | head -1       # expect 401
```

Do **not** treat a header-less 200 as a failure: until a dashboard
password is set, TOFU mode allows anonymous loopback requests by design
— tokens gate only requests that present a header. The full contract,
including the read-scope 403 check, is in the guide's
[Verification section](../../../docs/guides/agent-access.md#verification).

## Phase 6 — snippets and report

- Dev checkout: `uv run python scripts/agent/agent-bootstrap.py --snippets`
- Docker: print the curl snippet with the real port interpolated; the
  guide's [Worked examples](../../../docs/guides/agent-access.md#worked-examples)
  cover httpx, n8n, and HTTP-tool-using agents.

Close with this report shape:

```
Headless backend ready.
  Context:    <docker|dev-checkout>
  API:        http://localhost:<port>
  Storage:    <sqlite|dynamodb>
  Demo mode:  <true|false>
  Frontend:   <served|headless>
  Auth:       <enabled|disabled>
  Token env:  FINANCE_API_TOKEN  (raw value shown once above)

Next: docs/guides/agent-access.md — scopes, revocation, LAN checklist.
```

## Constraints

- **Never edit `src/`.** The only writes are `.env`,
  `docker-compose.override.yml`, and `data/config.json` (via the token
  commands above).
- Don't restate guide facts; link `docs/guides/agent-access.md`.
- Never help expose the API beyond loopback without a dashboard
  password set and the guide's LAN checklist — TLS is the reverse
  proxy's job.
