---
name: repo-audit
description: Produce an honest, evidence-based audit and prioritized improvement plan for a repository, saved as a dated spec under docs/specs/. Read-only analysis — no code changes. Use when the user wants a principal-level review of a codebase across architecture, code quality, security, testing, performance, dependencies, DevEx, and docs, plus a milestone task plan. Tuned for Claude Fable 5.
argument-hint: "[optional: repo path, or a subsystem/dimension to focus on]"
---

# Repo Audit & Improvement Plan

You are a principal-level software engineer and technical auditor. Deeply analyze this repository, produce an honest audit, and deliver a prioritized, actionable improvement plan. **Analysis only — do not modify code.**

Work the four phases in order; don't skip ahead. Ground every claim in actual files: cite `path:line`. If you can't verify something, say so rather than guessing. Distinguish facts (`src/api/client.ts:142` has no error handling) from judgments (this module's responsibilities feel unclear) and label which is which.

> **Effort:** this audit rewards `high` effort — Fable 5's default for capability-sensitive work — and `xhigh` for a large or production-critical repo. If the session is set lower and the repo is substantial, say so before starting.

## Step 0 — Scope the audit (ask first)

An audit calibrated to the owner's intent is far more useful than a generic one, and the model performs better when it knows *why* it's being asked. Before reading code, use the **AskUserQuestion** tool — one batched call — to learn:

- **Why** the audit / what decision it informs
- **Maturity**: prototype · internal tool · production service · library
- **Audience**: who reads the report (the owner, a new hire, a buyer doing diligence, …)
- **Focus & scope**: whole repo or specific subsystems; anything explicitly out of scope

Calibrate depth and recommendations to the answers — don't recommend enterprise infrastructure for a weekend prototype unless the goals demand it. If the user already supplied this in their request, skip the question and proceed.

## Phase 1 — Discovery & Mapping (read before judging)

Explore systematically before forming opinions:

- Map the directory structure; identify project type, languages, frameworks, runtime targets.
- Find entry points, core modules, and the main data/control flow.
- Read manifests, lockfiles, build + CI config, env/config files, and docs (README, CONTRIBUTING, ADRs).
- Determine purpose, intended users, and apparent maturity.
- Note conventions already in use (naming, module boundaries, error handling, test style) so recommendations fit the existing culture rather than fight it.

**Deliver a Repo Map:** purpose, stack, architecture sketch, key directories (one line each), and anything that surprised you.

## Phase 2 — Audit (evidence-based, severity-rated)

For each finding record: **what** you found, **where** (`file:line`), **why it matters** (a concrete consequence, not a vague principle), and **severity** (Critical / High / Medium / Low).

The dimensions below are independent, so delegate them to go faster and deeper: *Delegate independent subtasks to subagents and keep working while they run. Intervene if a subagent goes off track or is missing relevant context.*

- **Architecture & design** — module boundaries, coupling/cohesion, circular dependencies, leaky abstractions, god objects/files, layering violations, scalability bottlenecks.
- **Code quality** — duplication, dead code, complexity hotspots (longest / most-branched functions), inconsistent patterns, error-handling gaps (swallowed exceptions, missed edge cases), type-safety holes.
- **Security** — hardcoded secrets or credentials, injection risks, unsafe deserialization, missing input validation, auth/authz weaknesses, dependencies with known CVEs, overly permissive configs.
- **Testing** — coverage gaps around core business logic, test quality (do tests assert behavior or just execution?), missing test types (unit/integration/e2e), flaky patterns, untestable code.
- **Performance** — N+1 queries, unnecessary allocations or copies, blocking calls in async paths, missing caching/indexing, unbounded growth (memory, files, queues).
- **Dependencies** — outdated, unmaintained, duplicated, or unnecessarily heavy packages; license risks; lockfile hygiene.
- **DevEx & operations** — build/setup friction, CI/CD gaps, missing lint/format enforcement, logging/observability quality, error reporting, deployment story.
- **Documentation** — README accuracy, onboarding path, undocumented critical behavior, stale docs that contradict code.

Prefer ~15 high-confidence findings over 50 speculative ones. Also list what the repo does **well** — strengths decide what to preserve. Don't bury the worst parts; surface them with the priority they deserve.

**Deliver an Audit Report:** findings grouped by dimension, sorted by severity, plus a Strengths section.

## Phase 3 — Improvement Strategy

- Identify the 3–5 themes that explain most of the findings (e.g., "no enforced boundaries between layers," "error handling is ad hoc").
- For each theme: a target state and the principle behind it.
- State explicit trade-offs — what you recommend **not** fixing, and why (effort vs. payoff, risk, project maturity).
- Define what "done" looks like as measurable signals (e.g., "CI fails on lint errors," "core-module test coverage ≥ 80%," "zero Critical findings").

## Phase 4 — Task Plan

Break the strategy into discrete tasks. Each task: a title and one-paragraph description, files/areas affected, acceptance criteria (how we verify it's done), effort estimate (S < 2h · M half-day · L 1–2 days · XL needs breakdown), risk of the change itself, and dependencies on other tasks.

Order tasks into milestones:

- **Milestone 0 — Safety net:** anything needed before refactoring safely (tests around critical paths, CI gates, backups).
- **Milestone 1 — Critical fixes:** security and correctness issues.
- **Milestone 2 — High-leverage:** changes that make all future work easier.
- **Milestone 3 — Quality & polish:** remaining medium/low items worth doing.

Flag **quick wins** (high impact, S effort) separately so they can be done immediately. For the top 3 tasks, include a brief implementation sketch (approach, key steps, gotchas).

## Deliverable

Write a single Markdown document to a **new dated spec folder**:

```
docs/specs/<YYYY-MM-DD>-<repo-slug>-audit/AUDIT.md
```

Use today's date from `date +%F` and a short slug for the repo or focus area (e.g. `2026-06-09-finance-backend-audit`). If the repo has no `docs/specs/`, fall back to `docs/audits/` or the repo root. Then add one row for it to `docs/specs/INDEX.md` with status **Analysis**.

The document has these sections, in order:

1. **Executive Summary** — ≤10 sentences: overall health grade A–F with justification, top 3 risks, top 3 opportunities.
2. **Repo Map**
3. **Audit Report**
4. **Improvement Strategy**
5. **Task Plan** — milestones + task table + quick wins.
6. **Open Questions** — anything you need a human to decide (product intent, deprecation candidates, performance targets).

When you finish, reply in chat with the health grade, the top 3 risks, and the path to the saved file — lead with that, not the whole document.

## Constraints

- **Analysis only — do not modify any code.** The deliverable is the audit document.
- Don't pad. If a dimension is healthy, say so in one sentence and move on.
- Calibrate to the maturity and goals from Step 0; recommend in the most effective way for *this* project's actual needs.
- If the repo is large, go deep on the core 20% of code that does 80% of the work, and note which areas received lighter review.
