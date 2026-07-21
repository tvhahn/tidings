# Releases

How to cut a new release of Tidings. This guide is the source of truth for versioning policy, branching, and the step-by-step release ritual. Single-maintainer reality: keep it simple, ship when there's something worth shipping, don't promise a calendar.

## Versioning policy

The project follows [Semantic Versioning 2.0](https://semver.org/spec/v2.0.0.html) with the standard pre-1.0 relaxation already documented in [`CHANGELOG.md`](../../CHANGELOG.md):

| Bump | When |
|------|------|
| `0.1.0 → 0.1.1` (patch) | Bug fixes, doc-only changes, small parser tweaks, dependency bumps without behavior change |
| `0.1.0 → 0.2.0` (minor) | New features, new bank parsers, breaking config or schema changes (allowed pre-1.0) |
| `0.x → 1.0.0` (major) | Public API + on-disk schema are stable enough to commit to not breaking for ~12 months |

Pre-1.0 callout: minor bumps **may** introduce breaking changes — that is the SemVer escape hatch for projects under active shape-finding. Document the break in the CHANGELOG `### Changed` or `### Removed` section so self-hosters reading the release notes know to read more carefully before upgrading.

### When to cut 1.0

Don't rush it. A reasonable bar:

- The `/api/v1/*` surface has been stable for ~3 months without a breaking change.
- The SQLite schema has been stable, or the migration runner has handled at least one real migration in the wild without issues.
- `data/config.json` keys haven't been renamed/removed in the same window (the canonical key list is [`configuration.md`](configuration.md)).
- You've gotten enough community feedback (issues, PRs, Discussions) that the rough edges are known, not hypothetical.

## Branching model

**Trunk-based development on `main`.** No release branches, no GitFlow.

- `main` is always releasable. The `make verify` gate is what enforces this.
- Feature work happens on short-lived branches → PR → squash-merge to `main`.
- A release is just a tagged commit on `main`. Nothing more.

Skip release branches until you're maintaining an old version while shipping a new one in parallel — you are nowhere near that. Adding the ceremony now is overhead with zero payoff.

### Hotfix flow

If `main` has unreleasable work-in-progress when a critical bug is reported against the latest tag:

1. Branch from the tag: `git checkout -b hotfix/0.2.1 v0.2.0`
2. Apply the minimal fix, commit, open PR against `main`.
3. Merge to `main`, then tag `v0.2.1` on the merge commit and follow the normal release ritual below.

If `main` is releasable (the common case), just commit the fix to `main` and cut a patch release directly. No branch needed.

## Changelog conventions

[`CHANGELOG.md`](../../CHANGELOG.md) is the source of truth for what shipped. These rules keep it curated between releases so cutting one is a rename, not a rewrite.

**Where entries live.** Every in-progress entry goes under `## [Unreleased]`. The file's order is fixed: top matter → `## Versioning` → `## [Unreleased]` → released version entries, newest-first. Never open a second in-progress section.

**What earns an entry.** User-visible changes only: UI, `/api/v1/*` contract, `data/config.json` keys, the install/upgrade path, new or changed parser support, and docs that self-hosters act on. Internal refactors, CI/tooling, tests, and agent-workflow changes get no entry — the commit is the record for those.

**Altitude and length.** One bullet per capability, not per commit. Keep each to 1–3 lines. When you extend a feature that already has an Unreleased bullet, amend that bullet instead of stacking a new one. Link the relevant guide for depth rather than inlining the detail.

**Entry grammar.** Version headers are `## [X.Y.Z] — YYYY-MM-DD`. Subsections come only from the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) set — `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed`, `### Security` — and only the ones with entries.

**Banned content.** No commit SHAs, no PR or issue numbers, no internal process narrative, no references to private history, no exclamation marks. `Changed`/`Fixed` bullets describe the delta relative to the latest **public** release — never against something older or against unreleased trunk.

**Enforcement.** `make verify` runs [`scripts/checks/check_changelog.py`](../../scripts/checks/check_changelog.py), a mechanical lint covering heading grammar, dangling SHA/PR references, and release-notes extraction safety. It does not judge altitude or wording — that editorial call lives here and in the `/commit` skill, which flags a user-visible change and asks for the bullet at commit time.

## The release ritual

About 5 minutes of work when you decide to cut one. Run through the checklist top-to-bottom.

### 1. Pre-flight

```bash
git checkout main
git pull --ff-only
make verify              # backend + frontend + e2e + openapi drift
```

If `make verify` is red, fix it before tagging. **Never** tag a commit that doesn't pass verify.

