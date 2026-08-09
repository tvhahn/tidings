---
name: basis-principles-audit
description: Audit a codebase or notes corpus (e.g., an Obsidian vault) against the five Basis principles for agent-native architecture — canonicality, localization, verifiability, interoperability, default-no. Produces a 5-row scorecard with file:line evidence plus tiered recommendations. Read-only. Invoke for a principles read on whether a repo is agent-ready, or on mentions of the Basis essay or "agent-native codebase".
disable-model-invocation: true
argument-hint: "[output-dir]"
---

# Basis Principles Audit

> **Canonical source:** `~/dotfiles/claude/skills-optional/basis-principles-audit/` — this copy is a published snapshot (synced 2026-08-06). Make edits there and re-sync; edits made here will be overwritten.

Score a codebase 0–10 against each of the **five principles** from the Basis Atlas team's essay *Making Our Monorepo Ergonomic for Agents* (see [`reference/basis-essay.md`](reference/basis-essay.md)). Emit a scorecard and a tiered recommendations report. **This is a read-only audit.** The only writes are to the chosen output directory inside the target repo.

## The five principles

1. **Canonicality** — Every artifact is either source-of-truth about the system today, OR a record of intent / history. Never both. (Also carries the spec-discipline sub-check.)
2. **Localization** — Context lives as close to the code it governs as possible. It moves up only when genuinely shared.
3. **Verifiability** — Agents need automated verification of their work (CI, linter strictness, tests that catch AI slop, conformance hooks, commit hygiene).
4. **Interoperability** — No layer of the architecture binds the team to a single agent vendor.
5. **Default-no** — Every auto-loaded token earns its place. When the default is "include," loaded files balloon; when the default is "exclude," every line earns its place.

**Harness portability:** the procedure assumes a Claude-Code-style harness (subagents, Glob/Read tools) but degrades to any capable agent CLI — the fallbacks in Phase 0 (no bash) and Phase 2 (no `Explore`/no subagents) cover PowerShell + Copilot-CLI-style environments. GitHub Copilot CLI supports this SKILL.md format natively (Agent Skills open standard) and auto-discovers skills from `.github/skills/`, `.claude/skills/`, `~/.copilot/skills/`, and `~/.claude/skills/` — copy this directory into one of those (copy, not symlink, on Windows). Non-Claude harnesses ignore the Claude-specific frontmatter and don't substitute `$ARGUMENTS` — in that case, read "$ARGUMENTS" below as "an output dir the user explicitly stated, if any."

Full rubric, decision tables, known tradeoffs, and common failure modes in [`framework.md`](framework.md). **Always read `framework.md` before scoring** — especially its "Known tradeoffs" section, which prevents the classic mis-recommendations — and skim sections "Principles for an Agent-Native Codebase," "Canon vs. Not Canon," and "Rewriting AGENTS.md" of [`reference/basis-essay.md`](reference/basis-essay.md) for grounding.

## Sibling tools

These ship separately from this skill and may or may not be installed. **Check before naming any of them in the report** (`ls .claude/skills .claude/commands ~/.claude/skills ~/.claude/commands`); never recommend one you haven't confirmed exists.

- **`agents-md-conformance`** (skill, *if installed*) — operationalizes Basis's "Cleanup" step: checks whether the *code* obeys the directives the context files declare. Run it after this audit when directives were added or rewritten.
- **`/claude-md-review`** (command, *if installed*) — the lightweight editor: prunes and fixes a CLAUDE.md/AGENTS.md file directly in one short session, using this skill's rubric. Point default-no findings at it.
- The former **`agent-readiness-audit`** skill is merged into this one; if the repo has historical runs (typically under `docs/specs/_archive/`), they still count as prior baselines.

## Output directory

If `$ARGUMENTS` is provided, use it as-is (create it if missing). Otherwise choose a default by repo convention, in priority order:

1. If `docs/specs/INDEX.md` exists → `docs/specs/YYYY-MM-DD-basis-principles-audit/`
2. Else if `docs/` exists → `docs/reviews/basis-principles-audit-YYYY-MM-DD/`
3. Else → `.basis-principles-audit-YYYY-MM-DD/` at repo root

