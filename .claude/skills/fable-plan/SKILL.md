---
name: fable-plan
description: Author an execution-grade implementation plan for a feature or fix,
  saved as a dated spec under docs/specs/, detailed enough that Opus agents can
  execute it end-to-end without Fable in the loop. Invoke when the user starts
  with /fable-plan, asks for a "fable plan", or wants a task planned for later
  Opus execution rather than built now.
argument-hint: <task to plan> [--dir <output-dir>]
---

# Fable plan — execution-grade spec authoring

You are the **planner**, not the builder. The task statement is everything that
followed the invocation:

> $ARGUMENTS Your output is a spec folder another model executes verbatim,
possibly weeks from now, with **zero access to your reasoning** — so every
judgment call you make while researching must end up written down. The division
of labor: the hard part is *thinking* (architecture, sequencing, ambiguity
resolution); execution should be left mostly mechanical.

Precedent plans (read one before your first plan; match their density):
`docs/specs/2026-07-02-timezone-history-migration/` (single-agent),
`docs/specs/2026-07-05-event-clustering/` (orchestrated). The format contract
lives in `docs/specs/2026-07-01-fable-plan-queue/README.md` § "Plan format".

## Step 1 — Scope and prior art

- Output location: `docs/specs/$(date +%Y-%m-%d)-<slug>/` (run `date`; never
  hardcode). If the invocation names a different directory, use that instead.
- Check `docs/specs/INDEX.md` and `docs/specs/2026-07-01-fable-plan-queue/README.md`
  for prior specs or queue items covering this task — a plan often supersedes an
  older analysis doc; say so in the README and link it.
- Read the relevant `CLAUDE.md` files (`src/finance/CLAUDE.md`,
  `frontend/CLAUDE.md`) before planning work in those trees.

## Step 2 — Research until nothing is ambiguous

Read the actual code — every module the change touches, every consumer of the
data it alters. Depth here is the whole point; skimming produces plans that
Opus has to re-derive, which defeats the skill.

- **Anchors from the live tree only.** Every `file:line` reference in the plan
  must come from a Read/Grep you ran this session — never from memory or an
  older spec (specs go stale; the tree is truth).
- **Build the consumer map.** For any data shape, key, or contract the plan
  changes, enumerate *everything* that reads or writes it (side stores, pointer
  fields, caches, journal files, fixtures, e2e specs). Missed consumers are the
  #1 way executed plans corrupt data.
- **Find the traps.** Identify the plausible-but-wrong implementation an
  executor would naturally reach for, and write down why it's wrong (the
  timezone plan's "bucketing trap" section is the model).
- **Resolve every fork.** Each design decision gets analyzed and **locked** as
  `L1, L2, …` with a one-paragraph rationale. Technical forks you resolve
  yourself using the codebase's own conventions. Use `AskUserQuestion` only for
  genuinely product-owned forks (scope, user-visible behavior, data-loss
  tradeoffs) — never for anything the code can answer.

## Step 3 — Write the deliverables

### `README.md` — the *why* and the *what*

Header: title, `**Status:** Not Implemented (Fable-authored; build-ready)`,
`**Date:**`, links to parent spec / queue item if any. Then:

- **Context** — what exists today (with anchors), what's broken or missing,
  why now. Concrete failure narratives beat abstract motivation: show the
  corruption/bug/gap with real field values.
- **Why this is subtle** — the traps section. Only if there are traps; don't
  manufacture drama.
- **Locked decisions** — `L1…Ln`, each with rationale. Include an explicit
  **deferred / do-not-build list** as its own locked decision so scope can't
  creep during execution.
- **Contracts** — API shapes, schemas, key formats, algorithm constants. If an
  algorithm matters, spell it out verbatim (named constants, formulas) and lock
  it — "reasonable clustering" is not a spec.
- **Verification** — how a human confirms the finished work end-to-end.

### `IMPLEMENTATION_PLAN.md` — the *how*

Open with the standing instructions: execute phases in order, gates must pass
before advancing, decisions in README are final ("do not re-derive them"), all
Python via `uv run`.

