# Docs: Guides

Practical, step-by-step guides. Some are for self-hosters, some for people working on the project itself. The user-facing ones (email setup, notifications, AWS deployment) are also published on the docs site at [docs.gettidings.com](https://docs.gettidings.com) — the markdown here is the source of truth.

## For self-hosters

- [`self-hosted-email-setup.md`](./self-hosted-email-setup.md) — dedicated Gmail account, App Password, IMAP poller, per-bank alert settings
- [`notifications-setup.md`](./notifications-setup.md) — configuring a notification provider: ntfy (recommended), Twilio SMS, or AWS SNS
- [`configuration.md`](./configuration.md) — every `data/config.json` key: type, default, behavior, and what lives in `.env` instead
- [`agent-access.md`](./agent-access.md) — bearer-token API access: issuing tokens, scopes, and the LAN-exposure checklist
- [`troubleshooting.md`](./troubleshooting.md) — the failures self-hosters actually hit: health-dot states, parser drift, IMAP auth, ports, permissions, forgotten password
- [`backup-and-restore.md`](./backup-and-restore.md) — the backup zip, volume copies, restoring with a dry-run preview, and leaving cleanly
- [`upgrading.md`](./upgrading.md) — pull-and-restart upgrades, automatic migrations, the pre-1.0 contract, rolling back
- [`faq.md`](./faq.md) — the short answers: bank ToS and PIPEDA, what leaves your machine, importing history, costs
- [`aws-deployment.md`](./aws-deployment.md) — Docker image build + full AWS Lambda deployment workflow (the advanced path)
- [`email-to-s3-setup.md`](./email-to-s3-setup.md) — routing bank alert emails into S3 via SES, a verified domain, and a receipt rule (the AWS inbound path)

## For contributors

- [`add-a-parser.md`](./add-a-parser.md) — the parser tutorial: add support for a new bank's alert emails or PDF statements
- [`environment-management.md`](./environment-management.md) — uv setup, Python environment, dependency management
- [`dev-surfaces.md`](./dev-surfaces.md) — frontend port map: the five dev surfaces, port-override flags, and BrowserRouter basename rules
- [`devcontainer-startup.md`](./devcontainer-startup.md) — DevContainer lifecycle and environment priming
- [`slash-commands.md`](./slash-commands.md) — category management, test review, spending insights, doc review slash commands
- [`static-hosted-demo.md`](./static-hosted-demo.md) — building, previewing, and regenerating fixtures for the static Cloudflare-Pages demo
- [`dynamodb-cost-analysis.md`](./dynamodb-cost-analysis.md) — DynamoDB cost model and sizing
- [`releases.md`](./releases.md) — versioning policy, branching model, and the step-by-step release ritual
