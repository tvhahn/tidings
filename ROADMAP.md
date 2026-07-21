# Roadmap

> Direction, not commitments. What works today lives in the [README](README.md)
> and [docs.gettidings.com](https://docs.gettidings.com); what shipped when
> lives in [`CHANGELOG.md`](CHANGELOG.md). Priorities shift with community
> feedback — if something here matters to you, open an issue and say so.

Tidings is built by one maintainer plus contributors: an email-first,
self-hosted finance journal. No Plaid, no bank APIs. Five Canadian banks ship
today; the architecture is country-neutral and parsers for institutions
anywhere are a contribution surface.

## On the radar

Rough order of interest, not a schedule:

- **More parsers** — the highest-leverage contribution. Email alerts for new institutions, and PDF statement coverage beyond RBC and Simplii. See the [parser tutorial](docs/guides/add-a-parser.md).
- **Monthly summary scheduler for self-hosters** — an in-app scheduler to replace the AWS EventBridge trigger, so the Docker path gets end-of-month summaries too.
- **Fuller AWS onboarding docs** — rewritten deployment guide, SES email-receiving setup, SMS/10DLC pointers.
- **Notification provider contributor guide** — a "how to add Pushover / Discord / Slack" worked example, mirroring the parser tutorial.
- **Unified `deploy.sh` for the AWS path** — one idempotent orchestrator with `install` / `update` / `teardown` / `status` subcommands.
- **Shareable demo deep links** — URLs into the hosted demo with preloaded state.
- **Native MCP entry-point** — a `finance-mcp` stdio server wrapping the bearer-token API, so MCP-native agents (Claude Desktop and similar) connect without hand-writing HTTP tools.
- **Release tooling** — adopt [release-please](https://github.com/googleapis/release-please-action) once the manual release ritual feels like overhead (around release 5–10), and pin GitHub Actions to commit SHAs before 1.0 so two builds of the same tag can't differ.
- **Bank ToS + PIPEDA FAQ** — the honest answer to "is it OK to forward my own bank emails?"
- **Conversational assistant** — "ask an agent about your transactions" over the existing API. Speculative; only if it's genuinely useful rather than gimmicky.

## Not doing

- **No Plaid or bank-API integration. Ever.** Email-first, no-credential ingestion is the identity of the project.
- **No multi-user / family mode.** Tidings is a single-household journal.
- **No native mobile app.** The responsive web UI is the mobile story.
- **No zero-based budgeting methodology.** Tidings shows where money went; it doesn't assign every dollar before you spend it.

## How to influence this

Open an issue or GitHub Discussion — "I want X" or "X matters more than Y" is
useful signal. PRs are welcome on anything above, parsers especially; comment
on an existing issue before starting so work doesn't double up.
