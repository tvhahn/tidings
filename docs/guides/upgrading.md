# Upgrading

Tidings is **pre-1.0**: a minor version may change APIs or the database
schema. The upgrade itself is three commands; the care is in the two steps
around them.

## Check where you are

The health endpoint shows the running version:

```bash
curl -s http://localhost:8000/api/v1/health | jq .version
```

## Upgrade

1. **Read the [CHANGELOG](../../CHANGELOG.md) first.** Anything that changes
   a schema, a config key, or a compose default is called out per release —
   that's the contract the [release ritual](releases.md) enforces.

2. **Take a backup.** One zip from Settings → Backup, per the
   [backup guide](backup-and-restore.md). Pre-1.0 this is the step to skip
   least.

3. **Pull and restart:**

   ```bash
   git pull            # compose file and docs move with releases
   docker compose pull
   docker compose up -d
   ```

Database migrations run automatically on startup — the app creates missing
tables and applies pending migrations before serving requests. There is no
separate migrate command to run.

Then open the dashboard and hover the sync dot beside the month picker: a
recent sync time means the poller re-attached and the schema settled.
Anything off, start with the [troubleshooting guide](troubleshooting.md).

## Roll back

Images are published per version, so rolling back is pinning a tag:

1. `docker compose down` (without `-v` — keep your data).
2. Edit the two `image:` lines in `docker-compose.yml` from `:latest` to the
   previous version, e.g. `ghcr.io/tvhahn/tidings:v0.1.0` and
   `ghcr.io/tvhahn/tidings-imap-poller:v0.1.0` (the committed file spells
   the owner with the `GITHUB_REPOSITORY_OWNER` compose variable — only the
   tag needs to change).
3. `docker compose up -d`.

If the newer version already migrated the schema, the older code may not
read it — that's what the pre-upgrade backup is for: restore it per the
[backup guide](backup-and-restore.md) and you're back exactly where you
were.

## Following along between releases

`docker compose pull` follows `:latest`, which moves with tagged releases.
Running from `main` (building locally after `git pull`) is the explicit
bleeding-edge opt-in — any commit may break an install, and the changelog's
`[Unreleased]` section is the only warning you get.
