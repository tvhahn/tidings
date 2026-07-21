# FAQ

Short answers, with links into the guides for depth.

## Does Tidings have my banking password?

No. Tidings never talks to your bank. It reads the alert emails your bank
already sends you, from a Gmail inbox you control, using an App Password
scoped to that inbox. There is no Plaid, no screen scraping, no bank
credential anywhere in the system.

## Is it OK to forward my own bank emails?

This is your own mail, about your own accounts, forwarded
by you to another inbox you own, processed on your own hardware. That is a
long way from the things bank terms of service actually prohibit — sharing
credentials, granting third parties account access, screen scraping. Email
forwarding of alerts the bank chose to send you is not credential sharing,
and no third party is involved.

Two caveats. First, alert emails contain personal financial
information, so the inbox that receives them is worth protecting like the
account itself — a dedicated Gmail account with 2-Step Verification, which
is what the [email setup guide](self-hosted-email-setup.md) builds. Second,
this is a description of how Tidings works, not legal advice; if your bank's
alert terms say something unusual, they win.

For Canadian users wondering about PIPEDA: it governs how *organizations*
handle your personal information. Running Tidings yourself, for yourself, on
your own machine is personal use of your own data — the situation the law
exists to protect, not restrict.

## What leaves my machine?

Without an AI key, nothing. Add an OpenAI key and two switches come on,
both yours to turn back off under
[Settings → Intelligence](https://docs.gettidings.com/using/settings/):
categorization, which sends the amount and merchant name of each parsed
transaction, and email rescue, which sends the subject and body of an email
no parser could read. Every other AI feature — the monthly briefing, receipt
reading, statement parsing — is a separate opt-in that a key never turns on.

## Which banks work?

Five ship today:

| Institution | Email alerts | PDF statements | Notes |
|---|---|---|---|
| RBC | Yes | Yes (chequing) | Purchase, withdrawal, e-transfer |
| CIBC | Yes | No | Purchase, preauth payment |
| MBNA | Yes | No | Credit card purchase |
| Simplii | Yes | Yes (chequing) | E-transfer (Interac sender) |
| PC Financial | Yes | No | Money Account purchase alerts |

Alerts from any other bank land in **Needs review** instead of being
dropped: AI extraction (if enabled) can read them, you can enter them
manually, and the [add-a-parser guide](add-a-parser.md) turns them into a
proper parser — the most useful contribution to the project.

## How is Tidings different from Firefly III or Actual Budget?

They solve adjacent problems in different ways. Firefly III is a full
double-entry finance manager; Actual Budget is a local-first envelope
budgeting app. Both are built around bank sync, file imports, or entering
transactions yourself. Tidings reads the alert emails your bank already
sends — no bank credentials, no aggregator, no manual entry — and turns them
into a daily journal. Pick those projects for accounting or strict budgeting;
pick Tidings for a spending record that maintains itself. Both projects are
solid; this is a difference in shape, not a ranking.

## Can I import my history?

Two paths. Bank PDF statements upload from the Statements page (built-in
parsers for RBC and Simplii chequing; AI statement parsing is an opt-in for
others). And the restore path accepts a transactions CSV, previewed before
anything is written — see [backup and restore](backup-and-restore.md).

## Why a dedicated Gmail account?

The poller reads the inbox you point it at, and an App Password grants mail
access — both are reasons to keep bank alerts in their own account rather
than your personal one. It also gives every bank one stable forwarding
target. The [email setup guide](self-hosted-email-setup.md) walks through
creating it.

## Can two people use it?

One household, yes — point both people's bank alerts at the same forwarding
inbox and the journal is shared. Separate logins, per-person views, or
multi-tenant hosting are out of scope, and staying out — see
[ROADMAP — Not doing](../../ROADMAP.md#not-doing).

## Can I put it on the internet?

It's built for loopback or a network you control — Tailscale is the
recommended way to reach it away from home. There's no rate limiting and
TLS is a reverse proxy's job, so the open internet is the wrong place for
it. The [agent access guide](agent-access.md#exposing-the-api-on-a-lan) has
the exposure checklist.

## What does it cost to run?

The software is free (MIT). Self-hosting costs whatever your machine already
costs — a Raspberry Pi is plenty. Optional extras: OpenAI categorization
(cents per month at household volume), ntfy notifications (free), the AWS
path (see the [cost analysis](dynamodb-cost-analysis.md)).

## Is my data locked in?

It's a SQLite file on your disk. Settings → Backup exports your
transactions, categories, rules, and budgets as a zip; the Search tab
exports CSV. Delete the volume and the repo and Tidings
is gone — [leaving Tidings](backup-and-restore.md#leaving-tidings) is four
steps.

## Do I need AWS?

No. The default is Docker Compose on your own machine with SQLite. The AWS
serverless path exists for people who already live there — same parsers,
different plumbing. Run the [Docker path](https://docs.gettidings.com/self-hosting/docker/)
unless you know you want Lambda.
