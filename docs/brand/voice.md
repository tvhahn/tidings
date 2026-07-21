# Voice

> Promoted from the **Content Fundamentals** section of `docs/specs/_archive/2026-04-24-design-system-refactor/design_handoff_tidings/design_system/DESIGN_SYSTEM_GUIDE.md` and §4 of `docs/specs/_archive/2026-04-24-marketing-and-demo/IMPLEMENTATION_PLAN.md`. Both originals are local-only historical records (absent in the public repo) and now point here.

Tidings speaks like **a thoughtful private journal**, not a fintech dashboard. Copy is quiet, observational, declarative. It never scolds, never celebrates, never nudges loudly. The mental model: a monthly statement from your bank, if your bank cared about typography.

This page is split into three layers:

1. **Voice constants** — invariant rules. Apply everywhere. Non-negotiable.
2. **Tone flexes** — contextual moves. Vary by surface (marketing vs. error vs. empty state).
3. **Word lists, name rules, PR checklist** — operational reference.

---

## 1. Voice constants (apply everywhere)

These are invariant. They apply to marketing copy, in-app copy, error messages, empty states, tooltips, toasts, README prose, and PR descriptions.

- **Observant, not evaluative.** "You spent $42 on groceries" — never "Nice job!" or "Yikes, that adds up." The system describes; it does not judge.
- **Second person, present tense.** "You" addresses the reader directly. The system is implicit and never uses "I" or "we" in product UI. (README prose can use "this app" — but never "we", which implies a team or company that does not exist.)
- **Sentence case everywhere.** No ALL CAPS labels. No tracking-heavy badges. Headings, button labels, nav items, pill labels — all sentence case. Two exceptions: small-caps eyebrows on the marketing landing (`text-transform: uppercase` + `letter-spacing: 0.06em`), and in-app **data eyebrows** — the small uppercase tracked labels set over a serif display number ("SPENT · AS OF JUN 9", "VS. MAY", "RECEIVED · YTD") plus the sidebar workspace section label. Data eyebrows are the statement-typography signature, not shouting: 11px, `0.08em` tracking, `--fg-muted`, always paired with a display amount. They are never buttons, headings, or sentences.
- **No exclamation marks. Ever.** Not in toasts, not in onboarding, not in empty states, not in error messages. If a sentence feels like it needs one, the sentence is wrong.
- **No emoji in product UI.** Lucide icons do the job emoji would do. (README badges and CHANGELOG entries are exempt — those are GitHub conventions, not product surface.)
- **No growth-copy verbs.** "Unlock", "supercharge", "crush", "conquer", "boost", "skyrocket", "level up" — all banned.
- **No gamification.** "Streak", "win", "level", "score", "achievement", "challenge" — all banned. Money is not a game.
- **No alarmist framing.** "Danger", "warning!", "critical", "alert!", "urgent" — banned in user-facing copy. The CSS token can be `status-danger` because it is internal vocabulary, but the visible string says "over ceiling" or "above target", not "warning!".
- **No bank formality.** "Transaction ledger", "statement period", "debit / credit" — too cold and too procedural. Say "transactions", "this month", "spent / received".

## Tagline

**Your spending, delivered.**

Use the comma. Use sentence case. The italic on "delivered" is a marketing-typography choice, not a copy choice — never write it as `*delivered*` in plain prose.

## Hero subtitle

*A private finance journal from the transaction emails you already receive.*

## Closers

The tagline and hero subtitle are verbatim on every surface that carries them. A surface may follow the pair with **one** of two sanctioned closers — pick one, never coin a new one:

- **Proof** — *No Plaid. No bank credentials. No manual entry.* The anti-credential promise. (Marketing footer sign-off.)
- **Ethos** — *Self-hosted, open source, calm by default.* What the project is. (Marketing footer brand column.)

Sentence-form adaptation is fine — commas instead of periods, lowercase after an em dash. Two sanctioned variations: the README strapline folds "self-hosted" into the proof list ("— self-hosted, no bank credentials, no manual entry") for the GitHub audience, and the marketing hero extends the subtitle with a sentence instead of a closer ("Forward them, and Tidings turns them into a calm daily record."). Running prose (README body, positioning, llms.txt descriptions) is not bound to these lockups.

---

## 2. Tone flexes (vary by surface)

Voice is invariant; tone bends to context. Three axes to consider when drafting a string:

| Axis | Marketing landing | Product UI | Error / failure | Empty state |
|---|---|---|---|---|
| **Formality** | Editorial, slightly elevated | Plain, declarative | Plain, factual | Plain, faintly inviting |
| **Energy** | Quiet confidence | Calm, neutral | Matter-of-fact | Calm, patient |
| **Technical depth** | Minimal jargon, names the moat ("no Plaid", "your bank's emails") | Domain language fine ("category", "override", "unbudgeted") | Specifics over generics ("OpenAI key not set" beats "Configuration error") | Names what's missing without scolding ("No transactions yet — once your forwarder is wired, they appear here.") |
| **Length** | Short paragraphs, generous whitespace | One line where possible | One line + recovery action | One sentence + a hint |

