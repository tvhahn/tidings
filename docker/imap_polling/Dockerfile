# Pinned by digest. Resolved 2026-04-30 from registry-1.docker.io/library/python:3.12-slim.
# See docs/guides/supply-chain-security.md.
FROM python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-group dev --no-editable

COPY src/ src/

# Non-root runtime user — same fixed uid/gid as Dockerfile.prod so the
# shared finance_data volume has one consistent owner across both services.
RUN groupadd --gid 10001 tidings \
    && useradd --uid 10001 --gid tidings --create-home tidings \
    && mkdir -p data \
    && chown tidings:tidings data
USER tidings

# --no-sync: the venv is baked at build time; never let `uv run` try to
# mutate a root-owned environment at runtime.
CMD ["uv", "run", "--no-sync", "python", "-m", "src.finance.imap_poller"]
