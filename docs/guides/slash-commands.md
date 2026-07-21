# Slash commands

Claude Code slash commands for project maintenance — category management, insights, statement parsing, test/doc review, and feature spec workflow.

## Quick reference

| Command | Description | When to Use |
|---------|-------------|-------------|
| `/review-categories` | Analyze recent transactions for category issues and update overrides | Periodically (e.g., monthly) to catch new miscategorizations |
| `/fix-categories` | Backfill DynamoDB with overrides and audit full history | After `/review-categories` adds new overrides, or for a comprehensive audit |
| `/spending-insights` | Generate an AI spending intelligence briefing for a given month | Monthly, to review spending patterns, budget pace, and anomalies |
| `/yearly-insights` | Generate an AI-powered yearly spending review with multi-perspective analysis | Annually, to review the full year's spending trends and category deltas |
| `/review-tests` | Review test suite for gaps and improvements via testing expert panel | After adding features, to identify missing coverage or testing blind spots |
| `/review-docs` | Audit docs for drift against source code and fix discrepancies | After adding tests, parsers, dev scripts, or other structural changes |
| `/claude-md-review` | Prune and improve CLAUDE.md / AGENTS.md files — freshness checks, line-anchored fixes, applied on approval | When context files grow stale, noisy, or duplicated and you want them fixed in one short session |
| `/spec-init` | Interview-driven feature spec scaffold under `docs/specs/YYYY-MM-DD-<name>/` | At the start of a non-trivial feature, before writing any code |
| `/create-handoff` | Produce a comprehensive handoff doc for the current branch / task | When passing work to another contributor or another LLM session |
| `/parse-statement-text` | Parse `pdfplumber` text extraction output into structured transaction JSON | When auditing a new bank's statement layout via the text-extraction path |
| `/parse-statement-vision` | Parse bank statement page images into structured transaction JSON via vision | When `pdfplumber` text extraction loses formatting and a vision parse is the fallback |
| `/commit` | Generate a structured git commit with conventional emoji prefix and a staged-files manifest | After making changes you want to commit — preferred over running `git commit` manually |
| `/git-merge` | Analyze a git merge scenario with conflict detection and interactive resolution guidance | Before a non-trivial merge, to surface conflicts and risk areas |
| `/expert-panel` | Assemble a panel of 4-6 domain experts for multi-perspective analysis of a topic | When a decision benefits from structured multi-viewpoint analysis |
| `/design-review` | UI/UX expert panel that visually inspects the dashboard via Chrome DevTools | After substantive UI work, for a broad design audit grounded in the app's design system |
| `/aesthetic-critique` | Aesthetic critique of a single page or view via a design-critic panel | When you want opinionated, prioritized feedback on whether a single surface feels premium |
| `/python-script` | One-shot Python script helper using PEP-723 inline metadata (`uv run script.py`) | When you need a quick self-contained script and don't want to touch `pyproject.toml` |
| `/engineer-role` | Prime Claude as a pragmatic senior software engineer (frame only; awaits a mission) | At the start of a session when you want a senior-engineer framing without immediate action |
| `/ghost-role` | Prime Claude as "The Ghost" (Pressfield) — a spare, reader-first writing voice (frame only; awaits a question) | At the start of a writing/editing session when you want an unsparing, reader-first voice |
| `/next-move` | Strategic project analysis that proposes the single most impactful addition | When you want one well-argued recommendation for where to invest next |
| `/timesheet` | Generate a timesheet entry from git history for a given date | When billing or logging time and you want commit-grounded line items |

## Category management workflow

The two commands form a review-then-fix pipeline:

### 1. Review: identify problems

`/review-categories [months]` downloads transactions from DynamoDB and runs `dev/cli/analyze_categories.py` to find three types of issues:

- **Inconsistent** — same company assigned different categories across transactions
- **Miscellaneous** — companies stuck in the fallback category
- **Misjudged** — consistent but wrong category for a company

Obvious fixes are applied automatically to `src/finance/config/category_overrides.json`. Ambiguous cases are presented interactively for your decision. This only updates the overrides file — it does **not** modify DynamoDB, so new emails going forward will use the corrected categories.

### 2. Fix: apply retroactively

`/fix-categories` has two phases:

- **Phase A** applies all entries in `category_overrides.json` to historical DynamoDB records
- **Phase B** audits the full transaction history using parallel sub-agents to find any remaining issues not caught by the review step

Both phases present a preview before writing to DynamoDB.

### Typical cadence

1. Run `/review-categories` periodically to maintain override quality
2. Run `/fix-categories` when you want DynamoDB to reflect the latest overrides
3. You can run `/fix-categories` independently — it works with whatever overrides exist

## Spending insights

`/spending-insights [YYYY-MM]` generates an AI-powered spending intelligence briefing. It gathers structured spending context (month-over-month comparison, 6-month trend, budget targets, historical averages) via `dev/cli/gather_insights_data.py`, then Claude Code produces a narrative analysis covering key findings, category deep dives, alerts, and outlook.

Defaults to the current month if no argument is provided. Output is delivered directly in the conversation as markdown.

The dashboard offers the same analysis in-app: `POST /api/v1/insights/generate` kicks off a background task that runs a Claude CLI subprocess, polled via `GET /api/v1/insights/status` — see ARCHITECTURE.md for details.

## Yearly insights

`/yearly-insights <year>` generates an AI-powered yearly spending review for the given year. It runs `dev/cli/gather_yearly_insights_data.py` to assemble the full-year spending context, then Claude Code produces a multi-perspective analysis of annual trends, category deltas, and notable shifts.

