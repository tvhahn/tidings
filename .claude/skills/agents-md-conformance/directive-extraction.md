# Directive Extraction Heuristics

How to pull operational rules out of CLAUDE.md / AGENTS.md / nested-context prose during Phase 2. The goal is a normalized list of `directive_id | source_file:line | verbatim text | scope` that Phase 3 can route to checkers.

## Three buckets

Every statement in a context file is one of these:

1. **Operational directive** — tells the agent how to *act*. Use these.
2. **Description** — tells the agent how the *repo is laid out*. Skip — the agent can derive these from filesystem inspection.
3. **Reference** — pointer to another doc with directives inside it. Follow the pointer once, then skip.

The classifier is mostly mechanical (verb-pattern matching). Fall back to an LLM only when a sentence mixes registers (e.g., "Routers live in `src/api/routers/` — each module is for one resource, raise `HTTPException(status, detail)` on errors": the first clause is description, the third is a directive).

## Imperative-verb signals (rule-based; first-pass extractor)

A line is an **operational directive** if it contains one of:

- `must`, `must not`
- `never`, `always`
- `all`, `every` (followed by a noun + verb: "All parsers must implement…")
- `prefer`, `avoid`
- `use` / `do not use` / `don't use`
- `raise` / `do not raise`
- `require` / `required`
- imperative-mood opener (capitalized verb at start of line: "Read", "Write", "Edit", "Commit", "Check")

Plus heading-scoped: a line under an H2/H3 like `## Critical Rules`, `## Conventions`, `## Style`, `## Required`, `## Do not` is a directive by location even if the verb signal is weak.

## Skip patterns (rule-based; first-pass exclusion)

These are **descriptions**, not directives — skip them:

- Bare file/directory listings: `- src/api/ — FastAPI app, routers, dependencies` (descriptive prose after an em-dash is the giveaway)
- Architectural facts: "Each bank has a parser in `src/finance/parsers/`" (stating *what is*, not *what should*)
- Counts / metrics: "20 routers", "5 parsers"
- Tool-name listings: "Ruff for Python linting" (factual; the directive would be "use ruff" elsewhere)
- Anything inside a fenced code block (examples, not directives)
- Anything inside a table cell that is purely a label or path

## Reference patterns

These are **references** — follow once, then skip:

- "See [`docs/X.md`](...)"
- "Read on demand: ..."
- "Reference: [`docs/...`]"
- Bare links to other markdown files in the project

When following a reference, extract directives from the target as if it were a nested context file (same heuristics). Do not recurse more than 2 levels — directives buried 3+ docs deep are unlikely to be enforced anyway.

## Heading scope hints

Use H1/H2/H3 headings as scope hints when emitting `directive_id`:

- Heading "## Frontend Visual Verification" → directives below it scope to frontend code paths.
- Heading "## Critical Rules" → high-severity scope (these are repo-wide must-follows).
- Heading "## Dual-Backend" → scope to the dual-backend service pairs only.

Embed the scope into the `directive_id` so Phase 4 agents know where to look. Example: `dim_backend.config_service.shared_base_class_for_business_logic`.

## Dedup across nested files

A nested context file can:

- **Restate** a root directive (e.g., root says "use HTTPException", `src/api/CLAUDE.md` says it again). Treat as one directive; cite both source lines.
- **Specialize** a root directive (root says "every module owns its config", nested says "config goes in `__init__.py`"). Treat as two distinct directives; the nested one's scope is the directory.
- **Contradict** a root directive. **Always flag.** Phase 4 Agent C exists to catch this.

Heuristic for "restate vs specialize": if the nested directive's text is a strict superset of the root one's *or* uses the same imperative verb on the same object, treat as restate; otherwise specialize.

## LLM-classification fallback

Only invoke an LLM classifier when:

- The line contains both directive-signal and skip-pattern words ("Routers live in `src/api/routers/` — every router must mount at `/api/v1/`").
- The line uses passive voice obscuring agency ("HTTPException is preferred over custom exception classes").
- The line is a question or rhetorical (these are rarely directives but the rule-based extractor will sometimes flag them).

Prompt skeleton for the LLM classifier:

```
You are classifying one sentence from a project context file (CLAUDE.md
or AGENTS.md). Decide: is this an operational directive (tells the
agent how to write code) or a description (tells the agent how the
repo is laid out)?

Sentence: "{{LINE}}"
Surrounding heading: "{{HEADING}}"

Return one of: directive | description | reference | mixed
If "directive", also return:
  - verb (must/never/prefer/...)
  - object (what's being constrained)
  - scope (repo-wide / directory-scoped / file-scoped)
If "mixed", return the directive portion only.
```

Cap LLM calls at ~20 per audit. If a CLAUDE.md has so many ambiguous lines that this cap is hit, the file itself is description-heavy — surface that as a finding in Phase 7 rather than burning more tokens.

## Opt-out marker

A directive on the same line as `<!-- conformance: skip -->` is intentionally exempted from this audit (matches the `scripts/spec_status.py` opt-in marker pattern). Honor it. Examples:

- `- Prefer descriptive variable names. <!-- conformance: skip -->` — the author has decided this is subjective enough that mechanical enforcement would produce noise.
- `## Style notes <!-- conformance: skip -->` — entire section exempted (applies to all directives under this heading until the next H1/H2).

## Output shape (passed to Phase 3)

```yaml
- directive_id: critical_rules.parsers.implement_parse_email
  source_file: CLAUDE.md
  source_line: 85
  verbatim: "All parsers must implement the abstract `parse_email()` method"
  heading: "## Critical Rules"
  scope: "src/finance/parsers/"
  verb_signal: "must"
  severity_hint: high
```

`severity_hint` derives from verb_signal:
- `must` / `never` / `all` / `every` → high
- `prefer` / `avoid` / `should` → medium
- `consider` / `note that` / `prefer when` → low

This shape is what Phase 3 consumes when deciding how to check each directive.
