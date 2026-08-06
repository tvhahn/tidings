# Report Template

This file contains three sub-templates delimited by `===== FILE: <name> =====` markers. During Phase 7, split on those markers and write each section to the output directory under the given filename.

Placeholders use `{{NAME}}` syntax — substitute every one. Leave no `{{...}}` in the final output.

---

===== FILE: violations.md =====

# Conformance Violations — {{AUDIT_DATE}}

**Repo:** {{REPO_NAME}}
**Directives extracted:** {{DIRECTIVE_COUNT}} ({{GREP_COUNT}} grep/AST · {{LLM_COUNT}} LLM-judgment · {{UNTESTABLE_COUNT}} untestable)
**Violations found:** {{VIOLATION_COUNT}} ({{HIGH_COUNT}} high · {{MEDIUM_COUNT}} medium · {{LOW_COUNT}} low)

## Severity legend

- **High** — directive uses *must / never / all / every*; violation is structural.
- **Medium** — directive uses *prefer / avoid*; violation is localized.
- **Low** — directive is soft guidance; violation is a one-off or in test code.

## All violations

| # | Directive | Source | Violation | File:line | Severity | Auto-fixable? |
|---|-----------|--------|-----------|-----------|:-:|:-:|
{{VIOLATION_ROWS}}

## Grouped by directive

{{VIOLATION_GROUPS}}

Each group shows the verbatim directive (quoted from CLAUDE.md / AGENTS.md), the source line of the directive, then a sub-table of code locations where it is violated.

## Untestable directives (recorded for context)

These directives were extracted but not checked because they require subjective judgment. Listed here so the audit is honest about its coverage.

{{UNTESTABLE_LIST}}

===== FILE: README.md =====

# AGENTS.md Conformance Audit — {{REPO_NAME}}

**Date:** {{AUDIT_DATE}}
**Mode:** {{MODE}}  *(dry-run · or · --apply)*
**Source framework:** Basis Atlas team — "Making Our Monorepo Ergonomic for Agents" (see [`../reference/basis-essay.md`](../reference/basis-essay.md), section "The Cleanup")

## Context

This skill scores whether the *code* obeys the *directives* declared in CLAUDE.md / AGENTS.md / nested context files. It is complementary to `/agent-readiness-audit`, which scores whether the directives themselves are well-formed.

The auditing premise: if your context files say "all parsers must implement `parse_email()`" and one parser doesn't, then your agent will read CLAUDE.md, trust the assertion, and build code that depends on an invariant the repo doesn't actually hold. Conformance audits close that gap.

## Repo shape

{{REPO_SHAPE_PARAGRAPH}}

## Context files audited

| Path | Lines | Frontmatter? | Directives extracted |
|------|------:|:-:|---:|
{{CONTEXT_FILES_TABLE}}

## Method

1. Discovered context files via glob (`CLAUDE.md`, `AGENTS.md`, nested, `.claude/skills/`, `.agents/`).
2. Extracted operational directives from each file using the heuristics in `directive-extraction.md`.
3. Classified each directive by checkability (grep / glob / AST / LLM-judgment / untestable).
4. Three parallel `Explore` subagents searched for violations — one for mechanically-checkable directives, one for LLM-judgment directives, one for cross-directive consistency.
5. Each violation was tagged severity (high / medium / low) and auto-fixable (allowlisted / needs-judgment / source-code-never).
6. {{APPLY_OR_DRYRUN_SENTENCE}}

## Summary

| Metric | Value |
|--------|------:|
| Context files audited | {{CONTEXT_FILE_COUNT}} |
| Directives extracted | {{DIRECTIVE_COUNT}} |
| Directives checked | {{DIRECTIVE_CHECKED_COUNT}} |
| Violations found | {{VIOLATION_COUNT}} |
| — of which high severity | {{HIGH_COUNT}} |
| Auto-fixable (allowlist) | {{AUTO_FIX_COUNT}} |
| Fixes applied (this run) | {{APPLIED_COUNT}} |

## Top violations

The 5–10 violations with the largest impact on agent reliability, ordered by severity × frequency.

{{TOP_VIOLATIONS}}

Each entry quotes the directive, lists 1–3 representative `file:line` violations, and explains the agent-failure mode (what an agent might do if it trusts the directive but the code disagrees).

## Tiered recommendations

Ordered by impact-per-unit-effort, not severity alone.

### Tier 0 — Doc fixes that close violations (minutes; auto-fixable with `--apply`)

| # | Change | File | Why |
|---|--------|------|-----|
{{TIER_0_ROWS}}

### Tier 1 — Code changes to satisfy high-severity directives (hours)

| # | Change | File | Directive | Why |
|---|--------|------|-----------|-----|
{{TIER_1_ROWS}}

### Tier 2 — Directive revisions (the rule is stale, not the code)