The year argument is required. Output is delivered directly in the conversation as markdown.

## Test suite review

`/review-tests [focus area]` assembles a panel of testing experts to audit the test suite for gaps, coverage issues, and improvements. It scans the test directory structure, reads source modules, and produces structured recommendations.

If a focus area is provided (e.g., `/review-tests auth module`), the review narrows to that area. Otherwise, the entire test suite is reviewed.

## Documentation review

`/review-docs` scans source directories (test files, dev scripts, parsers, config, specs) and compares what's on disk against the documentation tables in TESTS.md, ARCHITECTURE.md, specs/INDEX.md, slash-commands.md, and CLAUDE.md.

Structural drift — missing table rows, stale entries, wrong category counts — is fixed automatically. Prose-level changes (new ARCHITECTURE.md sections, ambiguous updates) are flagged for your decision.

No arguments, no external dependencies. Run it whenever you've added tests, parsers, dev scripts, or other structural changes.

## CLAUDE.md review

`/claude-md-review` prunes and improves the repo's context files (root + nested CLAUDE.md/AGENTS.md, or a single file passed as an argument). It runs mechanical freshness checks first — do the mentioned commands still exist, do referenced paths resolve, is anything duplicated across files — then a judgment pass against the same default-no/localization rubric as `/basis-principles-audit`, and applies the approved fixes with line-anchored edits. For structural problems (no context files, no canon boundary) it defers to `/basis-principles-audit` instead.

## Feature spec scaffolding

`/spec-init <feature-name>` opens an interview that asks probing questions about the feature (purpose, audience, scope, technical approach, edge cases, tradeoffs) and writes a spec scaffold to `docs/specs/YYYY-MM-DD-<feature-name>/`. Run this before writing code for any non-trivial feature so the resulting spec lands in the [`docs/specs/INDEX.md`](../specs/INDEX.md) registry (local-only, absent in the public repo).

## Handoff documentation

`/create-handoff [task number or description]` assembles a handoff document covering current branch state, work-in-progress diff, open questions, and verification steps so another contributor or LLM session can pick up cleanly. Useful between dev container sessions and when transferring work between human and agent.

## Statement parsing (one-shot)

`/parse-statement-text` and `/parse-statement-vision` are one-shot helpers used while reverse-engineering a new bank statement layout. They consume the output of the pre-processing scripts in `scripts/` (text via `pdfplumber`, images via `pdf2image`) and produce structured JSON that can be diffed against `StatementParser` output. Once a statement layout is well-understood, the work moves into a permanent parser under `src/finance/parsers/` rather than continuing through the slash command.

## Git workflow

`/commit` analyzes the current git status, staged and unstaged diffs, and recent commit history, then assembles a conventional commit with an emoji prefix (✨ feat, 🐛 fix, 📝 docs, ⚡ perf, 🧪 test, ♻️ refactor, 🔧 chore, 🎨 style, 🔒 security) and a staged-files manifest. It can also be invoked from agents via the `Skill` tool — see CLAUDE.md's "Committing" section.

`/git-merge <source-branch> [into <target-branch>]` analyzes a prospective merge using `git merge-tree`, surfaces conflicting paths, summarizes incoming commits, and walks through resolution interactively. It does not auto-merge — risky steps are confirmed first.

For parallel checkouts, use Claude Code's built-in worktrees (`EnterWorktree` / `claude --worktree <name>`) rather than a slash command — see the "Worktrees" section in [`CLAUDE.md`](../../CLAUDE.md).

## Expert panels

`/expert-panel "<topic>"` assembles 4-6 domain experts to analyze a topic from multiple perspectives — useful for sales strategy, engineering decisions, product direction, or any question that benefits from structured multi-viewpoint reasoning. Begins with a short interview to scope the panel.

`/design-review [focus areas]` runs a UI/UX panel against the live dashboard at `http://localhost:5173` via Chrome DevTools MCP, then produces a structured review grounded in the app's actual design system. Broader than `/aesthetic-critique` — this is a UX audit, not a critique of feel.

`/aesthetic-critique <target page> [@spec.md] [focus]` is a focused aesthetic critique of a single page, view, or flow. Four design critics inspect the target across desktop, mobile, and dark mode and return prioritized, opinionated suggestions with a specific eye toward "does this feel premium, or like a demo app?"

## Other helpers

`/python-script` produces a self-contained PEP-723 Python script (single file, runnable via `uv run script.py`) — useful for quick one-offs without modifying `pyproject.toml`.

`/engineer-role` primes Claude Code as a pragmatic senior software engineer and waits for a mission. Frame only — no actions are taken until you supply the task.

`/ghost-role` primes Claude Code as "The Ghost" — Steven Pressfield's spare, reader-first writing voice from *Nobody Wants to Read Your Shit*. Frame only — it holds the persona but takes no action until you ask a writing or editing question.

`/next-move [focus area]` does a deep codebase analysis and proposes the single smartest, most useful addition you could make next. Optional focus narrows the scope (e.g., `frontend`, `developer experience`).

`/timesheet [date-info] [context]` generates a professional timesheet entry from git history for the specified date.

## Rollback

A fresh CSV backup is downloaded at the start of each command. If anything goes wrong during `/fix-categories`, restore original categories with:

```bash
uv run dev/cli/restore_categories_from_csv.py data/raw/transaction_db_rough/transactions.csv
```