Exception: in a notes vault (e.g., Obsidian), a dotfolder is hidden from the app's file explorer — use a visible `basis-principles-audit-YYYY-MM-DD/` folder instead, unless the user asks for a hidden one.

Use today's date in ISO format. Create the directory if it doesn't exist. Never write outside of it.

## Procedure

### Phase 0 — Collect facts + load the prior run

Run the deterministic collector first. Invoke it by its path **relative to this skill's own directory** — the skill may be installed under the project (`.claude/skills/…`), the user home (`~/.claude/skills/…`), or a plugin, so never hardcode the project-local path:

```
bash <this-skill-dir>/collect-facts.sh <repo-root>
```

(Read-only; prints a markdown fact sheet. Running this script is always in-bounds — the read-only constraint applies to the *target repo's* code, not to the skill's own tooling.)

`<this-skill-dir>` is the directory containing the SKILL.md you are reading. If in doubt, locate `collect-facts.sh` with a `find` over `.claude/skills`, `~/.claude/skills`, and any plugin roots.

Save the script's output verbatim to `<output-dir>/fact-sheet.md`. This gives the next run a mechanical inventory to diff against, and lets you re-read facts later in the session instead of recalling them from memory.

**Windows / no-bash environments** (PowerShell, Copilot CLI on Windows): the collector is bash. Try, in order:

1. `bash <this-skill-dir>/collect-facts.sh <repo-root>` — works from PowerShell when Git for Windows is installed (Git Bash puts `bash` on PATH).
2. WSL: `wsl bash <this-skill-dir>/collect-facts.sh <repo-root>` — translate `C:\...` paths to `/mnt/c/...`.
3. No bash at all: collect the same facts yourself with the harness's file tools — reproduce every numbered fact-sheet section under the same headings, count carefully, and put `> Hand-collected (no bash available)` at the top of `fact-sheet.md`. It still serves as the inventory of record, but the label tells the next run the numbers came from agent counting, not the script.

The fact sheet is the **evidence floor**: context-file inventory, symlink coverage, broken canon links, verbatim duplication, CI/hook/verify-target inventory, spec directories, and the list of prior audit runs. Every number in your report that the fact sheet covers must come from the fact sheet — never re-derive or estimate those.

Then, from its "Prior audit runs" section, open the **most recent** prior run's `scorecard.md` and `README.md` (basis runs preferred; a legacy `agent-readiness-audit` run counts as a baseline for the infrastructure appendix). Extract:

- the previous five scores (if a basis run) and date
- the previous Tier 0 and Tier 1 recommendations, as a checklist

You will need both for the delta report in Phase 6. If no prior run exists, this is a baseline run — say so in the report and skip delta sections.

### Phase 1 — Detect repo shape and target type

A few quick Glob/Read calls: dominant languages (lockfiles, `pyproject.toml`, `Cargo.toml`, `go.mod`…), frameworks, monorepo vs single-project, count of major subsystem directories (the denominator for the localization-density check).

Classify the target as one of: **code repo**, **docs-or-notes corpus** (Obsidian vault, wiki, docs-only repo — mostly markdown, no build/test toolchain), or **mixed**. For a corpus or mixed target, apply the "Non-code corpus mode" section of `framework.md` everywhere downstream — never score a vault against CI/linter anchors. Also record whether the target is a git repo; every `git`-dependent check is conditional on that.

Record a one-paragraph "Repo shape" note including this classification — it becomes context in each Phase 2 brief.

### Phase 2 — Three parallel Explore subagents

Launch three `Explore` subagents **in a single message**. Pass each one: the repo-shape note, the relevant fact-sheet sections, and its brief below. Set thoroughness to "very thorough."

If no `Explore` agent type exists in the current harness, use general-purpose subagents; if subagents aren't available at all, work through the three briefs yourself, sequentially — briefs and output contract unchanged.

**Corpus mode:** when Phase 1 classified the target as a docs-or-notes corpus, adjust the briefs per the framework's "Non-code corpus mode" section — Agent B audits the prose-verification machinery (link checks, template/frontmatter consistency) instead of CI/linters/tests, and every `git`-dependent check applies only if the target is a git repo.

