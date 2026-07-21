# Positioning

> Promoted from `docs/specs/00_open-source-migration/2026-03-21-dhh-philosophy/POSITIONING_BRIEF.md` (drafted 2026-03-21 by Soren Madsen · Kenji Watanabe · Amara Diallo · Priya Shah · Marcus Vogel). The original spec is preserved as a local-only historical record (absent in the public repo); this file is the canonical home.

## Headline

A private finance journal built from the transaction emails you already receive — no Plaid, no bank credentials, no manual data entry. The dashboard runs in Docker on your own machine; ingestion runs locally via an IMAP poller (Pi, NAS, any always-on machine), or in your own AWS account if you prefer that path. Parsers ship today for five Canadian banks; the architecture is country-neutral, and the contribution model is built for adding banks, card issuers, and locales anywhere.

## For

People whose bank or card issuer sends transaction alert emails, and who want automatic transaction tracking without sharing banking credentials with a third party. Tidings supports RBC, CIBC, MBNA, Simplii, and PC Financial today. If your institution isn't among them, the path forward is described under "Adding a bank or card issuer" below.

People who are willing to spend a half-day on setup in exchange for automatic transaction capture without ongoing manual entry, and who want to know whether their spending is on pace without managing a zero-based budget or maintaining a spreadsheet.

## Not For

Users whose institution isn't supported and who need zero-setup, day-one onboarding. Parsers ship today for RBC, CIBC, MBNA, Simplii, and PC Financial. If your bank or card issuer emails transaction alerts but isn't on that list, the path forward is described under "Adding a bank or card issuer" below — but it is not instant.

Users who want a mobile app, zero-based budgeting, investment tracking, or automatic bank synchronization without any setup — the SMS notification is the mobile experience, annual targets are the budget methodology, and email forwarding configuration is required.

Two ingestion paths are supported. The **IMAP-polling daemon** is the default: it runs on a Raspberry Pi, a NAS, a VPS, or any always-on machine, with no cloud account required. Most users should pick this path. The **AWS account-hosted pipeline** (Lambda + S3 + SES + DynamoDB — your account, not ours) is the more advanced alternative for users who are already comfortable with AWS and would rather not expose an inbox to a polling daemon. The AWS path involves more wiring and is correspondingly less hand-held in the docs; community contributions to that path are welcome but the maintainer's day-to-day driver is the IMAP path. Pick the one that fits your trust model and your appetite for cloud-infra setup.

## Institution support

| Region | Institution | Type | Status |
|---|---|---|---|
| Canada | RBC | Bank / credit card | Supported |
| Canada | CIBC | Bank / credit card | Supported |
| Canada | MBNA | Credit card | Supported |
| Canada | Simplii | Bank | Supported |
| Canada | PC Financial | Money account / credit card | Supported |
| Other regions | Any institution that emails transaction alerts | Bank, card issuer, payment account | Parser contribution welcome |

This table is the canonical support list. Other docs (README, marketing FAQ, BRAND.md) should link back to it instead of restating institution names.

## Country-neutral architecture

Tidings starts with Canadian bank support because those are the parsers available today. That is a launch constraint, not a product boundary.

The architecture is country-neutral: if an institution sends structured transaction alert emails, Tidings can support it through a parser. Parser contributions for banks, credit card issuers, and payment accounts in any country are welcome.

International support may require locale-specific handling for currency symbols, decimal separators, date formats, languages, time zones, refund wording, and card / account identifiers. The parser contract in the [add-a-parser guide](../guides/add-a-parser.md) documents these surfaces.

## Adding a bank or card issuer

If your bank, credit card issuer, or payment account emails transaction alerts and isn't yet supported, two paths are open:

1. **Contribute a parser yourself.** The [add-a-parser guide](../guides/add-a-parser.md) walks through the parser contract, the registration points in `email_pipeline.py`, the test-fixture convention, and locale considerations (currency symbols, decimal separators, date formats, time zones, non-English email bodies). Contributions for any institution, in any country, are welcome and will be reviewed and merged.

2. **Open an issue with sample emails.** If you'd rather not write the parser yourself, file an issue at [`github.com/tvhahn/tidings/issues`](https://github.com/tvhahn/tidings/issues) with three or four sample alert emails attached. Strip personal information first — account numbers, balances, names, and any identifiers your institution includes — leaving only the merchant, amount, date, and the surrounding email structure the parser needs to lock onto. The maintainer adds parsers as capacity allows; there is no commitment on timing, and institutions whose alerts carry too little structured data may not be tractable.

Once a parser exists — whether contributed or maintainer-written — ingestion just works: forwarding addresses, IMAP or AWS routing, and the dashboard need no per-institution changes.

## Why It's Different

- **Email-first ingestion is architecturally absent from every other tool.** A comprehensive search of GitHub, HackerNews, and the OSS self-hosted ecosystem found zero other maintained repositories parsing real-time transaction alert emails from RBC, CIBC, MBNA, Simplii, or PC Financial. The entire category — commercial and open-source — is built on bank API aggregation or manual CSV import. This app inverts the model: the bank sends you an email you would receive anyway; the app reads it. No OAuth tokens. No Plaid credentials stored on a third-party server. No screen-scraping sessions that break when the bank updates their login page.

