# Troubleshooting

The short version: the sync dot beside the month picker tells you *whether*
something is wrong, `docker compose logs` tells you *what*. This page collects the
failures self-hosters actually hit, most common first.

## First checks

```bash
docker compose ps                          # both services up?
curl -s http://localhost:8000/api/v1/health | jq .
docker compose logs --tail=50 finance      # the API + dashboard container
docker compose logs --tail=50 imap-poller  # the email poller sidecar
```

The health endpoint is unauthenticated and returns the same state as the
sync dot:

| Status | Meaning |
|---|---|
| `ok` | Poller checked in within 5 minutes (or IMAP isn't configured), nothing quarantined. |
| `degraded` | Last poll 5–30 minutes ago, an email failed to parse in the last 7 days — the early signal that a bank changed its template — **or** AI categorization is failing (provider, quota, or auth errors). |
| `stale` | No poll in over 30 minutes, or no new transaction in 14 days. |

In the dashboard, the dot turns red and pulses only on `stale`; a
`degraded` poller shows up in the dot's hover text rather than as a
separate color.

`degraded` and `stale` describe the *email pipeline*, not the API — the
dashboard keeps working either way.

## Transactions stopped appearing

The most common failure in normal operation, and it's usually not your
setup: a bank changed its email template.

1. The dot goes amber; unparsed alerts collect under **Needs review** rather
   than being dropped.
2. `docker compose logs imap-poller` shows `Failed to parse email`.
3. Open a [parser-broken issue](https://github.com/tvhahn/tidings/issues/new?template=parser_broken.md)
   with a redacted email body — or fix it yourself with the
   [add-a-parser guide](add-a-parser.md), which is exactly the tutorial for
   this.

Meanwhile, entries recovered by AI extraction (if enabled) and manual
entries from Needs review keep the journal complete.

## The IMAP poller can't connect

Gmail sign-in failures, `[AUTHENTICATIONFAILED]`, repeated reconnects:

- Gmail needs an **App Password**, not your account password, and 2-Step
  Verification has to be on first.
- The poller backs off automatically (5s doubling to 5 minutes) and recovers
  on its own once credentials are right — no restart needed after fixing
  `.env`, but `docker compose restart imap-poller` applies it immediately.
- The [email setup guide](self-hosted-email-setup.md#troubleshooting) has
  the per-symptom detail, including IMAP being disabled on the account.

## The dashboard won't load

- **Port 8000 already in use** — uncomment the `ports: !override` snippet in
  `docker-compose.override.yml` (copy the file from its `.example` if you
  don't have one) and pick a free host port, e.g. `"8001:8000"`. Then open
  `http://localhost:8001`. Prefer the override to editing
  `docker-compose.yml` directly — the override is gitignored, so upgrades
  via `git pull` never conflict with your port choice.
- **Container restarting or exited** — `docker compose ps`, then
  `docker compose logs finance` and read the last screen; the failing line
  is almost always in it.
- **`exec format error` on Raspberry Pi / Apple Silicon** — images are
  multi-arch (amd64 + arm64), so this is usually a stale cache:
  `docker compose pull`, or build locally.

## Permission errors on `data/`

The named volume is owned by the container user. This appears after
switching between a bind mount and the named volume. The reset is
`docker compose down -v` — **this deletes the volume and your data**, so
take a [backup](backup-and-restore.md) first if there's anything real in it.

## Forgotten dashboard password

Stop the app, remove the `app_password_hash` key from `data/config.json`,
start it again — the dashboard returns to trust-on-first-use and prompts for
a new password. Under the Docker stack the file lives in the volume:

```bash
docker compose exec finance python -c \
  "from src.finance.app_config import update_config; update_config({'app_password_hash': None})"
docker compose restart finance
```

## Notifications aren't arriving

- With no provider configured, notifications go to the logs only — look for
  `NOTIFY [Transaction]:` lines in `docker compose logs finance`. That's the
  fallback, not a bug.
- More than one provider's variables set? Auto-detection has a precedence
  order; pin it with `NOTIFICATION_PROVIDER`. The
  [notifications guide](notifications-setup.md#troubleshooting) walks each
  provider's failure modes.

## Demo mode won't go away

Demo mode is a config key, not an env var: set `demo_mode: false` in
`data/config.json` (or from Settings), then restart. Your real data lives in
`data/finance.db`; the seeded demo stays in `data/demo.db` and never mixes.

## Still stuck

- Health state, last poll, and version in one line:
  `curl -s http://localhost:8000/api/v1/health | jq .`
- "How do I…" questions go to
  [GitHub Discussions](https://github.com/tvhahn/tidings/discussions);
  reproducible bugs go to
  [Issues](https://github.com/tvhahn/tidings/issues) — include the health
  JSON and the last ~20 log lines, redacted.
