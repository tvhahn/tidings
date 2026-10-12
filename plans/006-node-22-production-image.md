# Plan 006: Move the production image's frontend build stage from Node 20 to Node 22

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat cd828e5..HEAD -- Dockerfile.prod docs/guides/supply-chain-security.md`
> If either file changed since this plan was written, compare the "Current
> state" excerpts below against the live files before you start. If they don't
> match, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none. It needs a machine that can reach Docker Hub (see "Why this was left").
- **Category**: migration
- **Planned at**: commit `cd828e5`, 2026-09-25

## Why this matters

Node 20 reached end of life on 2026-04-30 and no longer gets security fixes.
The rest of the project already moved to Node 22 on branch
`claude/sweet-volta-5yawaj`:

- every GitHub Actions `setup-node` step,
- a root `.nvmrc` containing `22`,
- `engines.node: ">=22.12"` in `frontend/package.json` and `docs-site/package.json`,
- `CONTRIBUTING.md`.

The one place still on Node 20 is the frontend build stage of
`Dockerfile.prod`, which builds the React bundle shipped in the self-hosted
image. Until it moves, the published image is built with an unsupported
runtime, and with a different Node than CI tests against.

### Why this was left

The repo pins every base image by digest (`docs/guides/supply-chain-security.md`).
The session that did the upgrade ran behind a network proxy that blocked
Docker Hub and the public ECR mirror, so it could not resolve a trustworthy
`node:22-slim` digest. The maintainer chose to keep the Node 20 pin rather
than switch to an unpinned tag. This plan is that remaining step.

## Current state

- `Dockerfile.prod` lines 1–12 (stage 1, the frontend build):

  ```dockerfile
  # Pinned by digest. Resolved 2026-05-05 from registry-1.docker.io/library/node:20-slim.
  # See docs/guides/supply-chain-security.md.
  FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS frontend-builder

  WORKDIR /build/frontend

  # Enable pnpm 10 via Corepack (ships with Node 20). Mirrors the version
  # used by ci.yml's pnpm/action-setup steps.
  RUN corepack enable && corepack prepare pnpm@10 --activate
  ```

- `docs/guides/supply-chain-security.md` line 14, in the pinned-images table:

  ```
  | `Dockerfile.prod` | frontend build | `node:20-slim` |
  ```

- The Python stages of `Dockerfile.prod` and `docker/imap_polling/Dockerfile`
  (`python:3.12-slim@sha256:…`) are unrelated. Leave them alone.
- The refresh procedure is documented in
  `docs/guides/supply-chain-security.md` § "Refresh a pinned image". This plan
  follows it. The key rule: use the **multi-platform index digest** (the top
  `Digest:` line), not a per-architecture digest, because the image is built
  for both amd64 and arm64.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Resolve digest | `docker buildx imagetools inspect node:22-slim` | prints `Name`, `MediaType: application/vnd.oci.image.index.v1+json`, and a top-level `Digest: sha256:…` |
| Build self-hosted images | `docker compose build` | exit 0 |
| Smoke the web image | `docker compose up -d finance && curl -fsS http://localhost:8000/api/v1/health && docker compose down` | JSON with `"status": "ok"` |
| Canon links | `uv run python scripts/checks/check_canon_links.py` | `canon link check: clean` |

## Scope

**In scope**:

- `Dockerfile.prod`: stage 1 only (the pin comment, the `FROM` line and the Corepack comment)
- `docs/guides/supply-chain-security.md`: the `Dockerfile.prod` row of the pinned-images table
- `plans/README.md`: this plan's status row

**Out of scope** (do NOT touch):

- The Python base images, and their digests, in any Dockerfile.
- `.devcontainer/Dockerfile`, which uses an unpinned `node:22` for local development by design.
- The pnpm version. It stays at `pnpm@10` to match CI.
- CI workflow files. They are already on Node 22.

## Git workflow

