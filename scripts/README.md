# scripts/

Repo and CI tooling, grouped by domain. Operator CLIs live in `dev/cli/`,
not here. Every script carries a header docstring with usage; this index
records who calls what.

## checks/ — verification gates

| Script | Called by |
|--------|-----------|
| `check_canon_links.py` | `make verify-canon`, CI `public-tree` |
| `check_docs_coverage.mjs` | `make verify-docs`, CI `docs-coverage` |
| `check_test_conventions.py` | `make verify-backend`, CI `backend-lint` |
| `migrate_api_tests.py` | By hand — libcst codemod that migrates legacy API tests onto shared helpers, driving the `check_test_conventions.py` ratchet down |

## pii/ — open-source release gate

Works with local-only `.pii-patterns` / `.pii-dispositions` at the repo
root. See `docs/guides/releases.md`.

| Script | Called by |
|--------|-----------|
| `audit_oss_release.py` | `.githooks/pre-push`, CI `public-tree`, `release.yml` |
| `lint_pii_patterns.py` | `make sync-pii-patterns` (lint step), `check_pii_gate_armed.sh` |
| `check_pii_gate_armed.sh` | CI `public-tree` / `demo-smoke` / `release.yml` — proves the gate is live (pattern lint + canary run) |
| `real_data_collision_check.py` | `make pii-collision-check` — scans the tree for values from the real transaction export |

## demo/ — static hosted demo pipeline

| Script | Called by |
|--------|-----------|
| `demo_endpoints.ts` | Imported by both generators — canonical endpoint list |
| `generate_demo_fixtures.ts` | `pnpm demo:fixtures[:ai]` (needs API on :8000) |
| `generate_demo_api_manifest.ts` | `pnpm demo:api-manifest` |
| `generate_demo_openapi.py` | `make verify-demo-api` |
| `check_demo_api.py` | `make verify-demo-api`, CI `demo-smoke` |
| `check_demo_fixtures.py` | CI `demo-smoke` |

## media/ — screenshots, images, brand assets

| Script | Called by |
|--------|-----------|
| `generate_marketing_screenshots.ts` | `make marketing-screenshots` (part of `make screenshots`) |
| `generate_docs_screenshots.ts` | `make docs-screenshots` (demo build on :4179) |
| `docs_screenshots.manifest.ts` | Imported by the docs capturer; read by `checks/check_docs_coverage.mjs` |
| `generate_og_images.ts` | `pnpm og:images` |
| `prerender_marketing.ts` | `pnpm demo:build` (run from `frontend/`, CWD-relative) |
| `generate-image.py` | `generate-image` skill — gpt-image-2 asset generation |
| `chroma-key.py` | `generate-image` skill — matte → transparent-PNG cutout |
| `outline_wordmark.py` | By hand — regenerates the wordmark SVGs from Source Serif 4 |

## agent/ — agent access tooling

| Script | Called by |
|--------|-----------|
| `agent_token.py` | `make agent-token` / `-show` / `-revoke` |
| `agent-bootstrap.py` | `headless-backend-bootstrap` skill |

## fixtures/ — synthetic statement PDFs

Importable package (`uv run python -m scripts.fixtures.<generator>`);
renders parser-compatible bank-statement PDFs from expected-output JSON.
The module path is load-bearing — don't move it.

Note for movers: the Python scripts anchor the repo root as
`Path(__file__).resolve().parents[2]` and the TS scripts as
`resolve(__dirname, "..", "..")` — both assume exactly one subdirectory
level below `scripts/`. Unit tests under `tests/unit/` also import several
of these files by literal path.
