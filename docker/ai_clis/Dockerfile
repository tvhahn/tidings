# Layers the agent CLIs (Claude Code, OpenAI Codex, Google Gemini) on top of a
# published Tidings image, enabling the CLI providers in Settings →
# Intelligence without rebuilding the whole app image.
#
# Why not Dockerfile.prod's INSTALL_AI_CLIS arg? That path re-tags the
# registry tag (e.g. ghcr.io/…/tidings:main) with a local build, so the next
# `docker compose pull` silently clobbers the CLIs. This derived image keeps
# its own local tag: the base stays the CI-gated published image, pulls keep
# working, and an auto-update job can rebuild this layer after each pull —
# a cached no-op whenever the base digest is unchanged.
#
# Build (context needs no files, so point it at this directory):
#   docker build -t tidings-ai:main docker/ai_clis
# or via a compose override `build:` block — see
# docker-compose.override.yml.example.
ARG BASE_IMAGE=ghcr.io/tvhahn/tidings:main
FROM ${BASE_IMAGE}

# Same install steps as Dockerfile.prod's INSTALL_AI_CLIS block (NodeSource is
# unpinned, unlike the digest-pinned base images — an accepted trade-off for
# an opt-in local build). CLI login state lands in /home/tidings (~/.claude,
# ~/.codex, ~/.gemini); mount a volume there so logins survive recreation.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
USER tidings
