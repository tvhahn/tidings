# Base image pinned by digest. Resolved 2026-04-30 against
# public.ecr.aws/v2/lambda/python/manifests/3.12. Bumping the tag is not
# enough — refresh the digest via `curl -sI -H 'Authorization: Bearer
# $(curl -s https://public.ecr.aws/token/ | jq -r .token)' \
# https://public.ecr.aws/v2/lambda/python/manifests/3.12 | grep -i digest`.
# See docs/guides/supply-chain-security.md.
FROM public.ecr.aws/lambda/python:3.12@sha256:b47d5c18e29dd523457b183a4c203d6d7fc887db6f56a8580a8ed44cb7725f91

# uv is the build tool; the artifact identity is determined by the committed
# uv.lock, not by which uv version produced it. Tier 2 will pin this by digest.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR ${LAMBDA_TASK_ROOT}

# Resolve and install dependencies from the committed lockfile rather than
# from pyproject.toml ranges. This is the security boundary: every build that
# touches PyPI must go through uv.lock so a typosquat or maintainer-account
# compromise cannot land here without first changing the lockfile in a PR.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-group dev --no-emit-project --no-hashes -o /tmp/requirements.txt \
 && uv pip install --system --no-cache --target ${LAMBDA_TASK_ROOT} --requirement /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# Source code is loaded via LAMBDA_TASK_ROOT being on sys.path, not via
# site-packages — there is no editable install of the project itself.
COPY src ./src
COPY docker/email_parsing/lambda_function.py .
COPY docker/email_parsing/summary_handler.py .
COPY docker/email_parsing/coverage_handler.py .

CMD ["lambda_function.handler"]
