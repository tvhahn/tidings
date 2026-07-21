---
name: tune-fable-prompt
description: Tune a prompt, system prompt, skill, or autonomous goal-loop (/loop, /goal) instruction set that will be RUN BY Claude Fable 5 or Mythos 5, applying Anthropic's Fable 5 prompting patterns. Can also scaffold a Fable-tuned prompt from a description. Presents recommended tuning options via AskUserQuestion and applies your choices. Not for prompts targeting other models.
disable-model-invocation: true
argument-hint: "[audit|tune|scaffold] [file path, pasted prompt, or intent]"
---

# Tune Fable Prompt — Fable 5 prompt-tuning pass

You tune a prompt so that **Claude Fable 5 (or Mythos 5) executes it well**. The target of every edit is the *other* model that will run this prompt later — not you, the tuner. Never execute the prompt's task yourself; your deliverable is a better prompt.

**Before doing anything, read [`reference/prompting-fable-5.md`](reference/prompting-fable-5.md) in this skill's directory.** It is the canon: the behavioral differences and the exact snippets to insert. Every finding and every inserted snippet must trace to a section of it (cite the section). Pull snippets close to verbatim — adapt only the bracketed placeholders (`[X]`, `[the larger task]`, `[who it's for]`).

## Modes

- **`tune` (default):** audit silently, present the proposed changes interactively (step 3), apply the chosen ones. If the input is a **file path**, apply with targeted Edits — never rewrite passages that are already well-tuned. If the input is **pasted text**, return the revised prompt.
- **`audit`:** report only — list the risk findings and applicable levers with their canon sections, no edits. Use when the user wants to see what they'd change, or the prompt isn't theirs to edit.
- **`scaffold`:** the user has only an intent, not a draft. Generate a tight Fable-tuned prompt or goal-loop for that intent, then run the same interactive pass (step 3) over what you generated. Keep the scaffold lean — do not pre-load every lever; offer them.

If the user gives no draft and no intent, ask for one — nothing else.

## Step 1 — Classify the run-shape

Read the draft and decide which lever set applies. This is the single most important judgment in the skill; the levers differ sharply by shape.

- **(A) One-shot / interactive** — a person is watching; the prompt runs to a single answer or change.
- **(B) Long-running / autonomous** — a goal-loop, `/goal`, overnight or multi-hour run; nobody watching mid-task.
- **(C) Orchestrator-with-subagents** — the prompt dispatches and coordinates parallel subagents.

A prompt can be more than one (a long autonomous orchestrator is B + C). Confirm the target is Fable 5 / Mythos 5 — they share these patterns. **If the prompt targets another model, say so and stop**; this skill doesn't apply.

## Step 2 — Audit against the canon

Produce two kinds of findings. Order risk findings first.

**Risk findings** (recommend remove/rewrite — they degrade Fable 5 or raise refusal-fallback rates):

1. **Reasoning-extraction triggers** — any instruction telling the model to echo, transcribe, narrate, or "show your thinking / reasoning" as *response text*. Raises the `reasoning_extraction` refusal category and elevates fallbacks to Opus 4.8. (canon: *Recommended scaffolding changes*). Always flag as removable; suggest reading structured `thinking` blocks or a send-to-user tool instead.
2. **Over-prescriptive legacy enumeration** — long lists that name each behavior Fable 5 already handles from a brief instruction (e.g. spelled-out brevity rules, enumerated stop-cases). Recommend collapsing to the canon's short instruction. (canon: *Strong instruction following*, *Recommended scaffolding changes*).
3. **Surfaced context-budget counts** — the harness/prompt showing the model a remaining-token countdown. Recommend hiding it; if unavoidable, add the reassurance snippet. (canon: *Rare cases of context-budget concern*).

**Lever findings** — applicable canon patterns not yet present, scoped to the run-shape (table below). One finding per missing lever.

## Lever map

| Lever | Applies to | Canon section |
|---|---|---|
| Effort level | A B C | Consider all effort levels |
| Act, don't overplan | A B C (esp. ambiguous) | Longer turns by default |
| No over-engineering | A B C at higher effort | Consider all effort levels |
| Brevity / lead-with-outcome | A B C (user-facing) | Strong instruction following |
| Checkpoint discipline | A B | Strong instruction following |
| State the boundaries | A (advisory / "what do you think") | State the boundaries |
| Give the reason | A B C | Give the reason, not only the request |
| Ground progress claims | B | Ground progress claims during long runs |
| Early-stopping guard | B | Rare cases of early stopping |
| Context-budget reassurance | B (only if counts are shown) | Rare cases of context-budget concern |
| Self-verification cadence | B (long build tasks) | Recommended scaffolding changes |
| Readability addendum | B C (many tool calls) | Readability when communicating |
| Memory system | B C (recurring / cross-run) | Construct a memory system |
| Parallel subagents | C | Parallel subagents |
| Send-to-user tool | B C (async, verbatim delivery) | Create a send-to-user tool |

Insert the snippet verbatim from the cited canon section. Don't invent levers the canon doesn't support.

## Step 3 — Present interactively (AskUserQuestion)

This is the core of the skill. Modeled on `humanize`:

- **Effort first** — it's the canon's primary control. `header` = "Effort". Options, in order: **`high` (Recommended)** for most tasks · `xhigh` for the most capability-sensitive work · `medium` / `low` for routine work or a quicker, interactive feel (still strong on Fable 5). Use each option's canon description.
- Then **one question per finding**, **batched up to 4 per AskUserQuestion call**. `header` = lever / risk name (e.g. "Overplanning", "Reasoning leak", "Memory"). `question` = the reason it applies to *this* draft + the canon section.
  - **First option = the recommended action, labeled "(Recommended)"**, with `preview` = the exact snippet to insert (or, for a risk finding, the rewritten/removed text). Risk findings recommend remove/rewrite.
  - Then 1–2 genuine alternatives — a lighter variant, a different placement (system prompt vs. per-turn vs. system-reminder), or "edit the wording" — each with its own preview.
  - Always a **"Skip / keep as-is"** option last.
- **Bundle the autonomous set.** For shape B, offer early-stopping guard + ground-progress-claims + checkpoint discipline as a single "Apply the autonomous-run bundle?" question, with the three snippets combined in one preview. This keeps the interaction to ~3 rounds; reserve individual questions for levers that need a real choice.

## Step 4 — Apply

Insert the chosen snippets at the right channel for how the prompt is delivered: **system prompt** (durable behavior), **per-turn user message** (the *give-the-reason* framing), or **system-reminder** (the autonomous / early-stopping guard, which the canon writes as a reminder). Adapt only the bracketed placeholders to the user's context. When a chosen lever overlaps text already in the draft, **merge or edit it — don't stack a second copy**. File input → targeted Edits; pasted input → return the revised prompt with a short change summary citing the canon sections applied.

## Step 5 — Self-audit loop

Re-read the tuned prompt once. Ask: did I introduce a contradiction, over-prescribe (the thing the canon warns against), or re-introduce a reasoning-extraction trigger while rewording? Is it leaner than the draft, not just longer? Fix what you find. One pass.

## Hard rules

1. **Tune, never execute.** You produce a better prompt; you never carry out the prompt's underlying task.
2. **Snippets close to verbatim.** Pull from the canon and adapt only bracketed placeholders. Don't invent rules the canon doesn't state.
3. **Fewer, higher-leverage instructions.** Fable 5 degrades under over-prescription. Bias toward removing more than you add; never stack a lever onto text that already covers it.
4. **Always flag reasoning-extraction / show-your-thinking instructions as removable** — they raise refusal-fallback rates to Opus 4.8.
5. **Match placement to channel** (system prompt vs. per-turn message vs. system-reminder).
6. **Never auto-apply a risk removal.** Removed text may be load-bearing for another reason — route every change through AskUserQuestion.

## Scope limits

Only for prompts that will be run by Claude Fable 5 / Mythos 5; for other target models, say so and stop. This skill tunes *how* a prompt is framed for the model — it doesn't author the task's domain content, and it isn't an effort/latency/cost calculator.
