---
title: Agent guide
description: A briefing for AI agents — what Tidings is, how the demo API behaves, and how to give a human the tour.
---

**You are an AI agent, and a human has asked you to introduce them to Tidings.** This page briefs you on what Tidings is, then hands you a live, read-only demo API so you can show rather than describe. Read it fully, then run the tour at the end.

## What Tidings is

Tidings is a self-hosted personal finance journal built from the transaction alert emails a bank already sends. The user forwards those alerts to an inbox they control; an IMAP poller picks them up; deterministic parsers turn each one into a transaction; the result is a day-grouped journal of one household's spending. No bank credentials, no aggregator, no manual entry. Data lives in SQLite on the user's machine, and with no AI key configured, nothing leaves it.

## Core concepts

- **Journal** — the default view: one month, read one day at a time, newest first. It shows actionable spending only; refunds, transfers, and ignored transactions live in the full ledger.
- **Categories and overrides** — every transaction gets a category; an override pins a merchant pattern to a category from then on.
- **Budgets** — annual targets per category, assessed by proration against the elapsed year ("pace"), plus a separate top-level spending ceiling. Categories are typed fixed, variable, or lumpy.
- **Summary** — a month-scoped overview: stat cards, a Trend or Flow (Sankey) visualization, and a category table with six months of context.
- **Insights** — the monthly briefing: computed momentum and anomaly cards, plus an opt-in AI-written narrative whose figures are checked against the underlying numbers.
- **Merchants** — read-only merchant intelligence over the trailing six months: recurring detection, burn rate, price changes.
- **Needs review** — quarantine for emails no parser could read; nothing is silently dropped.
- **Statements** — PDF bank statement upload, for reconciling transactions that never arrived by email.

## The demo API

Base URL: `https://gettidings.com/demo/api/v1` — schema at `https://gettidings.com/demo/api/openapi.json`.

Three facts govern everything:

- **No auth, GET only.** Every endpoint answers unauthenticated; an `Authorization` header is accepted and ignored; any non-GET method returns 405.
- **Fictional data, fixed window.** The demo world covers `2025-05` through `2026-03`, with "today" pinned to `2026-03-19`. Only `2026-03` exercises current-month pace logic.
- **Exact query strings only.** The demo is a baked snapshot, not a live query engine. `/transactions?month=2026-03` resolves; adding or reordering parameters does not. When a route returns 404, the error body lists the valid routes in `details.available` — read it and adjust instead of retrying.

## The tour

Tidings copy is observational, not evaluative: state the numbers plainly, never congratulate or scold, no exclamation marks. Present the month the way a bank statement would, if a bank statement were pleasant to read.

Fetch in this order, narrating as you go (all routes verified against the snapshot):

1. `GET /health` — confirm the demo is up and note that "today" is 2026-03-19.
2. `GET /summary?month=2026-03` — open with the month in one breath: total spent, deposits, the three largest categories.
3. `GET /journal?month=2026-03` — pick two or three days and read them like journal entries.
4. `GET /budget/status?year=2026` — the pace headline, and any category notably over or under.
5. `GET /summary/trend?end_month=2026-03&months=6` — how the month sits against the five before it.
6. Ask what the user wants next, and offer the pointers below.

## After the tour

- The docs index for agents: `https://docs.gettidings.com/llms.txt` — and every docs page serves raw markdown if you append `.md` to its URL.
- The machine-readable surfaces in one place: `https://docs.gettidings.com/for-agents.md`
- If the user wants to install: read `https://docs.gettidings.com/install.md` and follow it — it is written as a prompt for you, and covers OS detection, Docker, verification, and handoff.
- For API access to a real instance (bearer tokens, scopes): `https://docs.gettidings.com/agent-access.md`