**Every brief ends with this output contract** (include it verbatim):

> Return your findings as a markdown table with exactly these columns:
> `finding | file:line | verbatim quote or config snippet | principle | severity (high/med/low)`
> One row per finding. No prose summary outside the table except a ≤5-line "gaps I could not check" note. A finding without a real file:line citation is worthless — omit it.

**Agent A — Canonicality + Localization.**
- *Canonicality:* Is there an explicit Authority Map / documentation-standards doc? Does it enumerate the actual canon files (no phantoms, no omissions — cross-check against the fact sheet's context-file table)? Do specs/plans/notes leak into canonical directories? Find intent phrasing ("we plan to," "next quarter") inside canon files. Check the spec index's status taxonomy and spot-check 2–3 statuses against code reality.
- *Localization:* Using the fact-sheet inventory, judge whether subsystem-specific rules live at the right altitude — cite rules that live too high (root file, subsystem-specific content), too low (single folder, cross-folder applicability), or inverted (full procedure at root, pointer in the subsystem).

**Agent B — Verifiability.**
- CI gates present and actually blocking? (`continue-on-error`, non-required checks — cite them.) Lint / typecheck / format-check / tests all enforced? Linter strictness vs the framework's per-language anchors.
- Directive-to-machinery mapping: pick the 3–5 strongest "must/never/all" directives from the context files and report whether each has a mechanical enforcer (test, lint rule, CI grep) — cite the enforcer or its absence.
- Test-suite spot check: assertion strength, the AI-slop trap list from the framework, coverage gate enforced in CI or not.
- Commit hygiene: convention documented where agents look + practiced in `git log --oneline -30`?

**Agent C — Interoperability + Default-no.**
- *Interoperability:* Apply the framework's decision table. Fact sheet gives symlink coverage; verify the workflow assumption (single- vs multi-tool) from repo evidence and note which decision-table row applies.
- *Default-no:* Classify the first ~20 statements of the root context file as imperative / descriptive / reference and report the ratio. Identify the worst unearned-token offenders with quotes. Check nested files for brevity and operational quality. Note `@path` imports (fact sheet counts them) and any skill descriptions that run to paragraphs.

Consolidate the three tables into one findings list in your working context.

### Phase 3 — Verify citations

Before scoring: for **every** finding you intend to use as evidence, open the cited file at the cited line yourself (Read/Grep) and confirm the quote reproduces. Drop findings that don't. This is non-negotiable — subagent citations are claims, not facts, until re-verified.

### Phase 4 — Score each principle

Apply the rubric in [`framework.md`](framework.md). For every principle:

- Assign a 0–10 score (prefer 3, 5, 7, 9 — the score is a rubric tier, not a gradient)
- Write 2–3 bullets of evidence, each citing `file:line` (verified in Phase 3) or the fact sheet
- Write a one-line headline for the scorecard summary table
- Note the delta vs the prior run's score and, in one clause, why it moved (or didn't)

Respect the decision tables and the "score the need met, not the filename present" rule.

### Phase 5 — Draft and adversarially verify recommendations

Draft the tiered recommendations (Tier 0–3, impact-per-unit-effort; every row tagged with principle(s) + scale fit per the framework). Then run the **refutation pass** on every Tier 0 and Tier 1 item — for each, answer honestly:

1. **Already handled?** Does existing machinery or a doc already cover this? (Check — don't assume.)
2. **Evidence real?** Does the underlying citation still hold after Phase 3?
3. **Worth it at this scale?** Does the scale-fit tag survive the framework's Known tradeoffs?
4. **Repeat finding?** Was this same finding (or its class) in the previous run's report?

Items failing 1–3 are cut or demoted (note them in a short "Cut in verification" list — honesty about what didn't survive). Items flagged by 4 trigger the **graduation rule**:

> **Graduation rule:** a finding reported in two consecutive runs must not be re-issued as a manual fix. Re-state it as an automation proposal — a CI check, lint rule, hook, or script that detects the whole class permanently — and mark it `[graduated]`. The audit's job is to shrink its own job.

### Phase 6 — Emit deliverables

Read [`report-template.md`](report-template.md). It contains two delimited sections — one each for `scorecard.md` and `README.md`. Fill in every placeholder. Write both files to the output directory:

1. `<output-dir>/scorecard.md` — the 5-row table **with a Δ column vs the prior run**, rubric reminder, overall mean, and "what progress looks like"
2. `<output-dir>/README.md` — full findings, the **delta section** (prior Tier 0/1 recommendations: landed / not landed, with evidence), tiered recommendations (post-refutation, graduation-tagged), the non-scored infrastructure inventory appendix, and follow-ons

For `{{FOLLOW_ONS}}`: list **only** follow-on skills and commands you have verified are installed (`ls .claude/skills .claude/commands ~/.claude/skills ~/.claude/commands`). Drop any that aren't — a report that recommends a command the reader doesn't have is worse than one that recommends nothing. "Re-run this audit after Tier 0/1 land; the next run's delta section verifies the landings mechanically" always applies and needs no check.

**Do not modify any file outside the output directory.** If the output landed under a `docs/specs/` with an `INDEX.md`, you may ask the user at the end whether to add an INDEX row — never edit it without asking.

### Phase 7 — Report back

Print a short summary to the user:

```
Basis principles audit complete.
Overall score: X.X/10  (prev: Y.Y on <date>, Δ +Z.Z)
Lowest principle: <name> (<score>/10)
Prior Tier 0/1 recs: N of M landed
Graduated to automation proposals: K findings
Report: <output-dir>/README.md

Top 3 Tier-0 recommendations:
1. ...
2. ...
3. ...
```

Keep it under 15 lines. The full analysis lives in the files.

## Constraints

- **Read-only on the target repo.** The only writes are to the output directory. No execution of the target's code — the skill's own `collect-facts.sh` is the one permitted script.
- **Fact sheet is authoritative for inventory.** Line counts, file lists, link totals, symlink coverage come from `collect-facts.sh` output, never from estimation.
- **Every citation re-verified before use** (Phase 3). Every claim in scorecard and README carries `file:line` or a fact-sheet reference.
- **Delegate heavy reading to Explore subagents**, with the output-contract table format — keeps orchestration context lean and evidence structured.
- **Scorecard structure is diffable.** Always the same 5 rows; never invent principles per repo. The Δ column and delta section are mandatory when a prior run exists.
- **Tier 0–3 ordering is impact-per-unit-effort.** Tier 0 = minutes of work, order-of-magnitude impact. Tier 3 = days+ with high ceiling. Scale-fit tags required; `basis-scale` items never in Tier 0–1.
- **Graduation rule applies** (Phase 5): repeat findings become automation proposals, not repeated advice.

## Definition of done

Before printing the Phase 7 summary, confirm every box. If one fails, go back and fix it — don't ship around it.

- [ ] Fact sheet collected via `collect-facts.sh` and saved to `<output-dir>/fact-sheet.md`
- [ ] Target classified (code / corpus / mixed) and the matching rubric anchors used
- [ ] Every citation used as evidence re-verified with your own Read/Grep (Phase 3)
- [ ] Exactly five principles scored — no extra rows, none missing
- [ ] Refutation pass run on every Tier 0/1 item; cuts recorded in "Cut in verification"
- [ ] Delta section + Δ column present, or the run explicitly marked as baseline
- [ ] No `{{...}}` placeholder left in either output file
- [ ] Follow-ons verified installed via `ls`; unverified ones dropped
- [ ] No writes outside the output directory

## Supporting files

- [`framework.md`](framework.md) — full rubric per principle with decision tables, known tradeoffs, linter anchors, and scoring discipline. **Read before scoring.**
- [`collect-facts.sh`](collect-facts.sh) — deterministic fact collector; run first, treat as evidence floor.
- [`report-template.md`](report-template.md) — the markdown skeleton filled in during Phase 6 (two delimited sub-templates).
- [`reference/basis-essay.md`](reference/basis-essay.md) — the Basis essay itself. The five principles in section "Principles for an Agent-Native Codebase" are the rubric backbone; the Authority Map in "Canon vs. Not Canon" anchors canonicality; the five authoring rules in "Rewriting AGENTS.md" anchor default-no.
