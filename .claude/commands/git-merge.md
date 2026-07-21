---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git merge-base:*), Bash(git merge-tree:*), Bash(git merge:*), Bash(git rev-parse:*), Bash(git shortlog:*), Bash(git show:*), Bash(git checkout -- :*), Bash(git merge --abort), Bash(git reset:*), Read, Grep, Glob, AskUserQuestion
description: Analyze git merge scenarios with conflict detection and interactive resolution guidance
argument-hint: <source-branch> [into <target-branch>]
---

# Git Merge Command

Analyze and execute git merges with intelligent conflict detection, risk assessment, and interactive resolution guidance.

## Context Analysis

**Current repository status:**
!`git status --porcelain`

**Current branch:**
!`git branch --show-current`

**Recent commit history:**
!`git log --oneline -5`

**Available local branches:**
!`git branch --format='%(refname:short)' | head -20`

**Available remote branches:**
!`git branch -r --format='%(refname:short)' | head -10`

**Mid-merge state check:**
!`git rev-parse -q --verify MERGE_HEAD 2>/dev/null && echo "MERGE_IN_PROGRESS" || echo "NO_MERGE_IN_PROGRESS"`

## Input Parameters

- **Source branch** (required): The branch to merge FROM
- **Target branch** (optional): The branch to merge INTO (defaults to current branch)

**Argument format:** `<source-branch>` or `<source-branch> into <target-branch>`

${ARGUMENTS ? `**User input:** ${ARGUMENTS}` : "**No arguments provided** - you must ask which branch to merge"}

## Your Task

Complete these phases in order:

---

### Phase 1: Pre-Flight Checks & Argument Parsing

#### 1.1 Parse Arguments
- If `into <target>` is specified, use `<target>` as target branch
- Otherwise, target is the current branch
- If no arguments provided, use `AskUserQuestion` to ask which branch to merge

#### 1.2 Validate Environment
Check for blocking conditions:

| Condition | Check Command | Recovery Action |
|-----------|---------------|-----------------|
| Dirty working tree | `git status --porcelain` has output | "Please commit or stash changes first" |
| Mid-merge state | MERGE_HEAD exists | "Complete or abort current merge: `git merge --abort`" |
| Source branch missing | Branch not in local or remote | List available branches |
| Target branch missing | Branch not found | List available branches |

If any check fails, stop and report the issue with recovery instructions.

#### 1.3 Verify Branches Exist
```bash
# Check local branches
git branch --list "<branch-name>"

# Check remote branches if not found locally
git branch -r --list "origin/<branch-name>"
```

If neither exists, list available branches and exit.

---

### Phase 2: Merge Analysis

#### 2.1 Find Common Ancestor
```bash
git merge-base <target-branch> <source-branch>
```

#### 2.2 Analyze Divergence
```bash
# Commits unique to source (will be merged in)
git log --oneline <target>..<source>

# Commits unique to target (since divergence)
git log --oneline <source>..<target>

# Summary of contributors
git shortlog -sn <target>..<source>
```

#### 2.3 Identify Changed Files
```bash
# Files modified in source since merge-base
git diff --name-only $(git merge-base <target> <source>)..<source>

# Files modified in target since merge-base
git diff --name-only $(git merge-base <target> <source>)..<target>

# Files modified in BOTH branches (potential conflicts)
comm -12 <(git diff --name-only $(git merge-base <target> <source>)..<source> | sort) \
         <(git diff --name-only $(git merge-base <target> <source>)..<target> | sort)
```

#### 2.4 Preview Conflicts with merge-tree (CRITICAL)
This is the key command - it simulates the merge without modifying the working tree:

```bash
git merge-tree --write-tree --no-messages <target> <source> 2>&1
```

Parse the output:
- Exit code 0 with clean tree hash = **No conflicts**
- Exit code 1 with conflict markers = **Conflicts detected**
- Look for `CONFLICT` lines in output

Alternative for older git versions:
```bash
git merge-tree $(git merge-base <target> <source>) <target> <source>
```

#### 2.5 Present Analysis Summary

Format as a clear table:

```
## Merge Analysis: <source> → <target>

| Metric | Value |
|--------|-------|
| Common ancestor | <commit-hash> (<date>) |
| Commits to merge | <count> commits from <source> |
| Target ahead by | <count> commits |
| Files changed in source | <count> |
| Files changed in target | <count> |
| Overlapping files | <count> |
| **Conflict risk** | 🟢 LOW / 🟡 MEDIUM / 🔴 HIGH |

### Files with potential conflicts:
<list of overlapping files>

### Commits to be merged:
<list of commits from source>
```

---

### Phase 3: Conflict Deep-Dive (if conflicts detected)

For each file with conflicts:

#### 3.1 Categorize Conflict Type

| Type | Description | Risk |
|------|-------------|------|
| **Overlapping edits** | Same lines changed in both branches | 🔴 HIGH |
| **Delete vs modify** | Deleted in one, modified in other | 🔴 HIGH |
| **Adjacent edits** | Changes near each other | 🟡 MEDIUM |
| **Structural** | File renamed/moved differently | 🟡 MEDIUM |
| **Formatting** | Whitespace/style only | 🟢 LOW |

