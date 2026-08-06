# Basis Principles Framework

Audit the codebase against the five principles from the Basis Atlas team's essay *Making Our Monorepo Ergonomic for Agents* (see [`reference/basis-essay.md`](reference/basis-essay.md), section "Principles for an Agent-Native Codebase"). Score each principle 0–10 using the anchors below; cite evidence with `file:line` for every claim.

The principles in order: **canonicality, localization, verifiability, interoperability, default-no.**

This framework also absorbs the agent-relevant substance of Eno Reyes' "Making Codebases Agent Ready" six dimensions (the former `agent-readiness-audit` skill): linter strictness and CI live under **verifiability**, spec discipline under **canonicality**, commit hygiene under **verifiability**. The scorecard stays at exactly five rows; the Reyes-specific detail lands in the report's non-scored infrastructure inventory appendix.

## Universal rubric

- **0–3:** Absent or actively contradicted. Agent gets no signal and likely does the wrong thing.
- **4–6:** Present but shallow or inconsistent. Agent can proceed but the principle isn't load-bearing in practice.
- **7–8:** Solid practice, mostly followed. The principle visibly shapes how the repo is organized.
- **9–10:** Enforced by CI / tooling / culture. Drift is mechanically detected; the principle is part of the contract.

**Prefer 3, 5, 7, 9 over 4, 6, 8.** The score should represent a rubric tier, not a gradient.

## Known tradeoffs — read before scoring or tiering

These are the places where naive rubric application produces wrong recommendations. Each is a real tension; resolve it per the stated rule, not by intuition.

1. **Localization density vs default-no.** More nested context files improve locality but raise aggregate token cost if each file is heavy. Rule: nested files pay their cost only when an agent enters the directory — score each nested file on its own size and operational quality, never on the aggregate. Do not recommend nesting when the nested file would just duplicate root content.
2. **Canon-marking ceremony vs payoff.** Authority Maps and `owner:` frontmatter keep canon honest at scale, but for a 1–3 person repo the boundary can live in one paragraph. Rule: an Authority paragraph is Tier 0 at any size; `owner:` frontmatter and scanners are Tier 3 unless the team has multiple contributors or ownership turnover.
3. **Default-no on a "comprehensive" root file.** Length alone is not the failure; unearned lines are. Rule: judge each line by whether it changes agent behavior. A 400-line file of dense directives beats a 150-line file of prose description.
4. **Interoperability for single-tool shops.** Don't charge a Claude-Code-only repo for a missing `AGENTS.md`. Rule: use the decision table in principle 4. The symlink is a Tier 0-opt recommendation, never a deduction, in a single-tool workflow.
5. **Verifiability ceiling for solo repos.** Conformance hooks, mutation testing, and sub-agent verifier roles are Basis-scale machinery. Rule: for a solo repo, `make verify` + strong tests + a few custom lint rules for project invariants is the 9/10 bar; reserve the heavier machinery for Tier 3 recommendations. Exception: directives that are genuinely load-bearing (a parser contract, an API shape) deserve a mechanical check even solo.
6. **Specs as canon or not-canon.** Specs are intent, therefore not canon — but a spec index with a maintained status taxonomy (`Implemented` / `Pending` / …) is itself a canonical artifact *about* the intent record. Rule: score the boundary clarity and the index's freshness, not the specs' contents.

**Scale fit is a required field.** Every recommendation you emit must carry a scale tag: `solo` (pays off for one maintainer), `team` (pays off with multiple contributors), or `basis-scale` (pays off at high agent-onboarding volume). Never put a `basis-scale` item in Tier 0–1.

## Non-code corpus mode

When Phase 1 classifies the target as a **docs-or-notes corpus** (Obsidian vault, wiki, docs-only repo), the five principles still apply but several anchors below are code-shaped. Re-anchor as follows; for a **mixed** target, apply these re-anchors to the notes portion only.

