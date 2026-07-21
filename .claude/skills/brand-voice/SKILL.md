---
name: brand-voice
description: Apply Tidings brand voice to any user-facing copy — marketing strings, error messages, empty states, tooltips, toasts, FAQ entries, button labels, README prose. Loads the canonical voice rules from docs/brand/voice.md and self-checks the result against the 5-bullet PR review checklist. Invoke when writing or editing any string a user will see, or when reviewing a copy-heavy diff.
---

# Brand Voice — Tidings

The Tidings voice is **observant, not evaluative; quiet, not loud; a private journal, not a fintech dashboard**. Apply this skill whenever drafting or editing copy a user will see.

## When this skill applies

Trigger on any of:

- Writing or editing marketing copy (`frontend/src/marketing/**`).
- Drafting an error message, toast, or notification string.
- Writing an empty state for a page or component.
- Adding or editing a tooltip, label, button, or pill text.
- Writing a FAQ entry, onboarding step, or settings description.
- Composing README prose, CHANGELOG entries (user-visible portions), or PR descriptions for copy changes.
- Reviewing a PR diff that contains string changes.

Skip this skill for: comments, JSDoc, log messages (developer-facing), test fixtures, or internal variable names.

## Workflow

1. **Load the voice rules.** Read [`/workspace/docs/brand/voice.md`](../../../docs/brand/voice.md) before writing. The voice constants and tone-flex table are the bar; the banned-word list and approved domain terms are the operational reference. For a faster cheat-sheet load, read [`references/voice-quick-ref.md`](references/voice-quick-ref.md).

2. **Identify the surface and tone flex.** Marketing landing, product UI, error / failure, or empty state? Each surface has different formality, energy, and length conventions — see the tone-flex table in `voice.md` §2.

3. **Draft the string.** Apply the voice constants:
   - Observant, not evaluative.
   - Sentence case.
   - No exclamation marks.
   - No emoji in product UI.
   - No banned growth / gamification / alarmist words.
   - Number first when reporting a fact ("$48 under target", not "Under target by $48").

4. **Prefer editing existing strings before adding new ones.** If a similar string already exists in the area you're touching, match its rhythm rather than introducing a new phrasing pattern. Voice consistency reads as one author wrote everything.

5. **Self-check against the 5-bullet PR review checklist** (in `voice.md` §4):
   - No exclamation marks in any new or changed string.
   - Sentence case on every label / button / heading / pill.
   - No banned words from the §3 list.
   - Observant, not evaluative — no celebrating, scolding, congratulating, or warning.
   - Voice consistency — the new string sounds like the same writer wrote three nearby existing strings.

6. **Verify naming.** If the product is mentioned, it is **Tidings** (capital T, never abbreviated).

## Common failure modes

- Drafting "We do X" — Tidings uses second person ("you") in product UI, never "we" (no team / company exists).
- Reaching for an exclamation to convey enthusiasm in a positive empty state — use a calm declarative instead ("Your forwarder is wired. Transactions appear here as they arrive.").
- Using `urgent` / `critical` / `warning!` in error copy because the underlying state is red — the CSS token can be `status-danger`, but the visible string says "over ceiling" or "above target".
- Title-casing a button label out of habit (`Add Transaction`) — sentence case wins (`Add transaction`).
- Calling the AI insights "report" or "analysis" — they are "briefings" (less corporate, less clinical).

## When you finish

Hand the result back. If the user asked you to write *and* land a change in code, do that — but state explicitly which voice rules you applied, especially if you rewrote a string the user originally drafted differently. The user may want to override on a case-by-case basis (very rarely justified, but possible).