#### 3.2 Show Three-Way Context
For each conflicting file, show:

```bash
# Base version (common ancestor)
git show $(git merge-base <target> <source>):<file>

# Ours (target branch version)
git show <target>:<file>

# Theirs (source branch version)
git show <source>:<file>

# Diff from base to ours
git diff $(git merge-base <target> <source>)..<target> -- <file>

# Diff from base to theirs
git diff $(git merge-base <target> <source>)..<source> -- <file>
```

#### 3.3 Interactive Resolution Guidance
For each conflicting file, use `AskUserQuestion` to understand intent:

**For overlapping edits:**
- "Both branches modified `<file>`. Should we keep the source version, target version, or combine both?"

**For delete vs modify:**
- "`<file>` was deleted in `<source>` but modified in `<target>`. Keep the file or delete it?"

**For structural conflicts:**
- "`<file>` was renamed to `<new-name>` in source. Accept this rename?"

Document the user's decisions for use during merge execution.

---

### Phase 4: Merge Execution

#### 4.1 Confirm Merge Strategy
Use `AskUserQuestion` to confirm:

```
Ready to merge <source> into <target>

Options:
1. --no-ff (Recommended) - Create merge commit even if fast-forward possible
2. --ff - Fast-forward if possible (linear history)
3. --squash - Combine all commits into one (no merge commit)
```

#### 4.2 Execute the Merge

```bash
# Recommended: preserve merge commit
git merge <source> --no-ff -m "Merge branch '<source>' into <target>"

# Or with custom message
git merge <source> --no-ff -m "<user-provided-message>"
```

#### 4.3 Handle Merge Conflicts (if they occur)

If `git merge` reports conflicts:

1. List conflicted files:
   ```bash
   git diff --name-only --diff-filter=U
   ```

2. For each conflicted file:
   - Read the file to show conflict markers
   - Guide user through resolution based on Phase 3 decisions
   - After user edits, stage the resolved file:
     ```bash
     git add <resolved-file>
     ```

3. Complete the merge:
   ```bash
   git commit -m "Merge branch '<source>' into <target>"
   ```

#### 4.4 Abort Option
If user wants to cancel at any point:
```bash
git merge --abort
```

---

### Phase 5: Post-Merge Verification

#### 5.1 Verify Merge Success
```bash
# Check for conflict markers in tracked files
git diff --check

# Show merge commit
git log -1 --stat

# Verify clean status
git status
```

#### 5.2 Check for Residual Issues
- No conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`)
- Working tree is clean
- Merge commit exists with correct parents

#### 5.3 Display Summary
```
## Merge Complete! ✓

Merged: <source> → <target>
Commit: <merge-commit-hash>
Files changed: <count>
Insertions: +<count>
Deletions: -<count>

To undo this merge:
  git reset --hard ORIG_HEAD
```

---

### Phase 6: Post-Merge Actions (Optional)

Use `AskUserQuestion` to offer next steps:

#### 6.1 Run Tests
"Would you like to run tests to verify the merge?"
- If yes, identify test command from project (e.g., `uv run pytest`, `npm test`)

#### 6.2 Push to Remote
"Would you like to push to remote?"
```bash
git push origin <target>
```

#### 6.3 Delete Source Branch
"Would you like to delete the source branch `<source>`?"
```bash
# Delete local branch
git branch -d <source>

# Delete remote branch (if applicable)
git push origin --delete <source>
```

---

## Error Recovery

| Scenario | Command | Description |
|----------|---------|-------------|
| Abort in-progress merge | `git merge --abort` | Return to pre-merge state |
| Undo completed merge | `git reset --hard ORIG_HEAD` | Discard merge commit |
| Restore deleted file | `git checkout <commit> -- <file>` | Recover from history |
| View original HEAD | `git rev-parse ORIG_HEAD` | See pre-merge commit |

---

## Example Outputs

### Clean Merge (No Conflicts)
```
## Merge Analysis: feature/api-v2 → main

| Metric | Value |
|--------|-------|
| Common ancestor | a1b2c3d (2 days ago) |
| Commits to merge | 5 commits |
| Target ahead by | 2 commits |
| Files changed | 8 |
| **Conflict risk** | 🟢 LOW |

No conflicts detected. Ready to merge.
```

### Merge with Conflicts
```
## Merge Analysis: feature/refactor → main

| Metric | Value |
|--------|-------|
| Common ancestor | x9y8z7w (5 days ago) |
| Commits to merge | 12 commits |
| Target ahead by | 8 commits |
| Overlapping files | 3 |
| **Conflict risk** | 🔴 HIGH |

### Conflicts detected in:
1. src/api/handlers.py - 🔴 Overlapping edits (lines 45-67)
2. src/models/user.py - 🟡 Adjacent changes
3. config/settings.json - 🟢 Formatting only
```

---

## Important Notes

- **NEVER use `-i` flags** (interactive modes are not supported)
- **NEVER use `--no-edit`** with rebase commands
- **Always preserve ORIG_HEAD** for recovery
- **Use merge-tree for conflict preview** - it doesn't modify the working tree
- **Document all user decisions** during conflict resolution for audit trail
