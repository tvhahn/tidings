# Backup and restore

Everything Tidings knows lives in one place: the `data/` directory —
`config.json` plus the SQLite database, and the receipt files under
`data/raw/attachments/` if you use receipts. A backup is a copy of that data;
a restore is putting it back. This guide covers both, plus leaving cleanly.

Under the default Docker stack, `data/` is a **named volume**
(`docker volume ls` shows it as `<project>_finance_data`, e.g.
`tidings_finance_data`) — it is *not* the `data/` folder in your checkout.
Copying the repo directory backs up nothing.

## Back up

### The backup zip (recommended)

**Settings → Backup → Download backup** produces
`finance-backup-<date>.zip`: every transaction plus your configuration
(categories, overrides, merchant aliases, budgets, and the Needs review
queue). It is the portable format the
restore path understands, and it works the same on SQLite and DynamoDB.

The same thing over the API, for a cron job or an agent:

```bash
curl -sf -X POST http://localhost:8000/api/v1/data/export \
  -H "Authorization: Bearer $FINANCE_API_TOKEN" \
  -o "tidings-backup-$(date +%F).zip"
```

Bearer tokens are covered in the [agent access guide](agent-access.md).
Backup is disabled in demo mode — there is nothing of yours to back up yet.

**What the zip does not carry:** receipt and statement attachment *files*,
and instance settings (timezone, dashboard password, AI toggles — those
live in `data/config.json` and take a minute to re-set on a fresh install).
The transactions and their links are in the zip; the images and PDFs
themselves live only in the volume. If you use receipts, take a volume copy
(below) as well. If you already use AWS, you can instead mirror those files
to a bucket you own with [S3 backup](s3-backup.md) — the durability answer
for the attachment and statement files the zip leaves out.

### The volume copy (full fidelity)

A byte-level copy of the whole volume — databases, config, attachments,
saved briefings. Stop the stack first so SQLite isn't mid-write:

```bash
docker compose stop
docker run --rm \
  -v tidings_finance_data:/data \
  -v "$(pwd)/backup":/out \
  alpine cp -r /data /out
docker compose start
```

Substitute your volume name from `docker volume ls`. The result in
`./backup/data/` is the entire state of your install.

## Restore

### From the backup zip

**Settings → Backup → Restore from backup.** Upload the zip (or a plain
transactions CSV from the Search tab's export). Nothing is written until you
confirm: a dry-run preview first shows how many rows are new versus
duplicates, and you choose whether duplicates are skipped and whether the
zip's configuration is applied.

This is also the migration path — the zip restores into a fresh install on
another machine, or across the SQLite/DynamoDB boundary.

### From a volume copy

Onto a fresh install:

```bash
docker compose up -d          # first boot creates the volume
docker compose stop
docker run --rm \
  -v tidings_finance_data:/data \
  -v "$(pwd)/backup/data":/from \
  alpine sh -c "rm -rf /data/* && cp -r /from/. /data/"
docker compose start
```

Open the dashboard and check the sync dot beside the month picker; the
[troubleshooting guide](troubleshooting.md) covers anything that looks off.

## A reasonable habit

Download a backup zip before every upgrade (the
[upgrading guide](upgrading.md) starts there) and on some calendar rhythm
that matches how much re-entry you can tolerate losing. One zip in your
existing backup system — a synced folder, an external drive — is enough;
this is a single household's journal, not a database fleet.

## Leaving Tidings

Everything is yours and everything is local, so leaving is short:

1. Download a backup zip (transactions as portable JSON/CSV) if you want the
   history.
2. `docker compose down -v` — stops the stack and deletes the volume.
3. Delete the cloned repo directory.
4. Revoke the Gmail App Password ([myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords))
   and turn off the bank-alert forwarding rules you created during
   [email setup](self-hosted-email-setup.md).

No accounts to close, nothing left behind.
