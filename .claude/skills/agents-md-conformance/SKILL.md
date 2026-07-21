---
name: agents-md-conformance
description: Audit whether the codebase obeys the directives declared in its CLAUDE.md, AGENTS.md, or nested context files — finds violations with file:line evidence and classifies each as auto-fixable or human-judgment. Read-only by default (--apply does doc-only fixes). Complements /basis-principles-audit (which scores whether the rules are good). Invoke for "conformance", "AGENTS.md compliance", "do we follow our own rules", or "Basis cleanup".
disable-model-invocation: true
argument-hint: "[--apply] [output-dir]"
---

# AGENTS.md Conformance Audit

Find code that violates the rules declared in CLAUDE.md / AGENTS.md / nested context files. **Read-only on source code by default.** With the optional `--apply` flag, applies a narrow allowlist of doc-only fixes (frontmatter, structural sections, broken refs) — never source code.

## What this is, what it isn't

- This skill audits **code against its own declared rules**. ("All parsers must implement `parse_email()`" — do they all?)
- The sibling [`basis-principles-audit`](../basis-principles-audit/SKILL.md) skill audits **whether the rules themselves are good**. (Is the context architecture canonical, localized, lean?)
- Run `basis-principles-audit` first if the repo has no usable CLAUDE.md — this skill needs directives to check against.
- See [`../basis-principles-audit/reference/basis-essay.md`](../basis-principles-audit/reference/basis-essay.md) for the Basis "Cleanup" pattern this skill operationalizes.

## Output directory

If `$ARGUMENTS` includes a positional output dir, use it as-is. Otherwise:

1. If `docs/specs/INDEX.md` exists → `docs/specs/YYYY-MM-DD-agents-md-conformance/`
2. Else if `docs/` exists → `docs/reviews/agents-md-conformance-YYYY-MM-DD/`
3. Else → `.agents-md-conformance-YYYY-MM-DD/` at repo root

Use today's date in ISO format. Create the directory if it doesn't exist. Never write outside of it (excluding `--apply` fixes inside the auto-fix allowlist — see `low-risk-fixes.md`).

## Arguments

- `--apply` — opt into auto-fix. Without this flag, the skill is a pure read of the codebase; with it, the skill may modify files inside the allowlist in `low-risk-fixes.md`. Default: dry-run.
- `[output-dir]` — positional, optional. Overrides the default output directory.

## Procedure

### Phase 1 — Discover context files

Glob the repo for context files agents would actually load:

- Root: `CLAUDE.md`, `AGENTS.md`, `agents.md`
- Nested: same names in every subdirectory (`src/**/CLAUDE.md`, `frontend/**/AGENTS.md`, etc.)
- Skill packages: `.claude/skills/*/SKILL.md`, `.agents/skills/*/SKILL.md`
- Adjacent rule files: `.cursorrules`, `.github/copilot-instructions.md`

Record each path + line count. Resolve symlinks (a 3-line `AGENTS.md` that points at `CLAUDE.md` is one source, not two). Note frontmatter presence/absence per file.

### Phase 2 — Extract directives

Read each discovered file. For every sentence/bullet, classify into one of three buckets using the heuristics in [`directive-extraction.md`](directive-extraction.md):

- **Operational directive** — imperative mood ("All parsers must…", "Never use…", "Raise `HTTPException` not custom error classes…"). These are what we check.
- **Description** — facts about repo layout or architecture ("`src/` contains source code", "Each bank has a parser"). Skip.
- **Reference** — pointer to another doc ("see `docs/ARCHITECTURE.md` for design decisions"). Follow once, then skip on subsequent encounters.

Rule-based extraction first (imperative-verb regex). Fall back to LLM classification only on prose that mixes registers in a single sentence. Skip any directive marked with `<!-- conformance: skip -->` on the same line (an inline HTML-comment opt-out marker).

Output a normalized list: `directive_id | source_file:line | verbatim text | scope (root / nested-path / skill-name)`.

### Phase 3 — Classify each directive by checkability

For each extracted directive, decide *how* it can be checked:

- **Grep-checkable** — pattern presence/absence in code text. ("No inline imports" → grep for non-top-level `import` in `.py`.)
- **Glob-checkable** — file structure. ("Every router lives in `src/api/routers/`" → glob mismatch.)
- **AST-checkable** — structural. ("Every parser must implement `parse_email()`" → parse `src/finance/parsers/*.py` with `ast`, look for the abstract-method override.)
- **LLM-checkable** — judgment. ("Write code that can be understood without referencing other files" — no mechanical check; sample N files and ask an LLM.)
- **Untestable** — aspirational / vague. ("Be explicit rather than clever.") Record and skip.

This classification shapes Phase 4 partitioning.

### Phase 4 — Find violations via parallel Explore subagents

Launch up to 3 `Explore` subagents **in a single message**:

- **Agent A — Grep/glob/AST directives.** Pass the list of mechanically-checkable directives. Returns a violations list with `file:line` + which directive is violated.
- **Agent B — LLM-judgment directives.** Pass the list of LLM-checkable directives + a sampling budget (e.g., 5 files per directive). Returns violations with `file:line` + which directive + a short rationale.
- **Agent C — Cross-directive consistency.** Pass the full directive list. Looks for *contradictions between directives themselves* (e.g., root says "use early returns"; a nested file says "always use the result wrapper") and *stale references* (a directive pointing at a path that no longer exists).

Set thoroughness to "very thorough." Consolidate the three lists into a single findings document in your working context.

### Phase 5 — Classify each violation: auto-fixable vs not

Apply the allowlist in [`low-risk-fixes.md`](low-risk-fixes.md). Default: report-only.

Tag each violation as one of:

- **`auto-fix-allowlisted`** — fits the strict allowlist; will be applied in Phase 6 if `--apply` is set.
- **`needs-judgment`** — doc-only fix but outside the allowlist (e.g., paraphrasing a duplicated instruction).
- **`source-code`** — violation is in source code; never auto-fixed; surfaces in recommendations.

Also assign severity per directive strength:

- **High** — uses "must" / "never" / "all"; violation is structural.
- **Medium** — uses "prefer" / "avoid"; or violation is localized.
- **Low** — uses "consider"; or violation is a one-off in test code.

Two judgment calls to make explicitly, per violation:

- **Fix the code or revise the directive?** A violation of an old directive that predates a refactor usually means the *rule* is stale, not the code. Check the directive's age (`git log -1 --format=%as -S "<directive text>"` on its source file) before assuming the code is wrong; stale-rule cases go to the Tier 2 (directive revision) table, not Tier 1.
- **Severity tracks verb strength + observed impact, not position in the file.** An aspirational line ("be explicit rather than clever") never rates High just because it sits under a "Critical Rules" heading.

### Phase 6 — Apply fixes (only if `--apply` flag is set)

For each violation tagged `auto-fix-allowlisted`:

1. Re-verify the fix is still in the allowlist (defense-in-depth — the file may have changed between Phase 5 and Phase 6).
2. Apply via `Edit` (never `Write` — preserves untouched lines).
3. Append the unified diff to a `fixes-applied.md` section of the report.

If `--apply` is not set, this phase emits a `fixes-proposed.md` section with the diffs you *would* have applied, so the user can review before re-running.

### Phase 7 — Emit deliverables

Read [`report-template.md`](report-template.md). Fill in placeholders. Write two files to the output directory:

1. `violations.md` — table of all violations, grouped by directive, with `file:line` evidence and severity.
2. `README.md` — summary, tier-ordered recommendations, fixes-applied (or fixes-proposed) section, suggested order of execution.

Print a short summary to the user:

```
Conformance audit complete.
Directives checked: N (M grep/AST, K LLM, J untestable)
Violations found: X (Y high, Z medium, W low)
Fixes applied: 0   (dry-run; re-run with --apply to action)
Report: <output-dir>/README.md

Top 3 violations to act on:
1. ...
2. ...
3. ...
```

Keep it under 15 lines.

## Constraints

- **Source code is read-only.** `src/`, `frontend/src/`, `tests/`, `scripts/` are never modified, including with `--apply`.
- **Auto-fix is opt-in via `--apply`.** Default is dry-run; users see proposed diffs before any disk write.
- **Allowlist is hard-coded in `low-risk-fixes.md`.** Do not expand it at audit time. Anything outside it goes to the recommendations section.
- **Every violation needs `file:line` evidence AND the verbatim directive it violates.** Quoting the directive shows the user the rule, not just the failure.
- **Never edit `docs/specs/INDEX.md`** without asking, even if a directive points at it.
- **Delegate heavy reading to Explore subagents** — keeps orchestration context lean and lets the skill audit large repos.

## Pre-flight checks

Before Phase 1, sanity-check:

- Is there a root `CLAUDE.md` or `AGENTS.md`? If neither exists, abort early with a message pointing the user at `/basis-principles-audit` first (no directives → nothing to conform to).
- If `--apply` is set, confirm the working tree is clean (`git status --porcelain`). If dirty, refuse to auto-fix and ask the user to commit or stash first — auto-fixes need to be reviewable as a clean diff.

## Supporting files

- [`directive-extraction.md`](directive-extraction.md) — heuristics for pulling directives out of CLAUDE.md prose
- [`low-risk-fixes.md`](low-risk-fixes.md) — explicit allowlist of auto-fixable patterns
- [`report-template.md`](report-template.md) — markdown skeleton (two delimited sub-templates)
- [`../basis-principles-audit/reference/basis-essay.md`](../basis-principles-audit/reference/basis-essay.md) — the Basis essay that originated the "Cleanup" pattern (single shared copy, kept under the sibling skill); read sections "Canon vs. Not Canon" and "The Cleanup" for grounding
