---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git add:*), Bash(git commit:*), Bash(git restore --staged:*)
description: Create the project-standard git commit — emoji conventional format, changelog gate, staged-files manifest. Use at the end of any task that produced changes worth committing.
argument-hint: [scope or message hints]
---

# Git Commit

## Context

- Status: !`git status --porcelain`
- Staged: !`git diff --cached --stat`
- Unstaged: !`git diff --stat`
- Branch: !`git branch --show-current`
- Recent commits (match their tone and altitude): !`git log --oneline -5`

Hints from the caller (scope, emphasis, or a full message — may be empty): $ARGUMENTS

## Steps

If there is nothing to commit, report the clean status and stop.

### 1. Understand the change

Identify what this task changed and why. Run targeted `git diff <path>` only where
the stats above aren't enough — if you made the changes this session, you already know.

### 2. Changelog gate

Decide whether the change is user-visible per §Changelog conventions in
`docs/guides/releases.md` (UI, `/api/v1/*` contract, config keys, install path,
parser support, self-hoster docs). If yes: add or amend one `## [Unreleased]`
bullet in `CHANGELOG.md` and stage it with this commit. If no: skip — the commit
is the record.

### 3. Stage explicitly

Stage only the paths this task touched, each by name. **Never `git add -A`,
`git add .`, or `git add -u`** — this working tree is shared with other agents,
and blanket staging captures their in-flight work. Leave unrelated dirty files
alone; don't ask before staging your own changes. If the tree state contradicts
what you expect (your files missing, conflicting edits), stop and report instead
of committing.

### 4. Compose the message

```
<emoji> <type>(<scope>): <Subject>

- <body bullets: what changed and why it's the right change>

Changed files:
New: <new files, if any>
Modified: <modified files>
Deleted: <deleted files, if any>
```

Emoji↔type pairs (pick exactly one):
✨ feat · 🐛 fix · 📝 docs · ⚡ perf · 🧪 test · ♻️ refactor · 🔧 chore · 🎨 style · 🔒 security

House deviations from stock conventional commits: subject is Capitalized,
imperative, ≤72 chars, no trailing period. Body bullets carry the why, not a
file list. Keep the manifest paths repo-relative and match what you staged.

### 5. Commit

Batch the `git add` calls and the commit into a single response. Use a quoted
heredoc so the multi-line message survives the shell:

```bash
git commit -m "$(cat <<'EOF'
<message>
EOF
)"
```

Never pass `--no-verify`. Never create a branch — commit on the current branch,
`main` included (see CLAUDE.md §Committing).

If two clearly unrelated concerns are mixed in the tree, make two commits.

### 6. If the PII guard blocks the commit

A pre-commit guard scans staged **added** lines and blocks with a count-only
message. If that happens: inspect `git diff --cached` for the offending
addition, fix or unstage that file (`git restore --staged <path>`), and retry
once. If you can't identify or resolve it, stop and report — never bypass the
guard.

### 7. Verify

Confirm the commit succeeded and report the short hash and subject line.
