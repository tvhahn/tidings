---
description: Prune and improve CLAUDE.md / AGENTS.md context files — freshness checks, default-no review, line-anchored fixes, applied on approval
argument-hint: "[path-to-context-file]"
---

# CLAUDE.md Review — Prune and Improve

You are a pragmatic senior engineer tidying the repo's agent context files. This is the **lightweight editor**: one short session, no subagents, no report files — findings shown in-conversation, fixes applied to the files after the user approves.

Scope rule: this command fixes *content* problems (stale, duplicated, unearned, misplaced lines). If you find *structural* problems — no context files at all, no canon/not-canon boundary, directives with no enforcement anywhere — recommend `/basis-principles-audit` instead of improvising architecture here.

## Rubric

Shared with `.claude/skills/basis-principles-audit/framework.md` (principles: default-no + localization). Condensed:

**The primary test is behavior, not length.** Every line in an auto-loaded file must change what an agent does. A 400-line file of dense directives beats a 150-line file of prose. Line count is a secondary signal: ~300–500 lines healthy for a root file, 800+ is a bloat flag; nested files should be brief, scoped addenda.

**Classify every line** as one of:
- **Imperative** — "use X", "never Y", "all Z must W" → earns its place if true and enforced-or-enforceable
- **Descriptive** — "`src/` contains source code", architecture prose the model can discover itself → default cut; keep only if non-obvious (the "only the non-obvious parts are recorded here" standard)
- **Reference** — pointer to a doc read on demand → cheap, keep if the target earns it

**`@path` imports force-load their target into every session.** They are not links — each one silently costs the target file's full token weight, always. Plain markdown links + a "Read on demand" section defer that cost. Flag any `@` import whose target isn't genuinely needed every session; never recommend converting plain links *to* `@` imports.

**Three destinations for a line that doesn't belong:**
1. **Move down** — subsystem-specific content goes to that subsystem's nested CLAUDE.md (create one only if the subsystem has real distinct conventions)
2. **Move out** — detail goes to `docs/` (or the file it duplicates), leaving a one-line pointer
3. **Delete** — descriptive filler, stale rules, duplicated statements

## Procedure

### 1. Discover

If `$ARGUMENTS` names a file, review that file *plus* its root/nested relatives for duplication context. Otherwise load the whole system: root `CLAUDE.md`/`AGENTS.md` and every nested one (Glob `**/CLAUDE.md`, `**/AGENTS.md`; skip `node_modules`, `.claude/worktrees`, archives). Note symlinks — a symlink and its target are one file.

If `.claude/skills/basis-principles-audit/collect-facts.sh` exists, run it (`bash <script> <repo-root>`) and use its sections 1–4 (inventory, root stats, broken links, duplicate lines) as ready-made mechanical findings. Otherwise do the checks below by hand.

### 2. Mechanical freshness checks (do these first — they anchor everything)

- **Commands exist:** every command the files mention (`make <target>`, scripts, `pnpm <script>`, CLI invocations) — verify the target/script/binary is actually defined. Stale commands are the single worst context-file failure: agents run them and trust the failure.
- **Paths resolve:** every referenced file/dir path exists. Phantom references in an Authority/layout section are worse than no section.
- **Enumerations complete:** if the file lists "the nested guides are X, Y, Z", check none are missing and none are extinct.
- **Duplication:** the same rule stated in two files, or restated within one file. Also check against README/CONTRIBUTING/Makefile — a Quick Start that duplicates documented make targets is paying twice.

### 3. Judgment pass

Per file, walk the content with the rubric: unearned descriptive prose, rules at the wrong altitude (subsystem detail in root; universal rule trapped in a nested file; a full procedure at root with only a pointer in the subsystem that owns it), vague directives ("format code properly" → name the tool and config), missing read-on-demand section, priority dilution (everything marked critical = nothing is).

### 4. Present findings

Per file, in this shape — line numbers mandatory, mechanical findings before judgment calls:

```markdown
## <path> (<N> lines)

**Freshness (mechanical):**
- L12: `make dev-docs` — target does not exist in Makefile (removed in <commit/date if cheap to find>)

**Prune / move:**
- L40–52 (descriptive): architecture prose duplicating docs/ARCHITECTURE.md → replace with one-line pointer
- L60 (wrong altitude): frontend-only rule → move to frontend/CLAUDE.md L<n>

**Sharpen:**
- L23: "format code properly" → "run `ruff format`; CI enforces `--check`"
```

Then show the **proposed diff** (before/after for each edit, or the full proposed file if the rewrite is extensive) and a one-line impact summary (lines before → after, duplications removed, stale refs fixed).

If the files are already in good shape, say so and stop — do not manufacture findings. One or two genuine improvements beat ten cosmetic ones.

### 5. Apply

Ask the user which changes to apply (default: all). Apply with `Edit` — never rewrite wholesale what only needs surgical changes. Where an edit moves content into another file (nested CLAUDE.md, a doc), make both sides of the move. Don't commit; leave that to the user or `/commit`.

## Guardrails

- Verify before flagging: confirm a command/path is really absent before calling it stale (a Makefile `include`, a script in `package.json` — check all definition sites).
- Preserve voice and formatting conventions of the file you're editing.
- Never delete a rule you merely disagree with — flag it as a question instead. Cut only what is stale, duplicated, descriptive-filler, or misplaced.
- Content moved out must land somewhere: no deletions of true-but-detailed material without a destination.
