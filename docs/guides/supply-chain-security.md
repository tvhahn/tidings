# Supply-chain security

What pins the builds, what checks them, and how to move a pin on purpose.

## Base images are pinned by digest

A tag like `python:3.12-slim` moves every time upstream rebuilds it. A digest
names one exact image, so a build only changes when you change the digest.
Every `FROM` line carries a digest and a comment naming the tag it was resolved
from and the date:

| Dockerfile | Stage | Resolved from |
|---|---|---|
| `Dockerfile.prod` | frontend build | `node:20-slim` |
| `Dockerfile.prod` | runtime | `python:3.12-slim` |
| `docker/imap_polling/Dockerfile` | runtime | `python:3.12-slim` |
| `docker/email_parsing/Dockerfile` | Lambda runtime | `public.ecr.aws/lambda/python:3.12` |

The `uv` binary is copied from a tag, not a digest: `ghcr.io/astral-sh/uv:0.11.14`
in `Dockerfile.prod` and the IMAP image, `uv:latest` in the Lambda image.

Nothing refreshes these digests automatically. Dependabot does not watch the
Dockerfiles (see [Dependabot](#dependabot)), so a pin moves only when you move it.

## Refresh a pinned image

1. Resolve the current digest for the tag:

   ```bash
   docker buildx imagetools inspect python:3.12-slim
   ```

   Copy the `Digest:` line at the top of the output. That is the multi-platform
   index digest; the per-platform digests listed under `Manifests:` each pin
   one architecture, which the amd64 + arm64 image builds cannot use. The same command works for
   `node:<tag>` and `public.ecr.aws/lambda/python:3.12`.

2. Update the `FROM` line: replace the value after `@sha256:`, and change the
   comment above it to `Resolved YYYY-MM-DD from <registry>/<image>:<tag>`. If
   you also change the tag, change it in both the `FROM` line and the comment.
   `python:3.12-slim` appears in two Dockerfiles; move both together.

3. Build the images and run the smoke checks:

   ```bash
   # Lambda image: the same import check CI's docker-build job runs
   docker build --platform linux/amd64 -f docker/email_parsing/Dockerfile -t test-build .
   docker run --rm --entrypoint python test-build -c "from lambda_function import handler; print('OK')"

   # Self-hosted stack: build both images, start the web service, probe health
   docker compose build
   docker compose up -d finance
   curl -fsS http://localhost:8000/api/v1/health
   docker compose down
   ```

4. Commit the Dockerfile change on its own. CI rebuilds the Lambda image on
   every pull request and every push to `main`; `docker-build.yml` builds the web and IMAP
   images for amd64 and arm64 when a pull request touches either Dockerfile.

## Lockfiles

- **`uv.lock`** pins every Python package. CI's `uv lock --check` step (the
  `backend-lint` job) fails when it is stale against `pyproject.toml`, and the
  Docker images install from it.
- **`frontend/pnpm-lock.yaml`** and **`docs-site/pnpm-lock.yaml`** pin the
  JavaScript packages. CI and `Dockerfile.prod` install with
  `pnpm install --frozen-lockfile`, which fails instead of re-resolving.

Change a dependency by editing `pyproject.toml` or `package.json` and
committing the regenerated lockfile in the same change.

## Audit gates

- **`make audit`** runs `uv run pip-audit` and `pnpm audit --prod --audit-level high`
  in `frontend/`. The pnpm half needs pnpm 11, because npm retired the audit
  endpoint pnpm 10 uses; with pnpm 10 installed, run
  `npx pnpm@11 audit --prod --audit-level high` from `frontend/` instead.
- **The `security-scan` job** in `.github/workflows/ci.yml` runs the same two
  audits on every push and pull request to `main`.
- **`.github/workflows/dep-audit.yml`** reruns them every Monday, so an advisory
  published between pushes turns the Actions tab red within a week. Set the
  optional `NTFY_URL` secret to get a push notification when it fails.

`pip-audit` checks the packages installed in the environment it runs in. CI
installs without the `notebooks` dependency group, so those packages are only
audited by a local `make audit`.

## Dependabot

`.github/dependabot.yml` opens weekly update pull requests, at most five open
at a time per entry, for:

- Python packages (the `pip` ecosystem at the repo root)
- GitHub Actions used by the workflows
- npm packages in `frontend/`
- npm packages in `docs-site/`

It does not cover the Docker base images or the `uv` image tag. Refresh those
by hand with the steps above.
