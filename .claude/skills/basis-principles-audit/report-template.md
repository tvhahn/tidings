# Report Template

This file contains two sub-templates delimited by `===== FILE: <name> =====` markers. During Phase 6, split on those markers and write each section to the output directory under the given filename.

Placeholders use `{{NAME}}` syntax — substitute every one. Leave no `{{...}}` in the final output. Sections marked *(baseline run: omit)* are dropped entirely when no prior run exists.

Corpus-mode runs (target classified as a docs-or-notes corpus in Phase 1): fill inapplicable findings subsections with a one-line `n/a (corpus mode)` — never invent code-shaped content to satisfy a placeholder.

---

===== FILE: scorecard.md =====

# Basis Principles Scorecard — {{AUDIT_DATE}}

Rubric anchors:
- **0–3**: Absent or actively contradicted. An agent gets no signal and likely does the wrong thing.
- **4–6**: Present but shallow or inconsistent. The principle isn't load-bearing in practice.
- **7–8**: Solid practice, mostly followed. The principle visibly shapes how the repo is organized.
- **9–10**: Enforced by CI / tooling / culture. Drift is mechanically detected.

Prior run: {{PRIOR_RUN_LINK_OR_NONE}} *(baseline run: "none — baseline")*

| # | Principle | Score | Δ | Evidence |
|---|-----------|:-:|:-:|----------|
| 1 | Canonicality | **{{SCORE_1}}/10** | {{DELTA_1}} | {{EVIDENCE_1}} |
| 2 | Localization | **{{SCORE_2}}/10** | {{DELTA_2}} | {{EVIDENCE_2}} |
| 3 | Verifiability | **{{SCORE_3}}/10** | {{DELTA_3}} | {{EVIDENCE_3}} |
| 4 | Interoperability | **{{SCORE_4}}/10** | {{DELTA_4}} | {{EVIDENCE_4}} |
| 5 | Default-no | **{{SCORE_5}}/10** | {{DELTA_5}} | {{EVIDENCE_5}} |

