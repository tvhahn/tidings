---
description: Generate an AI-powered spending briefing for a given month
argument-hint: "[YYYY-MM]"
model: sonnet
---

Your task is to generate a monthly spending briefing for the given month.

## Step 1: Gather spending data

Run the data gathering script. Use `$ARGUMENTS` as the month if provided, otherwise default to the current month:

```
uv run dev/cli/gather_insights_data.py <YYYY-MM>
```

The context JSON will be saved to `data/insights/context_<YYYY-MM>.json`.

## Step 2: Read the context file

Read the generated context JSON file to understand the full financial picture for the month.

## Step 3: Generate the briefing

Using the context data, write a monthly spending briefing addressed to the reader — the person whose money this is. The sections and rules below are fixed; follow them exactly so every month reads as the work of the same steady hand.

### Voice

- Second person, present tense: "you spent", "your groceries", "this month" — always writing to the reader, never about them in the third person, and never as "I" or "we".
- Observe, do not judge. State the number and what it shows. No praise, no scolding, no "good" or "bad", no "should".
- Phrase anything actionable as an option the reader has, not an instruction: "an auto-ignore rule would keep these transfers out of your totals", not "you should review these".
- No exclamation marks, and none of the alarm words a nervous bank reaches for — no "alert", no "warning", no "urgent". A large or unusual number is stated plainly and left to speak for itself.
- Section headers are sentence case, exactly as written below, at the `##` level.

### Actions available in Tidings

When a finding maps to one of these, you may name it in passing — never as a command, and no more than two or three across the whole briefing:

- Annotate a transaction with a comment, on the Journal page, to record intent.
- Set a category override or an auto-ignore rule, on the Categorize page, to fix where a transaction lands or keep transfers and payments out of totals.
- Adjust a budget target, on the Budgets page.
- Update the standing briefing memo, in Settings → Intelligence.

### Numbers

Every dollar amount and percentage must appear verbatim in the context data — do not derive, annualize, or compute any new figure. All pace and projection numbers come from `pace`; the year-end figure is always `pace.ceiling.projected_adjusted`, never `projected_naive`. Use `commented_transactions` to explain what a number means, not to raise it as a concern.

### Sections

#### The month in brief
One or two sentences: the month's total, its direction against last month, and the single thing that most explains it. No bullets.

#### What changed
Three to five bullets on the month's most notable movements — against last month, the six-month trend, budget pace, and historical averages. When `previous_briefing` is present, the first bullet follows up on what it raised: resolved, still here, or larger. Connect categories rather than restating the table below.

#### Where the month went
A short lead sentence, then exactly one table covering the top three to five categories by spending. Use these columns and no others:

| Category | This month | Last month | Pace | Notable merchants |

Fill "Pace" with the plain read from `pace` — "on target", "ahead of pace", "$210 over target", or "—" where no target exists. Do not add columns, a totals row, or a second table anywhere in the briefing.

#### Worth attention
Two to four bullets on the month's outliers: a category well past its pace, a spend far above its six-month norm, a category that fell to zero, or a single merchant carrying most of a category. State each as a fact with its number, and leave out anything a comment already explains. Mention `suspected_ignored` here in a single line only when it is non-empty. Omit this whole section when nothing qualifies.

#### Your notes
Include only when `commented_transactions` is non-empty. Two to four bullets on what the reader annotated and how it shapes the month, grouping related comments. Omit this whole section when there are no comments.

#### Looking ahead
Two to four sentences. If the month is still partial, give the projected month-end total from the data. Otherwise look to year-end with `pace.ceiling.projected_adjusted` against the ceiling, and name the categories most in play. Frame next steps as options the reader has, not tasks.

### Formatting

- Plain markdown. Do not use bold anywhere — not for amounts, not for labels. The single table above is the only table; everything else is prose and bullets.
- Keep the prose outside the table to roughly 350–500 words.
- Print figures the way a bank statement would, without changing their value: thousands separators and two decimals or none — $14,407.60 or $14,408, never a raw $14407.6, $1348.0, or $0.0. Percentages keep at most one decimal: 19.2%, not 19.22%.
