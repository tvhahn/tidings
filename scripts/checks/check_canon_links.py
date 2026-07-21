#!/usr/bin/env python3
"""Canon link checker — keeps the agent-facing context files mechanically true.

Scans the canon markdown set (root canon files, `docs/` excluding
`docs/specs/`, and every CLAUDE.md) and fails on:

1. Relative markdown links that do not resolve on disk.
2. References into the git-excluded `docs/specs/` tree that lack a
   "local-only" marker on the same line. Those paths exist only in the
   private checkout; in the public clone they dangle, so every mention
   must say so where the reader sees it. Covers markdown links, backtick
   `.md` paths, and bare backtick `docs/specs/…` directory spans.
3. Backtick path spans ending in `.md` that do not resolve (catches
   phantom filenames in prose, not just broken links).
4. A CLAUDE.md without a sibling `AGENTS.md` symlink pointing at it.
5. Intent phrasing inside canon files ("on the roadmap", "not yet
   shipped", "## Future …", "we plan to"). Canon describes today; plans
   belong in ROADMAP.md or docs/specs/. Suppress a deliberate line with
   an inline `<!-- canon: intent-ok -->` marker.
6. Skill descriptions over 60 words (.claude/skills/*/SKILL.md
   frontmatter). Every description auto-loads into every session; the
   body holds the detail.
7. Fenced directory trees inside CLAUDE.md context files. The tree is
   `ls`-discoverable, so it restates structure that drifts; keep only
   the annotated placement rules as prose bullets. Suppress a deliberate
   fence with a `<!-- canon: tree-ok -->` marker on the preceding line.

Runs against the private checkout and against the extracted public tree
(ci.yml `public-tree` job), stdlib only.

Origin: docs/specs/2026-07-11-basis-principles-audit/ (Tier 2 #3 + #5);
rules 5 and 6 graduated by docs/specs/2026-07-15-basis-principles-audit/
(G1 + G2 — repeat findings converted to automation); rule 7 graduated by
the 2026-07-16 basis-principles-audit run (G-A).

Usage: python3 scripts/checks/check_canon_links.py [--root PATH]
Exit 1 on any violation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT_CANON = ("README.md", "CLAUDE.md", "BRAND.md", "CONTRIBUTING.md", "INSTALL.md")
EXCLUDED_PARTS = {".claude", "node_modules", ".venv", "docs-site", ".git"}
LOCAL_ONLY_MARKER = re.compile(r"local[- ]only", re.IGNORECASE)
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
# Bare filenames (`GOAL.md`) are ambiguous shorthand — only path-like spans count.
BACKTICK_MD = re.compile(r"`([^`\s]*/[^`\s]*\.md)`")
# Bare directory spans into the excluded specs tree (`docs/specs/`, `docs/specs/foo/`).
BACKTICK_SPECS_DIR = re.compile(r"`(docs/specs(?:/[^`\s]*)?)`")
SKIP_TARGET = re.compile(r"^(https?:|mailto:|#)")
PLACEHOLDER = re.compile(r"[*<>{}]|YYYY")

# Rule 5: intent phrasing that does not belong in canon (case-insensitive).
INTENT_OK_MARKER = "<!-- canon: intent-ok -->"
INTENT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bon the roadmap\b",
        r"\bnot yet (shipped|implemented|built|supported)\b",
        r"\bwe plan to\b",
        r"\bnext quarter\b",
        r"\bfuture (refactor|automation|work|considerations?)\b",
        r"^#{1,6}\s.*\bfuture\b",
    )
)

# Rule 6: skill descriptions auto-load into every session — keep them lean.
MAX_SKILL_DESC_WORDS = 60

# Rule 7: fenced directory trees in CLAUDE.md restate ls-discoverable structure.
# A "tree-like" line is a path token (contains `/`) followed by a 2+ space
# column gap and annotation text — the visual shape of a `tree`/`ls` dump.
TREE_LINE = re.compile(r"^\s*\S*/\S*\s{2,}\S")
TREE_LINE_THRESHOLD = 3
TREE_OK_MARKER = "<!-- canon: tree-ok -->"


def canon_files(root: Path) -> list[Path]:
    files = [root / name for name in ROOT_CANON if (root / name).exists()]
    for path in sorted(root.glob("docs/**/*.md")):
        rel = path.relative_to(root)
        if rel.parts[:2] == ("docs", "specs"):
            continue
        files.append(path)
    for path in sorted(root.rglob("CLAUDE.md")):
        if EXCLUDED_PARTS & set(path.relative_to(root).parts):
            continue
        if path.parent != root and path not in files:
            files.append(path)
    # docs-site is EXCLUDED_PARTS (synced content copies + README stay out of
    # scope), but its own agent guide is canon and must be scanned.
    docs_site_guide = root / "docs-site" / "CLAUDE.md"
    if docs_site_guide.exists() and docs_site_guide not in files:
        files.append(docs_site_guide)
    return files


def candidates(target: str, base: Path, root: Path) -> list[Path] | None:
    """Possible absolute paths for a link/path mention, or None to skip."""
    target = target.split("#", 1)[0]
    if not target or SKIP_TARGET.match(target) or PLACEHOLDER.search(target):
        return None
    if target.startswith("/workspace/"):
        return [root / target.removeprefix("/workspace/")]
    if target.startswith("/"):
        return [root / target.lstrip("/")]
    return [(base / target).resolve(), (root / target).resolve()]


def is_local_only_specs(path: Path, root: Path) -> bool:
    """Path math only (no existence check) so it also holds in the public tree."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    return parts[:2] == ("docs", "specs") and parts[:3] != ("docs", "specs-public")