- **Canonicality** — unchanged in spirit. Canon = evergreen/reference notes, MOCs, indexes; not-canon = daily notes, drafts, clippings, meeting notes. Score the clarity of the boundary (folder convention, `status:` frontmatter) and its freshness. The spec-discipline sub-check maps to: do indexes/MOCs carry a status signal, and does it match the notes they point at?
- **Localization** — folder-level context files and index/MOC placement replace subsystem nesting: each major folder with its own conventions (templates, naming, frontmatter schema) should declare them in that folder, with the root file holding only vault-wide rules. Templates living next to the notes they govern is positive evidence.
- **Verifiability** — skip the linter-strictness anchors and the AI-slop test list entirely; they don't apply and their absence is not a deduction. The corpus 9/10 bar: mechanical prose checks exist and run — a link checker (the fact sheet's broken-link count is the floor), frontmatter/template consistency enforcement (an Obsidian Linter/Templater config, or a script), and a documented routine for running them. 7 = checks exist but run only manually/ad-hoc. 3 = nothing mechanical; broken links accumulate silently.
- **Interoperability** — portable context files apply as-is. Additionally note, lightly weighted for a personal vault: wikilinks vs standard markdown links, and plugin-dependent syntax (Dataview queries, Templater code) as lock-in signals.
- **Default-no** — applies unchanged, in full.
- **Git-dependent checks** (commit hygiene, specs-land-before-features log evidence) apply only when the target is a git repo. Otherwise mark them `n/a (corpus mode)` — no deduction.

In the report, per-principle findings subsections that don't apply get an explicit `n/a (corpus mode)` line — never invented code-shaped content. The infrastructure inventory lists what actually exists (plugins, scripts, checkers) instead of CI/linters.

---

## 1. Canonicality

> *"Every artifact in the repo is either a source of truth about the system as it is today, or a record of intent and history. It is never both."* — Basis essay

**What to look for**

*Explicit canon marking:*
- An "Authority Map" doc, documentation-standards file, or a clear convention that names which directories are canon vs not-canon
- README / context-file section that says "this is canonical" or equivalent
- `owner:` YAML frontmatter on canonical artifacts (a CI check for owner presence is the strongest signal)

*Directory naming conventions that imply canon vs not-canon:*
- Canon: root `CLAUDE.md` / `AGENTS.md`, nested context files, `docs/` (durable architecture), inline docstrings + comments
- Not canon: `docs/specs/` (intent), `.specs/`, `rfcs/`, `.notes/` (rationale), PR descriptions, issue tickets