*(Δ column: change vs the prior run's score, e.g. `+2`, `=`, `−1`. Baseline run: fill with `—`.)*

---

## Overall

**Mean score: {{OVERALL_AVG}}/10** (simple mean of the five scores; prior: {{PRIOR_AVG_OR_DASH}}).

{{OVERALL_NARRATIVE}}

## What progress looks like

Re-running this scorecard after the Tier 0 / 1 recommendations in [`README.md`](README.md) should move:

{{PROGRESS_PROJECTION}}

Aggregate target: **{{TARGET_AGGREGATE}}/10**.

===== FILE: README.md =====

# Basis Principles Audit — {{REPO_NAME}}

**Date:** {{AUDIT_DATE}}
**Status:** Analysis
**Prior run:** {{PRIOR_RUN_LINK_OR_NONE}}
**Source framework:** Basis Atlas team — *Making Our Monorepo Ergonomic for Agents* (skill copy: `reference/basis-essay.md`, inside the skill package)

## Context

Basis argues that agents have to "onboard" to a codebase on every trajectory — and at scale, that turns small inconsistencies, contradictions, and gaps into compounding cost. This audit scores `{{REPO_NAME}}` against their five principles for an agent-native codebase — **canonicality, localization, verifiability, interoperability, default-no** — with file:line evidence, and proposes tiered remediation. The rubric also carries the agent-readiness dimensions (linter strictness, spec discipline, commit hygiene) folded into the relevant principles. **No fixes are applied in this document — it is recommendations only.**

## Repo shape

{{REPO_SHAPE_PARAGRAPH}}

## Method

1. Deterministic fact collection (`collect-facts.sh`): context-file inventory, symlink coverage, broken canon links, cross-file duplication, CI/hook inventory, prior-run discovery.
2. Three `Explore` subagents in parallel: (A) canonicality + localization, (B) verifiability, (C) interoperability + default-no — each returning structured findings with `file:line` citations.
3. Every citation re-verified against the working tree before scoring; unverifiable findings dropped.
4. Five principles scored 0–10 against the skill's framework (see [`scorecard.md`](scorecard.md)).
5. Recommendations drafted, then adversarially verified (already handled? evidence real? right scale? repeat finding?); survivors below, casualties in "Cut in verification."

## Delta since {{PRIOR_RUN_DATE}} *(baseline run: omit this whole section)*

### Score movement

{{SCORE_DELTA_NARRATIVE}}

### Previous Tier 0 / 1 recommendations — landed or not

| Prior rec | Status | Evidence |
|-----------|--------|----------|
{{PRIOR_RECS_ROWS}}

*(Status: `landed` / `partial` / `not landed` / `obsolete`. Evidence cites the commit, file, or absence that proves it.)*

## Scorecard summary

| Principle | Score | Δ | Headline |
|-----------|:-:|:-:|----------|
| Canonicality | {{SCORE_1}}/10 | {{DELTA_1}} | {{HEADLINE_1}} |
| Localization | {{SCORE_2}}/10 | {{DELTA_2}} | {{HEADLINE_2}} |
| Verifiability | {{SCORE_3}}/10 | {{DELTA_3}} | {{HEADLINE_3}} |
| Interoperability | {{SCORE_4}}/10 | {{DELTA_4}} | {{HEADLINE_4}} |
| Default-no | {{SCORE_5}}/10 | {{DELTA_5}} | {{HEADLINE_5}} |

Full evidence in [`scorecard.md`](scorecard.md).

## Per-principle findings

### 1. Canonicality ({{SCORE_1}}/10)

**Canon / not-canon separation:**
{{FINDINGS_1_EXISTS}}

**Canon hygiene (intent leakage, phantom refs, broken links):**
{{FINDINGS_1_HYGIENE}}

**Spec discipline (index, status taxonomy, spot-check):**
{{FINDINGS_1_SPECS}}

**Why it matters for agents:**
{{FINDINGS_1_WHY}}

### 2. Localization ({{SCORE_2}}/10)

**Nesting structure:**
{{FINDINGS_2_NESTING}}

**Rules at the wrong altitude (too high / too low / inverted):**
{{FINDINGS_2_PLACEMENT}}

**Why it matters for agents:**
{{FINDINGS_2_WHY}}

### 3. Verifiability ({{SCORE_3}}/10)

**Mechanical gates (CI + hooks + verify command):**
{{FINDINGS_3_GATES}}

**Directive-to-machinery mapping (which "must" rules have enforcers):**
{{FINDINGS_3_ENFORCEMENT}}

**Tests vs AI slop + linter strictness + commit hygiene:**
{{FINDINGS_3_TESTS}}

**Why it matters for agents:**
{{FINDINGS_3_WHY}}

### 4. Interoperability ({{SCORE_4}}/10)

**Portable primary context (+ symlink coverage):**
{{FINDINGS_4_PRIMARY}}

**Decision-table row applied and workflow evidence:**
{{FINDINGS_4_WORKFLOW}}

**Why it matters for agents:**
{{FINDINGS_4_WHY}}

### 5. Default-no ({{SCORE_5}}/10)

**Token budget (root line count, @-imports, duplication):**
{{FINDINGS_5_TOKEN_BUDGET}}

**Instruction-vs-description ratio (first 20 statements):**
{{FINDINGS_5_INSTRUCTION_QUALITY}}

**On-demand / reference pattern:**
{{FINDINGS_5_REFERENCE_PATTERN}}

**Why it matters for agents:**
{{FINDINGS_5_WHY}}

## Tiered recommendations

Ordered by **impact-per-unit-effort for advancing the five principles**. Every row is tagged with the principle(s) it advances and its scale fit (`solo` / `team` / `basis-scale`). Rows marked `[graduated]` are repeat findings converted to automation proposals per the graduation rule. All rows below survived the adversarial verification pass.

### Tier 0 — Minutes of work, order-of-magnitude impact

| # | Change | Principle(s) | Scale | Where | Why |
|---|--------|--------------|-------|-------|-----|
{{TIER_0_ROWS}}

### Tier 1 — High-leverage rewrites + structural cleanup (hours)

| # | Change | Principle(s) | Scale | Where | Why |
|---|--------|--------------|-------|-------|-----|
{{TIER_1_ROWS}}

### Tier 2 — Deeper architectural shifts (days)

| # | Change | Principle(s) | Scale | Where | Why |
|---|--------|--------------|-------|-------|-----|
{{TIER_2_ROWS}}

### Tier 3 — Basis-scale aspirational (weeks, highest ceiling)

Patterns Basis themselves describe at scale (Automatic Context scanner, sub-agent roles, owner-frontmatter CI enforcement). They pay off when agent-onboarding volume is high; over-engineered for small teams.

| # | Change | Principle(s) | Why |
|---|--------|--------------|-----|
{{TIER_3_ROWS}}

### Cut in verification

Recommendations drafted but removed by the refutation pass, with the reason — kept here so the next run doesn't re-derive them.

{{CUT_IN_VERIFICATION_LIST}}

## Infrastructure inventory (non-scored)

Continuity appendix (formerly tracked by the retired `agent-readiness-audit` scorecards): concrete verification infrastructure as found this run.

- **CI:** {{INV_CI}}
- **Linters / type checkers:** {{INV_LINTERS}}
- **Test suite:** {{INV_TESTS}}
- **Specs:** {{INV_SPECS}}
- **Commit convention:** {{INV_COMMITS}}

## Suggested order of execution

{{EXECUTION_ORDER}}

## Scope boundary

This document is recommendations only. Implementation is deliberately deferred to subsequent sessions. When implementing, prefer landing each tier as its own PR — the canonicality moves in Tier 0 don't entangle with the default-no rewrites in Tier 1, and they deserve separate review.

## Natural follow-ons

{{FOLLOW_ONS}}

===== END =====