Also run the private-fixture statement tests once per release — they are
condition-gated on real (uncommitted) bank statements, so no CI machine ever
executes them; a release is the one moment a machine that *has* the fixtures
must prove they still pass:

```bash
RUN_PRIVATE_FIXTURES=1 uv run pytest tests/unit/test_statement_parser.py tests/unit/test_statement_dedup.py -q
```

If the release includes UI changes, also regenerate the product screenshots and
commit any that moved — docs pages, marketing landing, and README pairs are all
captured from the static demo:

```bash
make screenshots         # docs-screenshots + marketing-screenshots
git diff --stat          # commit refreshed images if any changed
```

### 2. Update the changelog

Cutting a release is the moment you curate `## [Unreleased]` down to release notes, following the [Changelog conventions](#changelog-conventions) above. Open [`CHANGELOG.md`](../../CHANGELOG.md) and:

1. Dedupe and compress the `## [Unreleased]` entries per the conventions — one bullet per capability, per-commit noise folded away, anything reading like an internal commit message rewritten into "what changed for the user" prose. Self-hosters read this.
2. Rename `## [Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD` (today's date).
3. Add a fresh empty `## [Unreleased]` block above it, ready for the next cycle's entries (add subsection headers only as entries arrive).

### 3. Bump the version

Edit `pyproject.toml`:

```toml
version = "X.Y.Z"
```

That's the only place the version lives today. If you ever wire the version into the React frontend (e.g. footer or `/health` payload), update those too.

### 4. Commit and tag

```bash
# Use the /commit slash command for the changelog + version bump
/commit chore: release vX.Y.Z

# Tag the resulting commit
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

The tag must be on a commit that is already on `main` and has passed `make verify`.

### 5. Push the tag — the workflow handles the rest

Pushing `vX.Y.Z` (from Step 4) triggers [`.github/workflows/release.yml`](../../.github/workflows/release.yml), which builds and pushes multi-arch images to GHCR (`vX.Y.Z` + `latest`) and creates the GitHub Release from the matching `## [X.Y.Z]` block in `CHANGELOG.md`. Releases for `v0.*` tags are auto-marked pre-release.

```bash
gh run watch    # follow the run in real time
```

See [How the release workflow works](#how-the-release-workflow-works) below for what's happening under the hood, including the tagging scheme and common failure modes.

**Fallback (workflow failed or no GHCR access).** Recreate the GitHub Release by hand from the same CHANGELOG section:

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes-file <(awk '/^## \[X.Y.Z\]/,/^## \[/{if(!/^## \[/||/X.Y.Z/)print}' CHANGELOG.md)
```

Add `--prerelease` for `v0.*` tags. Then trigger the Docker push from the GitHub Actions UI (re-run the failed `Release` workflow) or build and push locally if the workflow is broken.

### 6. Post-release sanity check

- Pull a fresh clone in `/tmp` and run `docker compose up` against the demo to confirm the released image works end-to-end.
- Skim the release page on GitHub — broken links, wrong tag, missing changelog section.

## How the release workflow works

Two workflows publish images and releases. They split work by trigger so they never race for the same tag.

### Triggers

- [`.github/workflows/release.yml`](../../.github/workflows/release.yml) fires on `git push origin v*`. Builds + pushes versioned images, then creates the GitHub Release.
- [`.github/workflows/docker-build.yml`](../../.github/workflows/docker-build.yml) fires on push to `main` and on PRs. On main it pushes `:main`; on PRs it builds without pushing (compile-check).

### What gets built and pushed

Each trigger builds two images for two architectures:

- `ghcr.io/<owner>/tidings` from [`Dockerfile.prod`](../../Dockerfile.prod) — the FastAPI + React backend.
- `ghcr.io/<owner>/tidings-imap-poller` from [`docker/imap_polling/Dockerfile`](../../docker/imap_polling/Dockerfile) — the email-polling daemon.
- Both are built for `linux/amd64` and `linux/arm64` (RPi4/RPi5, Apple Silicon).

Tag scheme:

| Trigger | Tags written | Workflow |
|---------|--------------|----------|
| `git push origin v0.2.3` | `:v0.2.3`, `:latest` | `release.yml` |
| `git push origin main` | `:main` | `docker-build.yml` |
| PR (open or update) | none — compile-check only | `docker-build.yml` |

**Convention.** `:latest` always tracks the most recent **released** version, not trunk. `:main` is the trunk preview. Self-hosters who pin to `:latest` get stability; those who want bleeding-edge use `:main`; production deployments should pin a specific `:vX.Y.Z`.

### Order of operations on `git push origin v0.1.0`

1. GitHub receives the tag push.
2. `release.yml` fires. The `gate` job runs first: the backend test suite, then `scripts/pii/audit_oss_release.py` against the `git archive` of the tagged commit (the exact bytes that ship). Blocking PII hits (exit 1) abort the release before anything is published; the audit report is uploaded as a workflow artifact either way. A tag can land on a commit that never went through PR CI, which is why the gate re-runs the checks instead of trusting a prior run.
3. The `docker` matrix job (`needs: gate`) runs twice in parallel — once for `web`, once for `imap-poller`.
4. Each matrix job, per step:
   1. `actions/checkout@v4` — clone the repo.
   2. `docker/setup-qemu-action@v3` + `docker/setup-buildx-action@v3` — enable cross-arch builds.
   3. `docker/login-action@v3` — log into GHCR using the auto-provided `GITHUB_TOKEN`.
   4. `docker/metadata-action@v5` — compute the tag list: `:v0.1.0` (from the tag ref) + `:latest` (raw).
   5. `docker/build-push-action@v5` — build `linux/amd64` and `linux/arm64`, push both manifests to GHCR. Shares GHA cache with `docker-build.yml` (same scope keys), so a recent main build warms the release build.
4. The `github-release` job (`needs: docker`) runs once both matrix jobs succeed:
   1. `actions/checkout@v4` — clone the repo.
   2. Extract the `## [0.1.0]` section from `CHANGELOG.md` into `release-notes.md` via the same `awk` recipe used in the Step 5 fallback. Fails loudly if the section is missing.
   3. `gh release create v0.1.0 --notes-file release-notes.md --prerelease` (the `--prerelease` flag is added automatically for any tag matching `^v0\.`).
5. End state: two images on GHCR with two tags each (`:v0.1.0` + `:latest`), one GitHub Release page with the changelog as its body.

### Reading the run

```bash
gh run list --workflow=release.yml --limit 5   # find the run id
gh run watch <id>                              # stream logs
gh run view <id> --log-failed                  # inspect a failure
```

Direct link pattern: `https://github.com/<owner>/tidings/actions/workflows/release.yml`.

### Failure modes + recovery

Common failures and what each one means:

- **`No '## [X.Y.Z]' section in CHANGELOG.md`** — Step 2 of the ritual was skipped or mistyped. Fix: edit `CHANGELOG.md` on `main`, then re-tag:

  ```bash
  git tag -d vX.Y.Z
  git push --delete origin vX.Y.Z
  git tag -a vX.Y.Z -m "Release vX.Y.Z"
  git push origin vX.Y.Z
  ```

- **GHCR push fails with 403** — repo `Settings → Actions → General → Workflow permissions` is set to "Read repository contents". Flip to "Read and write permissions" (one-time per repo).
- **Build fails on `linux/arm64`** — a Python wheel or native dep is x86-only. Drop `linux/arm64` from `platforms:` as a temporary fix and file an issue; multi-arch wheels usually exist for a slightly newer dep version.
- **`gh release create` fails because the release already exists** — usually a re-pushed tag after fixing an earlier failure. Delete the existing release on the GitHub web UI first, then re-tag (see above).
- **Workflow doesn't fire at all** — check the tag pattern: `on: push: tags: ["v*"]` requires a `v` prefix. `0.1.0` won't fire; `v0.1.0` will.

In all cases the Step 5 manual fallback above gets the release out the door while you fix the workflow.

### Permissions + secrets

- `GITHUB_TOKEN` is auto-provided by GitHub Actions. No external secrets needed.
- `Settings → Actions → General → Workflow permissions` must be **"Read and write permissions"** for GHCR pushes. One-time setup on the new repo.
- GHCR image visibility inherits the repo's visibility: a private repo publishes private images; a public repo publishes public images. To make a private repo publish public images, configure the package's "Manage Actions access" settings on GHCR separately.

## Cadence

Ship when there's something worth shipping. Realistic shape:

- **While the parser/feature backlog is hot:** every 2–4 weeks is healthy. Batches stay small, regressions are easier to bisect.
- **Quieter periods:** monthly or longer is fine. Don't ship for the sake of shipping.
- **Critical bug:** patch release within 24–48h of a confirmed reproduction. Don't wait for the next planned release.

Do not promise a calendar in the README, ROADMAP, or release notes. "We ship when it's ready" is the only commitment that survives a busy month at the day job.

Candidate tooling changes to this ritual (release-please, SHA-pinning the actions) live in [`ROADMAP.md`](../../ROADMAP.md), not here — this guide describes the process as it works today.