*Canon hygiene — content that should NOT be in canon files:*
- "TODO: we plan to," "next quarter," "in progress" phrasing in files marked as source-of-truth
- Specs / RFCs / plans living in the same directory as live documentation
- Stale references to removed features, dead-link file paths (**the fact sheet's broken-link section is the mechanical floor here — cite it directly**)
- Contradictions between two canon files (only canon is supposed to be self-consistent)

*Spec discipline sub-check (absorbed from Reyes dim 5):*
- Is there a spec/RFC/ADR directory with an INDEX or README enumerating entries?
- Does the index carry a status taxonomy (`Implemented` / `Pending` / `Superseded` / …), and do spot-checked statuses match code reality?
- Do specs follow a consistent format (template, dated folders)?
- Git-log evidence: do spec commits routinely land *before* the feature commits they describe?

**Rubric anchors**
- **3/10:** No canon / not-canon distinction. Specs, plans, notes, and live docs mix freely. Agents would have no way to tell intent from current truth.
- **5/10:** Implicit separation by directory convention (e.g., `docs/specs/` exists alongside `docs/`), but no explicit Authority Map and no marking on individual files. Some canon files contain intent-phrased content, or the spec index is stale.
- **7/10:** Explicit Authority Map or documentation-standards doc. Canon and not-canon directories are clearly named and respected. Spec index carries a maintained status taxonomy. Canonical context files read as operational, not aspirational. Minor drift (a few dead links, a status or two behind reality).
- **9/10:** Above + drift is mechanically detected (a canon link-checker in CI, status-taxonomy checks) — broken refs and contradictions can't silently accumulate.

**Common failure modes**
- A `docs/` directory that mixes architecture docs (canon) with proposal docs (not canon) with no naming signal.
- A `CLAUDE.md` that contains both current rules and a "Future considerations" section — the latter erodes trust in the former.
- An Authority paragraph that enumerates files which no longer exist, or omits canon files that do (phantom references are worse than no map — the map itself has drifted).
- The team has spec discipline (`docs/specs/INDEX.md`) but statuses don't match code reality.

**Aspirational (Tier 3, `basis-scale`, recommendation-only):**
- `owner:` frontmatter on all canonical artifacts + CI check enforcing presence + Automatic-Context-style daily scanner for contradictions.

---

## 2. Localization

> *"Context should live as close to where it is used as possible. It only moves up as it becomes more generally applicable."* — Basis essay

**What to look for**

*Nesting structure:*
- Count nested `CLAUDE.md` / `AGENTS.md` files (the fact sheet's context-file table gives the inventory). Compute ratio against major subsystem directories — `src/<subsystem>/`, `frontend/`, `packages/*/`, `apps/*/`, etc.
- Are subsystem-specific rules (parser conventions, API-contract rules, frontend hook patterns, database migration rules) in the root file or in the subsystem?

*Locality signals (positive):*
- Backend context file specifies import conventions for backend code only
- Migration directory has its own rules file describing migration safety
- Frontend `CLAUDE.md` covers query / mutation patterns; backend `CLAUDE.md` does not duplicate

*De-locality signals (negative):*
- Single 1,500-line root file with sections like "Backend rules," "Frontend rules," "Migration rules" all bundled
- Subsystem-specific rule that lives only in one folder but applies to a sibling folder too (cross-folder concern that isn't promoted to a shared skill)
- A truly universal rule ("never `print()` for logging") sitting in one nested file instead of the root
- A subsystem-only *procedure* spelled out in full at root while the subsystem's own file just points up at it (inverted placement)

**Rubric anchors**
- **3/10:** Single root context file; no nesting in a multi-subsystem repo; subsystem-specific rules live in the universal file (or worse, are missing entirely).
- **5/10:** One or two nested files in obvious places (e.g., `frontend/CLAUDE.md`) but sparse coverage; several subsystems with distinct patterns lack their own files.
- **7/10:** Nested context in most subsystems that have distinct patterns; the root file holds mostly universal directives; a rule or two sits at the wrong altitude.
- **9/10:** Dense nested coverage; rules demonstrably placed at the lowest directory that fully owns them; cross-folder concerns live in skills (Layer 3 of the Basis pyramid), not duplicated in two folders' context files.

**Decision table — when nesting is NOT the fix**

| Situation | Verdict |
|---|---|
| 1-package repo, no real subsystems | No deduction for zero nested files — score the need met |
| Nested file duplicates root content | Localization *failure* — flag the duplication, don't credit the nesting |
| Workflow's agent tool doesn't auto-load nested files | The fix is workflow/interoperability, not more nesting |
| Multi-subsystem repo, subsystems have distinct conventions, no nested files | Genuine deduction + Tier 1 recommendation per missing subsystem |

**Common failure modes**
- A monorepo with `src/api/`, `src/finance/`, `frontend/` and a single root `CLAUDE.md` that tries to cover all three.
- Backend has an `AGENTS.md` describing its conventions; frontend has none and silently inherits zero rules.
- Migration safety rules live in `docs/architecture.md` (a description) rather than next to the migration files (a directive).

---

## 3. Verifiability

> *"Agents need verification of their work. We built mechanisms to enforce that, including sub-agent roles, pre-commit hooks, and tests."* — Basis essay

**What to look for**

*Mechanical verification gates:*
- CI runs lint + typecheck + format-check + tests, all **blocking** on PR merge (not just "warning"). A `continue-on-error: true` job is not a gate — cite it when found.
- Pre-commit hooks of substance — at least lint + format + typecheck for staged files, not just whitespace / file-size / PII scans
- A unified `make verify` / `just check` / equivalent that runs the full gate in one command (the fact sheet lists targets)

*Agent-specific verification:*
- Conformance hooks that check directive obedience: custom lint rules written for project invariants (e.g., `no-restricted-syntax` rules whose messages cite the context file they enforce), grep checks in CI for "must not import X," AST-based rules
- Verifier-style skills (`.claude/skills/review*`, `verify*`) — codified review procedures
- Sub-agent role files (`.agents/roles/verifier.md`, similar)
- The full-gate command surfaced in CLAUDE.md / AGENTS.md as a hard pre-completion rule

*Tests as verification (not just as coverage):*
- Assertions check specific values, not just `assert result is not None`
- Contract tests for APIs (not just shape mocks); coverage gate present and actually enforced in CI (`--cov-fail-under`, `coverageThreshold`)
- Tests for the kinds of bugs agents reliably introduce — the classic AI-slop traps:
  - `assert len(result) == N` without checking element values — swapped items pass
  - top-N lists tested by length but not order — wrong sort key passes
  - error-path tests that check only `is not None` — hallucinated output on garbled input passes
  - date handling without leap-year / DST / month-boundary cases
  - case-sensitivity round-trips absent
  - UI-heavy repo with zero component or contract tests (if backend-only, document the rationale instead of deducting)

*Linter strictness anchors (absorbed from Reyes dim 2 — judge the dominant languages):*
- **Python:** weak = ruff at defaults (`E`,`F`), no type-checker. Solid = ruff with 8+ rule sets (`B`,`UP`,`N`,`RUF`,`PT`…), pyright/mypy strict, `ruff format --check` in CI. Ceiling adds bandit / dead-code detection.
- **TypeScript:** weak = `eslint:recommended`, no `strict` tsconfig. Solid = `tseslint.configs.strict`, `strict: true` + `noUncheckedIndexedAccess`, Prettier + `tsc -b` both in CI. Ceiling adds import-cycle and a11y plugins.
- **Rust:** solid = `cargo clippy -- -D warnings` + rustfmt enforced in CI. **Go:** solid = `golangci-lint` with a broad linter set, blocking.
- The recurring failure everywhere: formatter/linter *configured* but its `--check` variant never runs in CI, so drift accumulates.

*Commit / PR hygiene sub-check (absorbed from Reyes dim 6):*
- Is the commit convention documented where an agent will find it (CONTRIBUTING.md or a block in the root context file), and does `git log --oneline -30` show it's actually practiced?
- Convention practiced but undocumented = agents must reverse-engineer it; documented but not practiced = the doc is stale. For solo repos a 3-line block in CLAUDE.md is sufficient — don't require a separate CONTRIBUTING.md.

**Rubric anchors**
- **3/10:** No CI of substance, or CI exists but doesn't block merges. Pre-commit absent or trivial. Linters at defaults. Tests exist but assertions are weak.
- **5/10:** CI gates lint + tests but not typecheck or format-check. Linters with some opinionated rules. Tests assert specific values most of the time but edge-case coverage is thin.
- **7/10:** Full gate (lint + typecheck + format + tests) blocks PRs; strict linter configs; a unified verify command; tests catch the common agent-slop patterns. Some declared directives still lack mechanical enforcement.
- **9/10:** Above + directives are converted into machinery: custom lint rules / tests / CI checks that enforce specific context-file rules and cite them. (Mutation testing, sub-agent verifier roles push past 9 — `basis-scale`.)

**Common failure modes**
- `make test` exists but no `make verify` — agents (and humans) have to guess the full verification command.
- CI lint warnings don't block merges — drift accumulates.
- The context file declares "all parsers must implement `parse_email()`" but there's no test or grep check that enforces it.
- A rule described as "non-negotiable, enforced in review" with no mechanical gate *and* a workflow that doesn't include review — the enforcement claim is fiction; cite it.

---

## 4. Interoperability

> *"No layer of the architecture binds the team to a single vendor. AI technology is moving too fast to bet on a single platform."* — Basis essay

**What to look for**

*Tool-agnostic primary context:*
- `AGENTS.md` (open standard, read by Claude Code, Cursor, Aider, Copilot Chat, Codex CLI, etc.) at the root
- OR `CLAUDE.md` with a symlink (`ln -s CLAUDE.md AGENTS.md`) so other agents find the same file — the fact sheet's sibling-coverage section reports exactly which directories are missing the symlink
- Skills / context arranged so they're useful to *any* agent that finds them, not Claude-specific only

*Tool-specific files (handle carefully):*
- `.cursorrules`, `.github/copilot-instructions.md`, `.aider*`, `.continuerc` — fine as **symlinks or thin pointers** to the canonical context
- Red flag: tool-specific files that duplicate canonical content (N copies to keep in sync)
- Red flag: only `.cursorrules` exists, with no `AGENTS.md` / `CLAUDE.md` equivalent — the current tool is locked in

*Skills + integrations:*
- Skills written in plain markdown (any agent can load them) vs skills that only work through Claude-Code-specific invocation
- MCP servers (vendor-neutral protocol) vs vendor-specific integrations
- A tool-agnostic external-consumer path (documented API auth for arbitrary agents) is strong positive evidence

**Decision table — score the need met, not the filename present**

| Workflow | Context files | Verdict |
|---|---|---|
| Single-tool (e.g., Claude Code only) | Strong `CLAUDE.md`, no `AGENTS.md` | **No deduction.** Recommend the symlink as Tier 0-opt (`solo`) |
| Single-tool | `CLAUDE.md` + `AGENTS.md` symlinks throughout | Need met and future-proofed — 9-tier evidence |
| Multi-tool | `CLAUDE.md` only | Deduct — the other tools auto-load nothing |
| Multi-tool | Canonical content duplicated across `CLAUDE.md` + `.cursorrules` | Deduct — drift risk |
| Any | Only a tool-specific file (`.cursorrules` alone) | Deduct heavily |
| Any | No context file at all | Score 0–3 |

**Windows checkouts:** with `core.symlinks=false` (the Git-for-Windows default), committed symlinks materialize as plain one-line text files containing the target path — the fact sheet will report them as real files with no `Symlink →` entry (the collector flags likely cases with "materialized symlink?"). Before flagging such a file as duplication or drift, check `git ls-files -s <path>`: mode `120000` means it's committed as a symlink; treat it as symlink-equivalent, full credit.

**Rubric anchors**
- **3/10:** Only tool-specific files exist with no portable equivalent. Switching tools means rewriting context.
- **5/10:** A primary context file exists *plus* tool-specific files that duplicate it — drift risk, but one path is portable.
- **7/10:** Single portable source (`AGENTS.md`, or `CLAUDE.md` + symlink at root); a nested directory or two missing the symlink; skills mostly vendor-neutral.
- **9/10:** Symlink coverage everywhere a context file exists, vendor-neutral skills/MCP, and a documented path for onboarding a non-default agent tool.

**Common failure modes**
- Team uses Claude Code today, but the only context file is `.cursorrules` left over from an earlier tool.
- `CLAUDE.md` and `.cursorrules` both exist with overlapping-but-different content — agents see contradictory rules depending on which tool runs.
- Symlink discipline applied at root but forgotten in nested directories (partial coverage is easy to fix — cite the exact dirs from the fact sheet).

---

## 5. Default-no

> *"Any context that is loaded automatically must be scrutinized closely. Tokens that earn no behavior are a tax on every session, paid by every agent and every engineer."* — Basis essay

**What to look for**

*Token budget on auto-loaded files (fact sheet section 2 gives the numbers):*
- Root `CLAUDE.md` / `AGENTS.md` line count. Basis's own root file is ~300 lines and "every line has been argued over." Use that as the soft ceiling.
- 300–500 lines: healthy · 500–800: starting to bloat — ask what's earning its place · 800+: bloat signal regardless of content quality
- `@path` imports in the root file: each one force-loads its target into every session. More than 1–2 is a default-no red flag — plain markdown links defer the cost; `@` imports pay it always.

*Instruction quality (the first-20-statements test):*
- Sample the first ~20 statements of the root context file. Classify each: **imperative** ("use X," "never Z," "all parsers must W") / **descriptive** ("`src/` contains source code") / **reference** ("see `docs/X.md`").
- Target: ≥70% imperative. <50% imperative is a default-no failure — the agent pays tokens to be told things it already knows.

*Reference / on-demand pattern:*
- Does the root file have a "Read on demand" / "Reference" section that defers low-priority context (fact sheet reports presence)?
- Are detailed guides in `docs/guides/` with the root file only pointing at them?
- Are skills loaded on match (small description in the skill list) rather than auto-loaded prose in the root file?

*Duplication scan (fact sheet section 4 is the mechanical floor):*
- Same rule appearing verbatim in root + nested file, or in CLAUDE.md + README
- "Quick start" sections duplicating `make` target documentation already in the Makefile
- Skill descriptions that run to paragraphs (every description loads into every session's skill list)

**Rubric anchors**
- **3/10:** Root context >2,000 lines, heavy descriptive prose, repeated sections, no on-demand pattern.
- **5/10:** Root context 800–1,500 lines. Some imperative content, but also descriptive prose and duplication. Reference section present but light.
- **7/10:** Root context 300–800 lines, mostly imperative, with a clear read-on-demand section. Nested files brief and operational. Some residue (a descriptive block, a rule stated twice).
- **9/10:** Root context lean and ruthlessly operational, ≥80% imperative; reference material deferred; near-zero duplication; every line traceable to a behavior change.

**Common failure modes**
- Root `CLAUDE.md` opens with a 100-line "Architecture overview" prose section that re-explains what the model can already see.
- "Critical rules" section is 50 bullets with no priority signal — "when you tell an agent in strongly worded terms that everything is important, it makes nothing important."
- Skill files that auto-load (no `disable-model-invocation: true`) when their content is rarely needed.
- `@path` imports used as a linking convention — every "link" silently costs the target file's full token weight per session.

---

## Infrastructure inventory (report appendix, non-scored)

The report's README carries a short non-scored appendix listing the concrete infrastructure the audit touched: CI workflows and what they gate, linter/type-checker configs and their strictness, test-suite shape and coverage gate, spec index location and status taxonomy, commit convention and where it's documented. Source it from the fact sheet plus the subagents' evidence. Its purpose is continuity — the retired `agent-readiness-audit` scorecards tracked this detail, and the appendix keeps it diffable without adding scorecard rows.

## Scoring discipline

- Every evidence bullet needs a `file:line` citation or a direct quote. "Canonicality is weak" is not evidence; "`docs/architecture.md:147` includes a 'Future plans' section that contradicts `docs/specs/2026-03-12-cache.md`" is.
- **Re-verify before you write.** Before a citation enters the scorecard, confirm it with your own Read/Grep — open the file at that line and check the quoted content is there. Subagent-reported citations that don't reproduce are dropped, not paraphrased. Numbers (line counts, file counts, link totals) come from the fact sheet, never from memory.
- Score tiers, not gradients: 3, 5, 7, 9.
- Don't penalize the absence of artifacts the workflow legitimately doesn't need (see the decision tables and Known tradeoffs above).
- When genuinely uncertain, score *lower* and record the uncertainty in the evidence bullet.
- Tag every recommendation with scale fit (`solo` / `team` / `basis-scale`) and the principle(s) it advances.

## Relationship to the sibling tools

These ship separately and may not be installed in the repo under audit — confirm each exists before recommending it in the report (see SKILL.md "Sibling tools").

- **`agents-md-conformance`** checks whether *code* obeys the directives declared in context files. Natural follow-on once this skill's Tier 0 / 1 items land — especially if any directives were added or rewritten.
- **`/claude-md-review`** (command) is the lightweight editor: a single-session prune-and-fix pass over the context files themselves, sharing this framework's default-no and localization criteria. Recommend it as the remediation tool for default-no findings; recommend this audit when someone reaches for the command but the problem is structural.
- The former **`agent-readiness-audit`** skill is absorbed into this one (linters/CI → verifiability, specs → canonicality, commit hygiene → verifiability). Historical runs live under `docs/specs/_archive/*agent-readiness-audit*` and remain valid baselines for the infrastructure appendix.

A typical loop, where those siblings are installed: run this audit → apply Tier 0/1 (context-file fixes via `/claude-md-review`, code fixes directly) → run `agents-md-conformance` to confirm code obeys the now-clean directives → re-run this audit and diff the scorecard. Without them the loop still works — the fixes are applied directly and the re-run's delta section verifies them.
