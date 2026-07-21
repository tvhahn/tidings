# Auto-Fix Allowlist

When the user passes `--apply`, only the fixes on this allowlist are applied. Everything else is reported as a recommendation. The allowlist exists to keep auto-fix uncontroversial: every entry is mechanically reversible, touches docs only, and can't change program behavior.

## Hard preconditions (all must hold for any fix to apply)

1. **Path filter.** The file being edited must match one of:
   - `CLAUDE.md` (root or nested)
   - `AGENTS.md` / `agents.md` (root or nested)
   - `docs/**/*.md` (excluding `docs/specs/INDEX.md` — never auto-edit the index)
   - `.claude/skills/**/*.md`
   - `.agents/skills/**/*.md`
   - `.agents/roles/**/*.md`

2. **Change shape filter.** The edit must be one of:
   - Add YAML frontmatter to a file that has none
   - Add a missing key to existing YAML frontmatter
   - Update a relative file reference (path-only; not link text)
   - Add a standard H2 section *header line only* (no body content)

3. **Working tree clean.** `git status --porcelain` returns empty before applying. The user can review the auto-fix as its own commit.

4. **Never auto-create new files.** Auto-fix edits existing files only. Creating a new nested `CLAUDE.md` is a design decision; the report can recommend it but Phase 6 won't do it.

If any precondition fails for a candidate fix, drop it to `needs-judgment` and surface in the recommendations section instead.

## The allowlist

### A1 — Add missing `owner:` frontmatter

**Trigger:** A canonical artifact (root `AGENTS.md` / `CLAUDE.md`, any file in `.claude/skills/*/`, any file in `.agents/skills/*/`) has no YAML frontmatter, or has frontmatter without an `owner:` key.

**Fix:**
- If no frontmatter exists, prepend:
  ```yaml
  ---
  owner: TBD
  last_reviewed: YYYY-MM-DD
  ---
  ```
- If frontmatter exists, insert `owner: TBD` alphabetically among existing keys.

**Why low-risk:** Frontmatter is metadata; no runtime tool depends on the `owner` key in this repo (verified by greppping for `owner:` in `scripts/`, `Makefile`, `.github/workflows/`). The placeholder `TBD` makes the action obvious and reviewable.

### A2 — Update broken relative file reference (single unambiguous target)

**Trigger:** A directive cites `[label](relative/path)` where `relative/path` does not resolve, AND a search for the basename returns exactly one match elsewhere in the repo.

**Fix:** Rewrite the path. Leave the link text unchanged.

**Verification before applying:**
- `find . -name '<basename>'` returns exactly 1 path (excluding `.git/`, `node_modules/`, `.venv/`, build outputs).
- The new path resolves relative to the file being edited.

**Why low-risk:** A 1-for-1 rename is mechanical. If there are 0 matches or 2+, drop to `needs-judgment` — the author has to decide.

### A3 — Add missing standard H2 header

**Trigger:** Project-wide convention is that AGENTS.md/CLAUDE.md files have specific H2 sections (e.g., `## Critical Rules`, `## File layout`), and the file lacks one that the audit's directive map shows it should have.

**Fix:** Insert the H2 header line at an appropriate position (after the file's existing H1 + intro paragraph; before the first existing H2). Body is left empty with a single `<!-- TODO: fill in -->` line.

**Why low-risk:** Adding an empty header signals structure without inventing content. The TODO comment makes the human follow-up obvious.

**Caveat:** This rule fires only if at least 50% of *peer files* in the repo already have the header. Don't impose a new convention via auto-fix.

## Explicitly NOT in the allowlist

The conformance skill will surface these as recommendations, never as auto-fixes:

- **Any change in `src/`, `frontend/src/`, `tests/`, `scripts/`, `docker/`, build configs.** Source code is sacred to this skill.
- **Rewriting directive text.** Even an obviously stale sentence in CLAUDE.md is for a human to revise — paraphrase changes meaning.
- **Removing duplicated directives.** Two directives might look identical but apply to different scopes; only a human can confirm.
- **Adding new directives.** Augmenting policy is a design decision.
- **Creating new CLAUDE.md / AGENTS.md files.** Nesting policy is a design decision.
- **Test additions.** A missing test for a directive is a recommendation, not a fix.
- **Frontmatter values other than the placeholder.** Don't guess at an owner; `TBD` is the explicit placeholder.
- **Deleting any line.** Even commented-out code or stale references — flag for human review.

## Safety review checklist (run after Phase 6, before exit)

Before reporting `--apply` as complete:

1. `git diff --stat` — confirm only files in the path filter were touched.
2. `git diff` — read every changed line; reject the whole run if anything outside the change-shape filter slipped through.
3. If anything is wrong, `git restore .` the affected files and report the failure instead of partial success.
4. Print the final unified diff in the report's `fixes-applied.md` section so the user can review it without re-running `git diff`.

The goal: a user running with `--apply` should be able to `git commit` the result without reading each file — the diff alone should be enough to trust.
