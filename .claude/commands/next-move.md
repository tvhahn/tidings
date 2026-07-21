---
name: next-move
description: Deep codebase analysis to identify the single most impactful addition to the project. Explores architecture, specs, frontend, API, tests, and gaps to produce one well-argued recommendation.
argument-hint: "[optional focus area, e.g. 'frontend' or 'data pipeline' or 'developer experience']"
disable-model-invocation: true
---

# Next Move — Strategic Project Analysis

You are conducting a deep, creative analysis of this project to answer one question:

> What is the single smartest, most radically innovative, and most useful addition you could make to this project right now?

**Focus area:** $ARGUMENTS

If a focus area was provided, concentrate your analysis there — but still consider the full project context, since the best move in one area may depend on gaps in another. If no focus area was provided, the scope is unrestricted: backend, frontend, data pipeline, developer experience, infrastructure, user experience, AI integration, and anything else that emerges from your exploration.

**Your job is NOT to produce a list of ideas.** Your job is to converge on ONE recommendation and argue for it with the conviction of someone who has fully internalized the codebase.

## Phase 1: Deep Exploration

Explore the codebase thoroughly before forming any opinions. Use parallel tool calls where possible.

### 1.1 Architecture and History
- Read `docs/ARCHITECTURE.md` — understand the full system
- Read `docs/specs/INDEX.md` — what has been built, what is planned, what is in draft
- Read the most recent spec in `docs/specs/` — understand the project's current frontier
- Run `git log --oneline -30` — understand recent momentum and direction

### 1.2 Frontend Surface Area
- Glob `frontend/src/pages/*.tsx` and read each page component
- Glob `frontend/src/components/*.tsx` and scan the component list
- Read `frontend/src/App.tsx` — understand navigation and routing
- Glob `frontend/src/hooks/*.ts` and `frontend/src/lib/*.ts` — understand data layer

### 1.3 Backend Surface Area
- Read each file in `src/api/routers/` — what API endpoints exist
- Read `src/finance/spending_summary.py` — the core data aggregation
- Read `src/finance/budget_service.py` — the budget system
- Read `src/finance/transaction_db.py` — what database operations are available

### 1.4 Test Coverage and Gaps
- Glob `tests/unit/test_*.py` — what is tested
- Read `docs/TESTS.md` — what the testing guide covers

### 1.5 Configuration and Infrastructure
- Read `CLAUDE.md` — project conventions and critical rules
- Glob `src/finance/config/*.json` — what configuration exists
- Glob `.claude/commands/*.md` — what automation exists
- Glob `dev/cli/*.py` — what developer tooling exists (also `dev/e2e/`, `dev/spikes/`, `dev/archive/` for fuller picture)

### 1.6 What is Missing

After exploring, explicitly list:
- Frontend pages that exist vs. obvious gaps (settings? search? data export? onboarding?)
- Backend capabilities that exist but have no frontend (query methods without API routes)
- Data that is collected but never surfaced to the user
- Patterns that are repeated manually that could be automated
- User workflows that require leaving the app (CSV export, CLI commands, etc.)

## Phase 2: Multi-Dimensional Evaluation

With the codebase fully internalized, evaluate potential additions across these dimensions. Do this thinking internally — do NOT output a scoring matrix or comparison table. The goal is to develop conviction, not to perform analysis theater.

**Dimensions to weigh:**

1. **Innovation** — Does this exist in any personal finance tool? Would it make someone say "I've never seen that before"?
2. **Strategic leverage** — Does this unlock future capabilities or compound on what is already built?
3. **User impact** — How much does this change the daily or weekly experience of using the app?
4. **Technical feasibility** — Can this be built with the existing architecture, or does it require significant new infrastructure?
5. **Novelty of the gap** — Is this something obviously missing (table stakes) or something genuinely creative?
6. **Timing** — Is this the right moment for this addition given the project's current state and recent momentum?

**Eliminate candidates that are:**
- Already in a spec (even draft status) — the user has already thought of these
- Incremental improvements to existing features — useful but not "the single smartest addition"
- Infrastructure-only (CI/CD, monitoring, logging) — important but not what this prompt is asking
- Generic suggestions that apply to any project ("add authentication", "improve error handling")

## Phase 3: The Recommendation

Present your ONE recommendation in this structure:

### Headline
A single bold sentence stating what to build. Not a category — a specific feature with a clear scope.

### The Argument (3-5 paragraphs)
Make the case. Why this, why now, why nothing else?
- What gap does it fill that no existing feature or planned spec addresses?
- What existing infrastructure does it leverage (be specific about which classes, APIs, data)?
- What makes it innovative relative to what Mint, YNAB, Copilot, and other tools do?
- What user behavior does it enable that is currently impossible or painfully manual?
- Why is this more impactful than the runner-up ideas you considered?

### How It Would Work (technical sketch)
- 3-5 bullet points describing the architecture at a high level
- Which existing files/classes it builds on
- What new files would be needed
- Rough scope estimate (small/medium/large)

### What It Unlocks
- 2-3 future capabilities that become possible once this is built
- How it compounds with the existing roadmap

### Runner-Up
Briefly (2-3 sentences) name the second-best idea you considered and why you chose the recommendation over it. This demonstrates the depth of the analysis.

## Phase 4: Next Step

End with this exact offer:

---

**Ready to build this?** I can create a detailed spec with `/spec-init <feature-name>`, or we can discuss the idea further.

---

## Guidelines

- **Do not ask the user any questions.** This command runs autonomously — explore, think, recommend.
- **Spend real effort on Phase 1.** Read files, do not skim filenames. The quality of the recommendation depends entirely on the depth of exploration.
- **Be specific, not generic.** "Add a notification system" is worthless. "Add a recurring transaction detector that flags when a subscription price changes by comparing the last 3 charges from the same company" is valuable.
- **Be opinionated.** The prompt asks for the "single smartest" addition. Hedge language like "you could consider" or "one option might be" is failure. State your recommendation with conviction and back it with evidence from the codebase.
- **Do not output Phase 2 evaluation.** The scoring is internal reasoning. Output jumps from exploration straight to the recommendation.
