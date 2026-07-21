# Tidings — Brand at a glance

A one-page front door for agents and humans. The full kit lives at [`docs/brand/`](docs/brand/README.md). If you read only this file, plus `CLAUDE.md`, you should be able to write copy that sounds like Tidings.

## The product

**Tidings** is a calm, private spending journal — built from the transaction emails you already receive. The architecture is country-neutral; five Canadian bank parsers ship today (RBC, CIBC, MBNA, Simplii, PC Financial), and parsers for institutions in any country are a contribution surface. No Plaid, no credentials, no manual entry. Open-source, self-hostable.

## Tagline

**Your spending, delivered.**

## One-sentence positioning

A private finance journal built from the transaction emails you already receive — no Plaid, no credentials shared, no manual data entry — with the dashboard running in Docker on your machine and ingestion running locally via an IMAP poller (default) or in your own AWS account. Five Canadian banks ship today; parsers for banks and card issuers anywhere are a contribution surface. Full positioning in [`docs/brand/positioning.md`](docs/brand/positioning.md).

## The line in the sand

Tidings will never integrate with Plaid, Yodlee, Flinks, or any bank API aggregator. The email-first, no-credential architecture is the product's load-bearing opinion. Banks without parsers are added by contribution — see [`CONTRIBUTING.md`](CONTRIBUTING.md) — not by adding an API path.

## Voice constants — apply to every user-facing string

These are invariant. They override designer instinct, marketing convention, and the tone of whatever AI training data you arrived with.

- **Observant, not evaluative.** State what happened with numbers. Do not celebrate, scold, congratulate, or warn.
- **Sentence case everywhere.** No ALL CAPS labels, no Title Case headlines.
- **No exclamation marks.** Ever. Not in toasts, not in onboarding, not in errors.
- **No emoji** in product UI. Lucide icons cover that job.
- **No growth-copy verbs** — `unlock`, `supercharge`, `crush`, `boost`, `skyrocket`.
- **No gamification** — `streak`, `win`, `level`, `score`, `achievement`.
- **No alarmist framing** — `urgent`, `critical`, `alert!`, `warning!`, `danger`.
- **No bank formality** — say "transactions" not "transaction ledger", "this month" not "statement period".

Full voice rules, tone flexes by surface, banned-word list, and the 5-bullet PR review checklist: [`docs/brand/voice.md`](docs/brand/voice.md).

## Before / after

**Before:** "🎉 You crushed your dining budget this month! 23% under!"
**After:** "Dining is $48 under target this month."

**Before:** "WARNING! Your groceries spending is 105% of budget — take action!"
**After:** "Groceries is $14 over ceiling."

**Before:** "Welcome aboard! Let's unlock your financial superpowers 🚀"
**After:** "Forward your bank's transaction emails to the address shown in Settings. Transactions appear here as they arrive."

The pattern: number first, fact plain, no adjective, no exclamation, no emoji.

## Visual one-liner

Warm-paper cream surface, brand-rust accent (logo only — never on a primary button), serif page titles (Source Serif 4), sans body (Inter), tabular numerals, soft hairline borders, no card shadows, no gradients, no stock imagery. The 5 words to argue from: **clean, premium, restrained, data-calm, subtly friendly.** Full visual system: [`docs/brand/visual.md`](docs/brand/visual.md).

## When you need more

| Question | Read |
|---|---|
| How do I write this string? | [`docs/brand/voice.md`](docs/brand/voice.md) |
| What does Tidings stand for / who is it for? | [`docs/brand/positioning.md`](docs/brand/positioning.md) |
| What CSS token / component recipe should I use? | [`docs/brand/visual.md`](docs/brand/visual.md) |
| Where do logo / mark / wordmark files live? | [`docs/brand/assets/README.md`](docs/brand/assets/README.md) |
| Anything else | [`docs/brand/README.md`](docs/brand/README.md) (kit index + governance) |