- Commit on the current branch. Don't create branches (root `CLAUDE.md` § Committing).
- Use the `/commit` skill if available. Otherwise use the house format, for example
  `🔒 security(docker): Build the production frontend on Node 22`.
- This changes only the build toolchain, not the shipped app, so a changelog
  entry is optional. Follow the `/commit` changelog gate.
- Do not push unless told to.

## Steps

### Step 1: Resolve the Node 22 digest

Run `docker buildx imagetools inspect node:22-slim` on a machine with Docker
Hub access. Copy the top-level `Digest:` value, which is the index digest.
Confirm that the `Manifests:` list includes both `linux/amd64` and
`linux/arm64`.

**Verify**: the digest is 71 characters, `sha256:` plus 64 hex characters, and the MediaType is an image index.

### Step 2: Update stage 1 of `Dockerfile.prod`

Replace the three lines shown in "Current state" with the following. Fill in
today's date and the digest from Step 1:

```dockerfile
# Pinned by digest. Resolved YYYY-MM-DD from registry-1.docker.io/library/node:22-slim.
# See docs/guides/supply-chain-security.md.
FROM node:22-slim@sha256:<digest from step 1> AS frontend-builder
```

Also change the Corepack comment from `(ships with Node 20)` to
`(ships with Node 22)`. Leave the `RUN corepack …` line unchanged.

**Verify**: `grep -n "node:20" Dockerfile.prod` → no output. `grep -c "node:22-slim@sha256:" Dockerfile.prod` → `1`.

### Step 3: Update the guide's table

In `docs/guides/supply-chain-security.md`, change the `Dockerfile.prod` row's
image from `node:20-slim` to `node:22-slim`.

**Verify**: `grep -rn "node:20" Dockerfile.prod docs/guides/supply-chain-security.md` → no output. `uv run python scripts/checks/check_canon_links.py` → clean.

### Step 4: Build and smoke-test

Run the "Build self-hosted images" and "Smoke the web image" commands from
the table above. Then open `http://localhost:8000/` before `docker compose down`
and confirm the dashboard loads, which proves the frontend bundle built on
Node 22 is served.

**Verify**: build exits 0, `/api/v1/health` returns `"status": "ok"`, the dashboard HTML loads.

### Step 5: Commit, then let CI confirm both architectures

Commit the two files. After pushing, `docker-build.yml` builds the web and
IMAP images for amd64 and arm64 on any pull request that touches
`Dockerfile.prod`. That run must be green.

## Done criteria

- [ ] `grep -rn "node:20" Dockerfile.prod docs/guides/supply-chain-security.md` → no output
- [ ] The `FROM` line pins `node:22-slim` by a multi-platform index digest, with a "Resolved <date>" comment
- [ ] `docker compose build` exits 0, and the health probe returns `"status": "ok"`
- [ ] `docker-build.yml` is green for amd64 and arm64 on the pull request
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` row 006 set to DONE

## STOP conditions

- `imagetools inspect` returns a single-platform manifest instead of an index,
  or the index lacks `linux/arm64`.
- `corepack` is missing from the Node 22 image, so the `RUN corepack enable …`
  step fails. Node 22 is expected to ship Corepack; Node 25 and later do not.
- `pnpm install --frozen-lockfile` or the Vite build fails inside the image on
  Node 22. CI and local development already build the frontend on Node 22, so
  this would point to an image-specific problem. Report the build log rather
  than changing the Dockerfile further.

## Maintenance notes

- Node 22 reaches end of life in April 2027. The next move is to Node 24, and
  it follows the same steps: every `setup-node` version in
  `.github/workflows/*.yml`, `.nvmrc`, `engines.node` in both `package.json`
  files, `CONTRIBUTING.md`, and this Dockerfile stage. Corepack is no longer
  bundled from Node 25, so moving past 24 also means installing pnpm another way.
- Dependabot does not watch Dockerfiles, so this digest stays put until someone
  refreshes it. Refresh it along with the Python digests, following the guide.
