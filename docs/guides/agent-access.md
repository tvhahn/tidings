# Agent access

Tidings exposes a JSON HTTP API at `/api/v1/*` that a local agent (Claude Code, Cursor, n8n, curl, a custom script) can call directly. Authentication is RFC-6750 bearer tokens — `Authorization: Bearer fin_…` on every request. This guide walks through issuing a token, using it, and revoking it.

The bundled React dashboard does not need a token; it talks to `http://localhost:8000` over loopback and is unauthenticated by default. Agents that connect from anywhere else — a second device on your LAN, an agent running in another container, an automation pipeline — go through the bearer channel.

## Quickstart

```bash
make agent-token LABEL='laptop-claude'
```

> Working in this checkout with Claude Code? The `headless-backend-bootstrap` skill runs this whole guide's setup in one invocation — it detects Docker-vs-dev-checkout, mints the token via the right path (including the restart the running process needs), verifies the auth contract, and prints the consumer snippets.

Running the Docker stack rather than a dev checkout? `make agent-token` on
the host writes to the checkout's `data/`, which the containers don't read —
mint inside the container instead, so the hash lands in the named volume:

```bash
docker compose exec finance python -c \
  "from src.finance.agent_tokens import add_token; rec, raw = add_token(label='laptop-claude'); print(raw)"
docker compose restart finance
```

The restart matters: the API loads tokens at startup, so a token minted via `exec` answers 401 until the `finance` container restarts. (Tokens minted from the app itself take effect immediately; only this out-of-band path needs the restart.)

The command prints the token once. Save it now; only the sha256 hash is persisted to `data/config.json`, so the raw value is never recoverable.

```
  Token: fin_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  (illustrative — not a real token)
     id: 0123456789abcdef
  scope: read+write
  label: laptop-claude

Save this token now — it will NOT be shown again.
Pass it as `Authorization: Bearer <token>` on /api/v1/* requests.
```

Test the token against any read endpoint:

```bash
TOKEN=fin_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
curl -sH "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/categories | jq .
```

A 200 with the category list means the token works.

## Try it without installing

The demo journal is served read-only at a public endpoint, so an agent can explore the API before you clone anything. The base URL is `https://gettidings.com/demo/api/v1` — the same routes as a self-hosted install, backed by the fictional Mira Lin Chen fixtures.

```bash
curl -s https://gettidings.com/demo/api/v1/health | jq .status
curl -s 'https://gettidings.com/demo/api/v1/summary?month=2026-03' | jq .
```