- **MBNA and PC Financial are invisible to every non-email tool.** YNAB lists MBNA as "Not covered." Monarch lists it as "Not covered." PC Financial: not covered anywhere. Plaid-based tools fail Canadian users specifically because Canadian open banking is unimplemented as of March 2026 — connections break on two-factor authentication, bank security updates, and session expiry. Email forwarding sidesteps all of this: it uses a channel the bank already operates and the user already receives. The structural advantage grows larger, not smaller, the longer Canada delays open banking.

- **The AI works with the privacy story, not against it.** The override-first architecture means OpenAI handles fewer than one in ten transactions after six months of use — known merchants map locally from the override file without touching any API. For monthly briefings, Claude receives only category totals (e.g., `{groceries: 487, dining: 214}`) — no merchant names, no individual transactions, no dates. Both services are fully optional: in fully local mode with no API keys configured, zero outbound network calls are made. This is a verifiable architectural claim, not a privacy policy.

- **Built for the agent era.** Clean OpenAPI surface at `/api/v1/*`, an `INSTALL.md` an LLM can read and execute against the user's machine, and optional bearer auth for headless consumption. Agent-driven install and agent-driven daily use are first-class paths alongside the bundled dashboard, not afterthoughts.

## The Line in the Sand

**This app will never integrate with Plaid, Yodlee, Flinks, or any bank API aggregator.**

Not as a workaround while email parsing matures. Not as an optional connection for banks without email parsers. Not as a "power user" feature. The email-first, no-credential architecture is the product's load-bearing opinion: it is what makes the privacy story architectural rather than policy-based, what makes the data pipeline automatic rather than user-operated, and what makes the supported-bank constraint meaningful rather than arbitrary. If you add Plaid as an alternative ingestion path, the "no credentials" claim becomes conditional. The principle becomes a preference. Everything downstream of that — the privacy documentation, the r/selfhosted positioning, the "This is not for you" section — loses its teeth.

Banks without email parsers are served by the contribution model: submit a parser for your institution and extend the app's reach without changing its architecture.

## The product name: Tidings

The product is called **Tidings**. From Old English meaning "news / letters arriving" — a quiet echo of the email-first moat, with a soft money association ("good tidings") and headroom for future receipt/tax extensions without renaming. Decided 2026-04-19 by a five-expert naming panel; the runner-up was Pennypost. Capitalize as "Tidings" (sentence case in body copy; never abbreviate, never lowercase). Every user-facing surface — domain (`gettidings.com`), wordmark, marketing copy, in-app branding — uses Tidings.

The name was chosen by a five-expert naming panel weighing tier scoring, domain availability, and runner-up names.

## Show HN Title

**Show HN: I open-sourced my self-hosted personal finance app after 2 years of daily use — parses bank transaction emails, no Plaid**

*(If launching as a new project without the 2-year history to claim, use:)*
**Show HN: Self-hosted personal finance app that parses your bank's transaction emails — no Plaid, Docker + IMAP**

*Rationale: "Self-hosted" sits in the title now that the IMAP-polling daemon is the default ingestion path — the full pipeline (dashboard + ingestion) can run on a Pi, NAS, or VPS with no cloud account. The architectural claim — email parsing, no Plaid, no aggregator — is the wedge. "Canadian banks" is dropped from the title in favour of the universal product idea; the body of the post should mention that five Canadian banks ship today and that parsers for other institutions are a contribution surface. The 2-year-of-daily-use signal, when accurate, is the strongest credibility marker available: it says this is a tool someone actually runs, not a weekend project. The body should also describe the two ingestion paths honestly: IMAP for fully local, AWS account-hosted for users who prefer that route.*

## r/PersonalFinanceCanada Pitch

Parses transaction alert emails from RBC, CIBC, MBNA, Simplii, and PC Financial — including MBNA and PC Financial, which no other automated tool supports. Self-hosted, open-source, no monthly fee, no Plaid.

If you're still on spreadsheets because every tool you've tried either doesn't support your bank or keeps breaking its Canadian connections, this is built for exactly that situation.

## r/selfhosted Pitch

Two-layer architecture, two ingestion paths — worth being upfront about:

**Dashboard layer:** Docker + SQLite, runs on your own machine or VPS. Standard self-hosted deployment: `docker compose up`, data stays local, no external services required for the dashboard itself.

**Email ingestion layer (default — IMAP poller):** A long-lived Docker service logs into a dedicated email account over IMAP, fetches new bank emails as they arrive, and runs them through the parser pipeline. Runs on a Raspberry Pi, a NAS, the same VPS as the dashboard, or any always-on machine. No cloud account required. This is "self-hosted" in the strict r/selfhosted sense — your hardware, end to end. Setup walkthrough: [`docs/guides/self-hosted-email-setup.md`](../guides/self-hosted-email-setup.md).

**Email ingestion layer (alternative — your own AWS account):** Lambda + S3 + SES + DynamoDB, all in your AWS account, free tier for most personal volumes. "Your infrastructure, your data, your AWS account" — the bank emails land in your S3 bucket, your Lambda processes them, your DynamoDB stores the transactions. AWS is in the stack, but no third-party fintech is. This path involves more infrastructure setup; pick it if you're already comfortable with AWS and would rather not expose an inbox to a polling daemon. The IMAP path is the maintainer's daily driver and is more directly supported.

No Plaid. No credential sharing. No third-party fintech handling your data, on either path. Run `grep -r "plaid\|yodlee\|finicity" src/` to verify the credential story — the no-Plaid claim is architectural, not a policy.