| # | Directive to revise | Source | Reason | Suggested resolution |
|---|---------------------|--------|--------|----------------------|
{{TIER_2_ROWS}}

Some violations are real but in the *directive*, not the code — the rule was written before a refactor and no longer matches reality. Surface these so the user can decide whether to update CLAUDE.md or update the code.

### Tier 3 — Contradictions between directives (need a decision)

| # | Directive A | Directive B | Resolution needed |
|---|-------------|-------------|-------------------|
{{TIER_3_ROWS}}

Cross-directive consistency violations from Phase 4 Agent C. Each is a place where root and nested directives disagree, or two nested files disagree.

## Fixes {{APPLIED_OR_PROPOSED}}

{{FIXES_DIFF_BLOCK}}

{{FIXES_FOOTER_NOTE}}

## Suggested order of execution

{{EXECUTION_ORDER}}

## Scope boundary

This audit is read-only on source code. {{APPLY_OR_DRYRUN_SCOPE_NOTE}} Re-run with `--apply` to action the Tier 0 auto-fixable items.

After Tier 0 lands, the next high-leverage step is usually one of:
- **Updating directives that no longer match reality** (Tier 2)
- **Resolving cross-directive contradictions** (Tier 3) — these compound silently
- **Re-running the readiness/principles audit** (`/agent-readiness-audit` or `/basis-principles-audit`, whichever is installed) to confirm the now-clean directives still score well

## Related skills

List only what you have verified is installed (`ls .claude/skills .claude/commands ~/.claude/skills ~/.claude/commands`); drop the rest.

- `/agent-readiness-audit` (*if installed*) — sibling skill; scores the *quality* of the directives this audit checks against. Run it first if directives are sparse or descriptive.
- `/basis-principles-audit` (*if installed*) — absorbed `agent-readiness-audit`; use it where that skill isn't present.

===== FILE: expert-panel.md =====

# Expert Panel — AGENTS.md Conformance — {{AUDIT_DATE}}

**Question posed:** "Of the {{VIOLATION_COUNT}} violations found, which ones actually matter for agent reliability, and which are nits we should de-prioritize or ignore?"

**Input given to the panel:** the violations table in [`violations.md`](violations.md), the tier-ordered recommendations in [`README.md`](README.md), and the top-violations summary.

---

## The panel

{{PANEL_COMPOSITION}}

The panel composition mirrors the one in `/agent-readiness-audit/expert-panel-brief.md` for consistency across audits. Roles:

1. **Priya Okafor** — agent-platform staff engineer. Asks "which of these would a real agent trip over today?"
2. **Marcus Tremblay** — senior QA. Skeptical of severity assignments; wants reproducible failure cases.
3. **Dev Srinivasan** — DevEx lead. Pragmatic about which fixes are worth the contributor friction.
4. **Lin Watanabe** — technical writer / IA. Asks "is this a code violation or a directive that should be revised?"
5. **Casey Rourke** — API contract specialist. Tracks contract-shaped directives specifically.

---

{{PANEL_ANALYSIS}}

Each panelist's section follows this shape (~200 words):

```
## <Name> — "<one-line framing>"

> "<direct quote in their voice>"

<one to two paragraphs of analysis citing specific violations from the table>

> "<optional second quote — only if it adds a distinct point>"

**Most urgent, per <name>:** <their single highest-ROI violation to fix>
**Their pushback:** <what common move they disagree with — the panel gets texture from disagreement>
```

---

## Where the panel converges

{{PANEL_CONVERGENCE}}

3–6 bullets of agreed priorities. Always include the highest-severity violation if it survives panel scrutiny.

## Where the panel diverges

{{PANEL_DIVERGENCE}}

Surface real disagreements. Don't manufacture them, but don't whitewash either — a unanimous panel signals a weak prompt.

Likely tension points for a conformance audit:
1. **Whether to fix the code or revise the directive** — Lin will frequently argue the directive is stale; Priya will argue the directive captures real intent. Resolution depends on age + author of the directive.
2. **Severity inflation** — Marcus may push back on "high" labels for directives that are aspirational ("be explicit rather than clever"). Severity should track verb-strength + observed impact, not directive position in the file.
3. **Auto-fix scope** — Dev will argue for a wider allowlist (e.g., paraphrasing duplicated directives); the framework explicitly resists this. Surface the disagreement so the user can see the tradeoff.

## Rough consensus on a first-PR scope

{{PANEL_CONSENSUS_SCOPE}}

A concrete ordered list of 5–8 violations to address in a single first PR. Should map cleanly to Tier 0/1 entries in the README.

## Panel's closing remark

{{PANEL_CLOSING}}

One paragraph. Usually about how conformance gaps compound: each "small" stale directive becomes a confidently-wrong agent trajectory.

===== END =====