The demo world covers `2025-05` through `2026-03`, with demo-today pinned to `2026-03-19`. All of it is fictional data. No token is needed — an `Authorization` header is accepted and ignored, so the demo never returns a 401. Writes are not part of the demo: any non-GET method returns a 405 pointing you at self-hosting for a writable journal. For how the endpoint is served and regenerated, see the [static hosted demo guide](static-hosted-demo.md#demo-api).

## Token lifecycle

Three Makefile targets cover the full lifecycle. Each wraps `scripts/agent/agent_token.py` directly.

```bash
make agent-token LABEL='cursor-on-laptop'             # issue, default scope read+write
make agent-token LABEL='read-only-agent' SCOPE=read   # issue with strict-read scope
make agent-token-show                                  # list ids, labels, scopes, last-used
make agent-token-revoke ID=0123456789abcdef            # delete by id
```

`agent-token-show` prints the table without raw values:

```
id                label              scope       created_at           last_used_at
----------------------------------------------------------------------------------
0123456789abcdef  laptop-claude      read+write  2026-04-30T19:14:02  —
9ab21f0c7e...     read-only-agent    read        2026-04-30T19:15:10  2026-04-30T19:16:33
```

Revocation is permanent — the row is removed from `data/config.json`. Any client still holding that token gets a 401 on its next request.

`last_used_at` is stamped on successful bearer auth, throttled to once per
token per 15 minutes (each stamp rewrites `data/config.json`), so it reads as
"active recently", not per-request telemetry. For per-write accountability see
[Every write is on the record](#every-write-is-on-the-record).

## Scopes

Two scopes ship today; future scopes are a one-line addition in `src/api/auth.py`.

| Scope | Allows | When to use |
|---|---|---|
| `read` | `GET /api/v1/*` | A third-party UI, a sketchy agent you want to box in, a read-only dashboard mirror. |
| `read+write` | All methods on `/api/v1/*` | The default. Day-to-day agent work — categorize transactions, set overrides, import a statement. |

The default at issuance is `read+write` because Tidings is single-user; gating writes behind a separate token rotation is friction without a security story. The `read` scope is the safer hand-out when the holder isn't fully trusted.

## Versioning

The path prefix is `/api/v1/`. Breaking changes are allowed inside `v1`, lockstep with the `INSTALL.md` clone tag — no external consumer is depending on a stable contract today, so the prefix is hygiene rather than a guarantee. If you build against this API, pin to the `INSTALL.md` clone tag and use the committed `openapi.json` as your change log; `make verify-openapi` is the drift gate. The day a consumer needs a stability promise, `/api/v2/` ships alongside; until then there is one moving target.

## Public endpoints (no token required)

These bypass auth so a fresh agent can discover the API before it has a token:

- `GET /api/v1/health` — liveness + last-activity probe
- `GET /openapi.json` — full OpenAPI schema
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc UI
- `GET /llms.txt` — a plain-text orientation file agents can read first

For everything else under `/api/v1/*`: a request that presents an `Authorization` header is always validated against the configured tokens (invalid token → 401, insufficient scope → 403). A request with no header falls through to the browser channels — session cookie, or TOFU. That means anonymous access stays open until a **dashboard password** is set, even if tokens exist; setting a password (Settings → Password) is what closes it. With no password and no tokens — the state right after `docker compose up` — the API is fully open on loopback, preserving the zero-config quickstart.

## Worked examples

### curl

```bash
TOKEN=fin_…
BASE=http://localhost:8000/api/v1

# Read this month's spending
curl -sH "Authorization: Bearer $TOKEN" "$BASE/summary?month=2026-04" | jq .

# Search transactions
curl -sH "Authorization: Bearer $TOKEN" \
  "$BASE/transactions/search?merchant=tim+hortons" | jq '.transactions[] | {date, amount, category}'

# Pin a category override (company name in the path, URL-encoded; category in the body)
curl -sH "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -X PUT "$BASE/overrides/WHOLE%20FOODS" \
  -d '{"category":"Groceries"}'

# Search transactions by an array of merchants (POST sibling of the GET)
curl -sH "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -X POST "$BASE/transactions/search-by-filter" \
  -d '{
    "from_month": "2026-01",
    "to_month": "2026-04",
    "merchant_in": ["whole foods", "trader joe", "costco"],
    "category_in": ["Groceries"],
    "min_amount": 10
  }' | jq '.summary'
```

The POST `transactions/search-by-filter` endpoint is the agent-friendly companion to `GET /transactions/search` — same filter semantics, but `merchant_in` / `category_in` / `institution_in` / `type_in` accept arrays in the request body instead of needing each value URL-encoded as a separate query param.

### Python (httpx)

```python
import httpx, os

client = httpx.Client(
    base_url="http://localhost:8000/api/v1",
    headers={"Authorization": f"Bearer {os.environ['FINANCE_API_TOKEN']}"},
)

summary = client.get("/summary", params={"month": "2026-04"}).raise_for_status().json()
print(summary["total_spent"])
```

### n8n

Use the **HTTP Request** node:

- URL: `http://localhost:8000/api/v1/summary?month={{ $now.format('yyyy-MM') }}`
- Authentication: **Header Auth** (or **Generic Credential Type → Header Auth**)
- Header name: `Authorization`
- Header value: `Bearer fin_…`

Store the token in n8n's credential vault, not in the workflow JSON.

### Custom HTTP-tool-using agents (Claude API tool use, ChatGPT actions, Cursor tools)

Any agent surface that lets you define an HTTP tool can call this API. Configure the tool with:

- **Base URL:** `http://localhost:8000` (or your reverse-proxy host)
- **Authentication:** static header — `Authorization: Bearer fin_…`
- **Spec:** point the agent at `http://localhost:8000/openapi.json` if it consumes OpenAPI; otherwise hand-write the tool schema for the endpoints you need.

There is no native MCP server entry-point; use the HTTP path above — most agents handle bearer-auth REST cleanly. (Direction lives in [`ROADMAP.md`](../../ROADMAP.md).)

## Errors

The API returns the unified `{error, code, details}` shape on all 4xx/5xx responses.

| Status | code | When |
|---|---|---|
| 401 | `UNAUTHORIZED` | Missing `Authorization` header, wrong scheme, or token not in `data/config.json`. |
| 403 | `FORBIDDEN` | Token is valid but its scope does not permit this (method, path). For example, a `read` token attempting `PATCH /api/v1/transactions/bulk`. |

Body for both:

```json
{
  "error": "invalid token",
  "code": "UNAUTHORIZED",
  "details": null
}
```

## Every write is on the record

Every mutating call to `/api/v1/*` is journaled in an append-only activity
ledger: who made it (token id and label, browser session, or the pre-password
device), which operation, when, and — for the invertible operations
(transaction category/state/comment/field edits, bulk recategorization,
overrides, merchant aliases, budget config, category groups) — a before/after
image with one-call undo. Three endpoints and one page expose it:

- `GET /api/v1/whoami` — the caller's resolved identity: kind, token id, label,
  scope, `last_used_at`. The quickest "is my token wired up?" check.
- `GET /api/v1/activity` — the journal, newest first. Filters: `limit`
  (default 100, max 500), `since` (inclusive ISO timestamp), `operation`, and
  `principal` — a token id, or the literal `me` for "my own writes". An agent
  can read back its own mutations to self-verify they landed:

  ```bash
  curl -s -H "Authorization: Bearer $TIDINGS_TOKEN" \
    "http://localhost:8000/api/v1/activity?principal=me&limit=10"
  ```

- `POST /api/v1/activity/{id}/revert` — undo an invertible entry. Refuses with
  `409 stale_revert` if the resource changed after the entry was written (pass
  `force=true` to override), 409 if already reverted or not reversible. The
  revert is itself journaled and the original entry is marked.
- **Settings → Activity** — the same journal as a calm feed, grouped by
  principal and burst, with per-entry revert.

Entries are retained for 90 days on both backends (SQLite prune-on-write,
DynamoDB TTL). `last_used_at` on tokens is stamped at most once per 15 minutes
per token — treat it as coarse presence, not an audit timestamp; the ledger is
the audit trail.

## Security caveats

Read this section before exposing the API on anything other than `localhost`.

- **Tokens grant full data access at their scope.** A `read+write` token can delete every transaction. Treat them like database passwords. Rotate when an agent or device is decommissioned. Run `make agent-token-revoke ID=…` whenever a token leaks. The activity ledger (above) means a misbehaving token is at least *visible* and its instrumented edits are revertible — but permanent deletes and import commits are not, so the warning stands.
- **Never commit a token.** They go in `.env`, in the agent's credential store, or in your password manager. The repo's `.gitignore` already excludes `data/config.json`, but the raw value never lives there anyway.
- **Loopback is the assumed boundary.** Tidings has no rate limiting, no IP allowlisting, no origin allowlisting beyond CORS. Anything stronger is the responsibility of the network you put it on.
- **TLS is the responsibility of the reverse proxy, not the app.** The FastAPI server speaks plaintext HTTP. Do not bind it to a public interface without a TLS terminator (Caddy, Traefik, nginx, Cloudflare Tunnel) in front. Bearer tokens travel in the `Authorization` header and are useless on the wire without TLS.
- **Hash storage protects the disk, not the wire.** Tokens are sha256-hashed at rest, but the raw value travels with every request. If TLS is misconfigured, anyone on the path sees the token.

## Exposing the API on a LAN

The defaults are tight on purpose. To expose the API to other devices (your phone over Tailnet, a household member's laptop, a separate container in the same compose project), three pieces have to line up.

1. **CORS.** The default allowlist is `http://localhost:5173`. Set `CORS_ALLOWED_ORIGINS` to the origin(s) that will call the API. A wildcard works for read-only uses but should be considered carefully.

   ```bash
   CORS_ALLOWED_ORIGINS=https://tidings.example.com,http://192.168.1.74:5173
   # or, for development only
   CORS_ALLOWED_ORIGINS=*
   ```

2. **Bind address.** Inside the devcontainer the FastAPI server binds to `0.0.0.0:8000` already; confirm the docker-compose port mapping forwards `8000` to the host. If you ran `uv run uvicorn` directly with `--host 127.0.0.1`, switch to `--host 0.0.0.0`.

3. **TLS.** Run a reverse proxy that terminates HTTPS. Caddy is the lowest-friction option:

   ```text
   tidings.example.com {
       reverse_proxy localhost:8000
   }
   ```

   Cloudflare Tunnel is a valid alternative if you want a stable public hostname without opening a port.

Once those three are in place, every request from a non-loopback origin must carry a valid token. `make agent-token` is the right answer; do not poke holes in CORS to skip auth.

## How auth interacts with the bundled dashboard

The dashboard has its own cookie-session channel, separate from bearer tokens. With no password set (`app_password_hash` absent from `data/config.json`), the app runs in TOFU mode: the dashboard works unauthenticated and prompts you to set a password under Settings → Password. Once a password is set, the dashboard authenticates via `POST /api/v1/auth/login` and rides a signed session cookie; bearer tokens remain the channel for agents and scripts. If you expose the API beyond loopback, set a password first — TOFU mode plus a reachable port is an open dashboard.

## Verification

Three quick checks confirm the path end-to-end after issuing a token. Check 1 assumes a dashboard password has been set — in TOFU mode (no password yet) anonymous requests are allowed by design and it returns 200:

```bash
TOKEN=fin_…

# 1. No header → 401 (requires a dashboard password to be set; 200 in TOFU mode)
curl -si http://localhost:8000/api/v1/categories | head -1
# HTTP/1.1 401 Unauthorized

# 2. Valid token → 200
curl -si -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/categories | head -1
# HTTP/1.1 200 OK

# 3. Read token on a write → 403
curl -si -H "Authorization: Bearer $READ_ONLY_TOKEN" \
  -X DELETE http://localhost:8000/api/v1/transactions/foo/bar | head -1
# HTTP/1.1 403 Forbidden
```

If all three behave as shown, the auth layer is wired correctly.