### Surface-specific examples (lifted from current product copy)

| Situation | Copy |
|---|---|
| Month picker label | "December 2025" — full month name, full year, no abbreviation |
| Empty category | "Uncategorized" — not "—", not "No category" |
| Freshness | "synced 2m ago · 3:14:02 pm · latest tx 4h ago · SQLite" |
| Over-budget headline | "$112 over ceiling" — the number first, the fact plain |
| Enrichment meta | "89% of budget", "10× this month" — compact facts |
| Demo banner | "Demo mode — data is sample transactions" |
| Nav label for disabled | "Soon" (not "Coming soon", not "WIP") |
| Toast confirmation | "Category updated to Groceries" — subject first, with Undo action |

### Before / after

**Before:** "🎉 You crushed your dining budget this month! 23% under!"
**After:** "Dining is $48 under target this month."

**Before:** "WARNING! Your groceries spending is 105% of budget — take action!"
**After:** "Groceries is $14 over ceiling."

**Before:** "Welcome aboard! Let's unlock your financial superpowers 🚀"
**After:** "Forward your bank's transaction emails to the address shown in Settings. Transactions appear here as they arrive."

**Before:** "Oops! Something went wrong. Try again later."
**After:** "OpenAI key is not set. Add it in Settings → Intelligence to enable AI categorization."

---

## 3. Word lists

### Banned words (do not ship in user-facing copy)

`unlock`, `supercharge`, `crush`, `conquer`, `boost`, `skyrocket`, `level up`, `streak`, `win`, `level`, `score`, `achievement`, `challenge`, `urgent`, `critical`, `alert!`, `warning!`, `danger`, `oops`, `whoops`, `awesome`, `amazing`, `magical`, `seamless`, `effortless` (the work involved is not zero — say "no manual entry" instead), `revolutionary`, `disrupt`.

### Approved domain terms

| Term | Use it for |
|---|---|
| **Transaction** | The atomic unit. Singular and plural both fine. |
| **Category** / **uncategorized** | The classification of a transaction. "Uncategorized" is a real category, not a placeholder. |
| **Override** | A user rule that pins a merchant pattern to a category. |
| **Budget** / **ceiling** / **target** | The annual budget amount. "Target" is the neutral term — use it for the dial-in moment ("set a target"). "Ceiling" is the over-state framing word — use it once spend has crossed the line ("$112 over ceiling"). Avoid "envelope" — it implies envelope-budgeting (YNAB / Mvelopes), which Tidings is not. |
| **Pace** | Spending velocity vs. budget. "On pace" / "off pace" / "ahead of pace". |
| **Insight** / **briefing** | The AI-generated monthly narrative. Never "report" (too corporate), never "analysis" (too clinical). |
| **Forwarder** / **forwarding address** | The Gmail address the user forwards bank emails to. |
| **Statement** | A bank-issued PDF the user uploads for reconciliation. Distinct from a transaction. |
| **Journal** | The day-grouped transaction view. The name of the page (`/journal`) and the conceptual model. |

### Product-name rules

- The product is **Tidings**. Always capitalize the T.
- Never abbreviate. No "Tids", no "T.", no `:tidings:` slack-emoji style.
- Sentence case applies to *the rest of the sentence*, not to the name. "Open Tidings" not "Open tidings".
- The public repository is `tidings`; user-facing copy is always Tidings.
- The domain is `gettidings.com`. The demo is `gettidings.com/demo`.
- Wordmark: serif (Source Serif 4), tight tracking (`-0.015em`). Never set the wordmark in a sans typeface.

---

## 4. PR review checklist (5 bullets)

Before merging any PR that touches user-facing copy, the reviewer (human or `/review` slash command) confirms:

1. **No exclamation marks** in any new or changed string. (Comments and JSDoc are exempt.)
2. **Sentence case** on every label, button, heading, and pill. No ALL CAPS, no Title Case headlines.
3. **No banned words** from §3 above. `grep` the diff for `unlock|crush|streak|supercharge|boost|alert!|warning!|critical|danger!|oops|whoops`.
4. **Observant, not evaluative.** No string celebrates, scolds, congratulates, or warns the user about their financial behaviour. Numbers and facts only.
5. **Voice consistency.** A new string, read alongside three nearby existing strings, sounds like the same writer wrote all four. If it does not, it is wrong.

For copy-heavy PRs (marketing edits, FAQ additions, multi-string features), also run the `.claude/skills/brand-voice/` skill before requesting review.