- **Phase 0 — re-validate anchors.** A checkbox list of every load-bearing
  anchor the plan rests on, one line each with what should be found there.
  Gate: every box checked against the live tree. Include the drift protocol:
  if an anchor moved, update the plan file in place and note the drift in the
  commit body. (Plans are executed later; this phase is what makes staleness
  survivable.)
- **Phases 1…n**, each with:
  - Concrete deliverables: file paths to create/modify, function signatures,
    dataclass fields, SQL statements, endpoint shapes. Include short code
    snippets **only** where prose would be ambiguous (a hash recipe, a
    `ConditionExpression`, a regex) — not for code Opus can write from a clear
    sentence.
  - **Enumerated tests** — name the test module and list the cases, including
    the edge cases your research surfaced (boundaries, DST, collisions,
    resume-after-crash). "Add tests" is not a plan line.
  - Repo rules restated inline where they bite (dual-backend edit discipline,
    `queries.*` factories, brand voice for user-facing strings) — don't assume
    the executor read every CLAUDE.md section.
  - A **gate**: literal commands with expected outcome
    (`uv run pytest tests/unit/test_x.py -v` green; `ruff` + `pyright` clean).
- Final phase: docs updates (guides, ARCHITECTURE.md, CHANGELOG if
  user-visible, `docs/specs/INDEX.md` status flip) and `make verify` green.
- Sequencing rule: pure logic before I/O before CLI/UI — early phases should be
  exhaustively unit-testable without infrastructure.
- If anything at plan-time is unknowable until build time (e.g. the next free
  migration number), say exactly how Phase 0 resolves it rather than guessing.

### `GOAL.md` — the runnable prompt

One bare paragraph, no fences, no commentary — the exact text pasted to a
fresh agent. Name the spec directory, the read order (README → plan →
relevant CLAUDE.md), the phase sequence with one clause per phase, and the
standing rules: decisions are final, gates before advancing, `uv run` only,
commit per phase via `/commit`, finish with `make verify` green. Model:
`docs/specs/2026-07-02-timezone-history-migration/GOAL.md`.

### `ORCHESTRATE.md` — only when it pays

Write it only if the work splits into ~3+ packets with **disjoint file
ownership** that can genuinely run in parallel. Model:
`docs/specs/2026-07-05-event-clustering/ORCHESTRATE.md`. Must include: worktree
isolation (mandatory — this repo runs multiple agents against one shared
index), a work-packet table with exclusive file ownership, orchestrator-run
gates (subagent claims are never trusted), ≤2 `SendMessage` feedback rounds per
packet before the orchestrator fixes residuals itself, self-contained briefs
(packet ID, read list, locked decisions by name, traps, deliverable contract,
no commits by subagents), and stop clauses. Single-agent work: skip this file;
`GOAL.md` is enough.

## Step 4 — Register and stop

- Add a row to the top table of `docs/specs/INDEX.md`: status `Not Implemented`,
  summary column carrying the load-bearing locked decisions, second column
  noting "build-ready Fable plan" and the file inventory.
- If the task came off the fable-plan-queue, annotate that queue entry
  (`← planned <date>; see <folder>/`).
- **Do not commit** the plan: `docs/specs/` is local-only via
  `.git/info/exclude`. (If the user pointed output at a tracked location,
  offer `/commit` instead.)
- **Do not start implementing.** The deliverable is the plan. End by telling
  the user the folder path, the locked-decision count, and the one-line launch
  instruction (paste `GOAL.md` to an Opus agent, or run `ORCHESTRATE.md` if
  written).

## Quality bar — self-check before finishing

Reject your own draft if any of these fail:

1. Could Opus start Phase 1 without asking a single question? Every "it
   depends" must already be an `Ln`.
2. Is every anchor from this session's reads, and is each one in the Phase 0
   checklist?
3. Does each phase end in a gate an agent can mechanically evaluate?
4. Are the tests enumerated case-by-case, edge cases included?
5. Is there an explicit do-not-build list?
6. Would a plausible-but-wrong implementation slip through? If you can name
   one, the traps section must kill it.