def skill_descriptions(root: Path) -> list[tuple[Path, int, str]]:
    """(skill_file, description word count, description text) per skill."""
    out: list[tuple[Path, int, str]] = []
    for path in sorted(root.glob(".claude/skills/*/SKILL.md")):
        lines = path.read_text().splitlines()
        if not lines or lines[0].strip() != "---":
            continue
        desc_parts: list[str] = []
        in_desc = False
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if in_desc and (re.match(r"^[A-Za-z_-]+:", line) or not line.strip()):
                in_desc = False
            if line.startswith("description:"):
                in_desc = True
                desc_parts.append(line.removeprefix("description:").strip())
            elif in_desc:
                desc_parts.append(line.strip())
        desc = " ".join(p for p in desc_parts if p and p not in (">-", ">", "|"))
        out.append((path, len(desc.split()), desc))
    return out


def fenced_tree_fences(lines: list[str]) -> list[int]:
    """Opening-fence line numbers (1-based) of fenced blocks that read as a
    directory tree (>= TREE_LINE_THRESHOLD tree-like lines) and are not
    suppressed by a TREE_OK_MARKER on the line immediately before the fence."""
    violations: list[int] = []
    in_fence = False
    fence_start = 0
    tree_count = 0
    suppressed = False
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start = lineno
                tree_count = 0
                prev = lines[lineno - 2] if lineno >= 2 else ""
                suppressed = TREE_OK_MARKER in prev
            else:
                if not suppressed and tree_count >= TREE_LINE_THRESHOLD:
                    violations.append(fence_start)
                in_fence = False
        elif in_fence and TREE_LINE.match(line):
            tree_count += 1
    return violations


def check(root: Path) -> list[str]:
    errors: list[str] = []
    for path in canon_files(root):
        rel = path.relative_to(root)
        lines = path.read_text().splitlines()
        for lineno, line in enumerate(lines, 1):
            targets = [(m, "link") for m in MD_LINK.findall(line)]
            targets += [(m, "path") for m in BACKTICK_MD.findall(line)]
            for target, kind in targets:
                cands = candidates(target, path.parent, root)
                if cands is None:
                    continue
                if any(is_local_only_specs(c, root) for c in cands):
                    if not LOCAL_ONLY_MARKER.search(line):
                        errors.append(
                            f"{rel}:{lineno}: {kind} into git-excluded docs/specs/ "
                            f"without a 'local-only' marker on the line: {target}"
                        )
                elif not any(c.exists() for c in cands):
                    errors.append(f"{rel}:{lineno}: broken {kind}: {target}")
            # Rule 2 (bare-dir case): `docs/specs/…` spans that name no .md file
            # resolve to the excluded tree too — same marker requirement.
            for span in BACKTICK_SPECS_DIR.findall(line):
                if span.endswith(".md") or span.startswith("docs/specs-public"):
                    continue
                if PLACEHOLDER.search(span):  # `docs/specs/YYYY-MM-DD-<name>/` is a pattern, not a path
                    continue
                if not LOCAL_ONLY_MARKER.search(line):
                    errors.append(
                        f"{rel}:{lineno}: bare reference into git-excluded docs/specs/ "
                        f"without a 'local-only' marker on the line: {span}"
                    )
            # Rule 5: intent phrasing — canon describes today, plans live elsewhere.
            if INTENT_OK_MARKER not in line:
                for pattern in INTENT_PATTERNS:
                    if pattern.search(line):
                        errors.append(
                            f"{rel}:{lineno}: intent phrasing in canon "
                            f"(move to ROADMAP.md/docs/specs/, or mark "
                            f"{INTENT_OK_MARKER}): {line.strip()[:80]}"
                        )
                        break
        # Rule 4: every CLAUDE.md has a sibling AGENTS.md -> CLAUDE.md.
        if path.name == "CLAUDE.md":
            agents = path.parent / "AGENTS.md"
            if not agents.exists():
                errors.append(f"{rel}: missing sibling AGENTS.md symlink")
            elif agents.is_symlink() and agents.readlink().name != "CLAUDE.md":
                errors.append(f"{agents.relative_to(root)}: symlink does not point at CLAUDE.md")
            # Rule 7: fenced directory trees restate ls-discoverable structure.
            errors.extend(
                f"{rel}:{fence_lineno}: fenced directory tree in a context file "
                f"— the tree is ls-discoverable; keep only annotated rules as "
                f"prose bullets (or mark the preceding line {TREE_OK_MARKER})"
                for fence_lineno in fenced_tree_fences(lines)
            )
    # Rule 6: skill descriptions are per-session context — cap the word count.
    for path, words, _ in skill_descriptions(root):
        if words > MAX_SKILL_DESC_WORDS:
            errors.append(
                f"{path.relative_to(root)}: description is {words} words "
                f"(max {MAX_SKILL_DESC_WORDS}) — descriptions load into every "
                f"session; move detail into the skill body"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    errors = check(args.root.resolve())
    if errors:
        print(f"canon link check: {len(errors)} violation(s)")
        for err in errors:
            print(f"  {err}")
        return 1
    print("canon link check: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
