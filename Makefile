.PHONY: clean data lint requirements sync_data_to_s3 sync_data_from_s3 dev-api dev-frontend dev dev-attach dev-restart dev-demo dev-marketing dev-preview dev-docs build-frontend serve test test-ci test-fast openapi verify verify-graph frontend-typecheck demo-build verify-backend verify-frontend verify-frontend-slop verify-e2e screenshots docs-screenshots marketing-screenshots verify-docs verify-openapi verify-demo-api verify-canon check-changelog prod-smoke audit agent-token agent-token-show agent-token-revoke sync-pii-patterns pii-collision-check

#################################################################################
# GLOBALS                                                                       #
#################################################################################

PROJECT_DIR := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
BUCKET = [OPTIONAL] your-bucket-for-syncing-data (do not include 's3://')
PROFILE = default
PROJECT_NAME = expense_reporting
PYTHON_INTERPRETER = python

ifeq (,$(shell which uv))
HAS_UV=False
else
HAS_UV=True
endif

#################################################################################
# COMMANDS                                                                      #
#################################################################################

env:
ifeq (True,$(HAS_UV)) # uv is available
	@echo ">>> Setting up environment with uv"
	uv sync
	@echo ">>> Wiring git hooks (pre-push: remote allowlist + OSS release audit)"
	git config core.hooksPath .githooks/
	@echo ">>> Environment created. Activate with: source .venv/bin/activate"
else
	@echo ">>> uv not found. Please install uv first: https://docs.astral.sh/uv/getting-started/installation/"
	@exit 1
endif


API_PORT ?= 8000

# ---------------------------------------------------------------------------
# Frontend dev surfaces — port map
# ---------------------------------------------------------------------------
# 5173  dev-frontend    Real dashboard with the real backend (basename `/`).
# 5174  (reserved)      Conventionally claimed by a second worktree's `pnpm dev`.
# 5175  dev-marketing   Marketing landing only — for editing copy/CSS.
# 5176  dev-demo        Static-fixture demo SPA — what marketing CTAs land on
#                       in production. No backend; reads JSON from
#                       frontend/public/demo-data/.
# 4173  dev-preview     Production preview bundle (marketing at /, demo at /demo/).
#                       Exactly what ships; built then served by `pnpm exec serve`.
# 4321  dev-docs        Astro Starlight docs site. No backend; reads /docs/ +
#                       /openapi.json. Synced into docs-site/ on every dev/build.
# 8501  dev-eval-harness Streamlit prompt evaluation harness (dev/eval_harness/).
#                       Forwarded in .devcontainer/docker-compose.yml so it's
#                       reachable on the host's tailnet IP at <host>:8501. Not shipped.
# ---------------------------------------------------------------------------
# Override any port via make var, e.g. `make dev-demo DEMO_DEV_PORT=5180`.
DASHBOARD_PORT ?= 5173
MARKETING_DEV_PORT ?= 5175
DEMO_DEV_PORT ?= 5176
PREVIEW_PORT ?= 4173
DOCS_DEV_PORT ?= 4321
EVAL_HARNESS_PORT ?= 8501

## Start FastAPI backend (dev mode with hot reload)
dev-api:
	uv run uvicorn src.api.main:app --host 0.0.0.0 --port $(API_PORT) --reload --reload-dir src

## Start frontend dev server: real dashboard with real backend at :$(DASHBOARD_PORT)/
dev-frontend:
	@echo ">>> Real dashboard:  http://localhost:$(DASHBOARD_PORT)/"
	@echo ">>> (uses the real backend; basename '/')"
	cd frontend && VITE_DEV_PORT=$(DASHBOARD_PORT) pnpm dev

## Start both backend and frontend dev servers
dev:
	make dev-api & make dev-frontend

## Attach to dev server tmux session
dev-attach:
	tmux attach -t dev

## Restart both dev servers in tmux
dev-restart:
	tmux send-keys -t dev:api C-c Enter && sleep 1 && tmux send-keys -t dev:api 'make dev-api' Enter
	tmux send-keys -t dev:frontend C-c Enter && sleep 1 && tmux send-keys -t dev:frontend 'make dev-frontend' Enter

## Static-fixture demo SPA at :$(DEMO_DEV_PORT)/ (vite dev, mode=demo, no backend, fixture data)
dev-demo:
	@echo ">>> Static-fixture demo:  http://localhost:$(DEMO_DEV_PORT)/"
	@echo ">>> (no backend; reads fixtures from frontend/public/demo-data/)"
	cd frontend && pnpm exec vite --mode demo --port $(DEMO_DEV_PORT) --strictPort

## Marketing landing at :$(MARKETING_DEV_PORT)/ (vite dev, mode=marketing — for marketing iteration only)
dev-marketing:
	@echo ">>> Marketing landing:  http://localhost:$(MARKETING_DEV_PORT)/"
	@echo ">>> (only useful while iterating on frontend/src/marketing/)"
	cd frontend && pnpm exec vite --mode marketing --port $(MARKETING_DEV_PORT) --strictPort

## Production preview at :$(PREVIEW_PORT)/ — builds the demo bundle then serves it (marketing at /, demo at /demo/)
dev-preview:
	cd frontend && pnpm demo:build
	@echo ">>> Production preview:  http://localhost:$(PREVIEW_PORT)/"
	@echo ">>> (marketing at /, demo SPA at /demo/ — exactly what ships)"
	cd frontend && pnpm exec serve dist -l $(PREVIEW_PORT)

## Astro Starlight docs site at :$(DOCS_DEV_PORT)/ (no backend; reads /docs/ + /openapi.json)
dev-docs:
	@echo ">>> Docs site:  http://localhost:$(DOCS_DEV_PORT)/"
	@echo ">>> (Astro Starlight; pulls content from docs/ and openapi.json)"
	cd docs-site && pnpm dev --host 0.0.0.0 --port $(DOCS_DEV_PORT)

## Streamlit prompt eval harness at :$(EVAL_HARNESS_PORT)/ (binds 0.0.0.0 so it's
## reachable on the host's tailnet IP — see .devcontainer/docker-compose.yml port 8501).
## Requires `uv sync --extra eval` first.
dev-eval-harness:
	@echo ">>> Streamlit prompt eval:  http://localhost:$(EVAL_HARNESS_PORT)/"
	@echo ">>> Tailnet:  http://$$(hostname):$(EVAL_HARNESS_PORT)/  (or this machine's tailnet IP)"
	@echo ">>> Reads dev/eval_harness/, demo.db by default (toggle in sidebar)"
	uv run streamlit run dev/eval_harness/app.py \
	  --server.address 0.0.0.0 \
	  --server.port $(EVAL_HARNESS_PORT) \
	  --server.headless true \
	  --browser.gatherUsageStats false

## Build frontend for production
build-frontend:
	cd frontend && pnpm build

## Build frontend and serve full app
serve: build-frontend
	uv run uvicorn src.api.main:app --host 0.0.0.0 --port $(API_PORT)


## Delete all compiled Python files
clean:
	find . -type f -name "*.py[co]" -delete
	find . -type d -name "__pycache__" -delete


# Full-suite runs fan out across cores via pytest-xdist (`-n auto` ≈ 7x here,
# adapts to 4-core CI runners). Serial escape hatch: make test PYTEST_WORKERS=0.
# xdist is deliberately NOT in pytest addopts, so ad-hoc `uv run pytest file.py`
# iteration stays serial and fast.
PYTEST_WORKERS ?= auto

# Parallelism for the `verify` dependency graph (make -j fan-out). Override with
# `make verify VERIFY_JOBS=4`. Only affects the parallel graph run, not the
# standalone sub-targets.
VERIFY_JOBS ?= 8

## Run backend unit tests with coverage report (no threshold)
test:
	uv run pytest tests/ -m "not integration" -n $(PYTEST_WORKERS) --cov=src --cov-report=term-missing

## Run backend unit tests with the 90% branch-coverage gate (use in CI and pre-deploy)
test-ci:
	uv run pytest tests/ -m "not integration" -n $(PYTEST_WORKERS) --cov=src --cov-report=term-missing --cov-fail-under=90

## Run backend unit tests without coverage instrumentation (fastest feedback loop)
test-fast:
	uv run pytest tests/ -m "not integration" -n $(PYTEST_WORKERS)

## Regenerate openapi.json from the live FastAPI app
openapi:
	uv run python -c "from src.api.main import app; import json; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" > openapi.json

## Full regression gate: canon links + backend tests + ruff + frontend lint/typecheck/format/vitest + Playwright e2e + openapi drift + demo API artifacts + docs coverage/build
## Runs the 7 sub-targets in parallel under an explicit dependency graph (see
## verify-graph and the `$(if $(VERIFY_GRAPH),...)` prereq edges below). -Otarget
## groups each sub-target's output so parallel logs stay readable.
verify:
	@$(MAKE) VERIFY_GRAPH=1 -j $(VERIFY_JOBS) -Otarget verify-graph
	@echo "verify: all checks passed"

# The parallel graph entrypoint. Depends on the same 7 sub-targets as the old
# serial `verify`; ordering constraints between them are expressed as the
# graph-only prereq edges (guarded by $(VERIFY_GRAPH)) on the targets themselves.
verify-graph: verify-canon verify-backend verify-openapi verify-demo-api verify-frontend verify-e2e verify-docs

# Frontend TypeScript project build (tsc -b). Extracted so the graph can order it
# after codegen (verify-openapi rewrites api.generated.ts) and share it as the
# single tsc run feeding both verify-frontend and demo-build — avoiding the
# .tsbuildinfo race when they run concurrently.
frontend-typecheck: $(if $(VERIFY_GRAPH),verify-openapi)
	cd frontend && pnpm exec tsc -b

# Static demo build (client + SSR + marketing prerender). Standalone it runs the
# full `demo:build` (tsc -b included). In the graph it runs `demo:build:vite`
# (no tsc — frontend-typecheck already did it) and waits for verify-demo-api,
# which rewrites frontend/public/demo-api/ that vite copies into dist.
demo-build: $(if $(VERIFY_GRAPH),frontend-typecheck verify-demo-api)
	cd frontend && pnpm $(if $(VERIFY_GRAPH),demo:build:vite,demo:build)

## Docs gate: "Using Tidings" coverage (pages registered in sidebar + llms.txt,
## app routes screenshotted or waived, screenshot ids consistent) + docs-site build.
verify-docs: $(if $(VERIFY_GRAPH),verify-openapi)
	node scripts/checks/check_docs_coverage.mjs
	cd docs-site && pnpm build

## Post-deploy smoke against the DEPLOYED site (network required; not part of `make verify`).
## Catches host-level breakage the local gates structurally cannot see: `make verify` serves dist
## with `serve` (honors public/serve.json) while Cloudflare honors public/_redirects — two files,
## one rule, and only this target exercises the Cloudflare one. Run after every Pages deploy.
## Override the target with PROD_BASE_URL=https://<preview>.pages.dev to smoke a preview build.
prod-smoke:
	node scripts/checks/check_prod_surfaces.mjs

## Canon link check: broken links/paths in agent-facing context files, unmarked docs/specs/
## references (local-only tree, dangles in the public clone), missing AGENTS.md symlinks.
## Mirrored in the public-tree CI job (.github/workflows/ci.yml); keep the two in sync.
## Also runs the changelog format lint (check-changelog) as a doc-integrity prereq.
verify-canon: check-changelog
	uv run python scripts/checks/check_canon_links.py

## Changelog format lint: heading grammar (## [X.Y.Z] — YYYY-MM-DD / one [Unreleased], descending
## semver), Keep-a-Changelog subsection whitelist, dangling SHA/#NNN refs in entry bodies, and
## release-notes extraction safety (mirrors the release.yml awk slice). Stdlib-only, runs in verify
## via verify-canon; invoke directly with `make check-changelog`.
check-changelog:
	uv run python scripts/checks/check_changelog.py

## Demo API artifacts: regenerate the manifest + filtered OpenAPI, fail on drift, then run the structural gate.
## Regen is deterministic (byte-stable), so a clean tree stays clean; a stale committed artifact is caught here.
## Graph edge: generate_demo_openapi.py reads the root openapi.json, which verify-openapi truncates
## and rewrites (`make openapi` uses `> openapi.json`). Ordered after verify-openapi so the parallel
## run never reads a half-written (0-byte) openapi.json — same reason verify-docs waits on it.
verify-demo-api: $(if $(VERIFY_GRAPH),verify-openapi)
	cd frontend && pnpm demo:api-manifest
	uv run python scripts/demo/generate_demo_openapi.py
	git diff --exit-code frontend/public/demo-api/
	uv run python scripts/demo/check_demo_api.py

## Backend slice of verify: pytest via test-ci (90% branch-coverage floor, matches CI) + ruff check + ruff format --check + pyright + deptry dependency-hygiene + test-convention ratchet
verify-backend: test-ci
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	uv run pyright src/
	uv run deptry src/
	uv run python scripts/checks/check_test_conventions.py

## Frontend unit slice of verify: eslint + tsc -b + prettier --check + vitest (with coverage thresholds) + de-slop P0 gate
## In the parallel graph (VERIFY_GRAPH=1) the tsc -b step is dropped from the recipe and
## satisfied by the frontend-typecheck prereq instead, so tsc never runs twice concurrently.
verify-frontend: $(if $(VERIFY_GRAPH),frontend-typecheck)
	cd frontend && pnpm lint $(if $(VERIFY_GRAPH),,&& pnpm exec tsc -b) && pnpm format:check && pnpm run test:coverage
	node .claude/skills/ui-slop-audit/scripts/slop-grep.mjs frontend/src --fail-on=P0

# verify-frontend-slop — the ui-slop-audit v2 deterministic static report.
# Mirrored by the frontend-slop CI job (.github/workflows/ci.yml); keep the two in sync.
# GATE FLIPPED 2026-07-11: the one live P0 (StatementReview.tsx sticky-bar backdrop-blur) was
# triaged (solid bg-background) and the tree is P0-clean, so verify-frontend now runs the P0 gate
# as a second recipe line (from the repo root — the script path is repo-relative, so it must not
# live inside the `cd frontend &&` chain). This target remains the full non-blocking report.
## De-slop static report over frontend/src (ui-slop-audit v2; full report, always exit 0)
verify-frontend-slop:
	node .claude/skills/ui-slop-audit/scripts/slop-grep.mjs frontend/src --report

## Playwright end-to-end suite against the static demo build.
## demo-build produces dist/ (full demo:build standalone; demo:build:vite in the graph).
## The serve step binds an ephemeral port and gates readiness on a unique per-run build
## stamp we drop into dist/ — so two concurrent runs (or a stale :4173 serve) can never
## collide or let Playwright hit the wrong build.
verify-e2e: demo-build
	cd frontend && \
	  STAMP="verify-stamp-$$$$-$$(date +%s%N).txt"; \
	  printf '%s' "$$STAMP" > dist/$$STAMP; \
	  PORT=$$(node -e 'const s=require("net").createServer();s.listen(0,()=>{console.log(s.address().port);s.close();})'); \
	  pnpm exec serve dist -l $$PORT > /tmp/verify-serve-$$PORT.log 2>&1 & \
	  SERVER_PID=$$!; \
	  ready=0; \
	  for i in $$(seq 1 30); do \
	    if curl -sf "http://localhost:$$PORT/$$STAMP" 2>/dev/null | grep -q "$$STAMP"; then ready=1; break; fi; \
	    sleep 1; \
	  done; \
	  if [ $$ready -ne 1 ]; then \
	    echo "verify-e2e: server on port $$PORT never served our build stamp $$STAMP (see /tmp/verify-serve-$$PORT.log)"; \
	    kill $$SERVER_PID 2>/dev/null || true; \
	    rm -f dist/$$STAMP; \
	    exit 1; \
	  fi; \
	  DEMO_PREVIEW_URL="http://localhost:$$PORT" pnpm exec playwright test e2e/; \
	  STATUS=$$?; \
	  kill $$SERVER_PID 2>/dev/null || true; \
	  rm -f dist/$$STAMP; \
	  exit $$STATUS

## Regenerate every product screenshot from the static-fixture demo: docs pages,
## marketing landing assets, and README <picture> pairs. Run after a UI change
## that moves any captured surface.
screenshots: docs-screenshots marketing-screenshots

## Capture the marketing-landing + README screenshots (light+dark pairs) via
## scripts/media/generate_marketing_screenshots.ts. Boots its own vite dev servers on
## :5186 (demo) and :5185 (landing) so it never collides with your dev servers.
## Writes to frontend/src/marketing/assets/ and docs/static/readme/.
marketing-screenshots:
	cd frontend && \
	  (pnpm exec vite --mode demo --port 5186 --strictPort > /tmp/mkt-shots-demo.log 2>&1 & \
	   DEMO_PID=$$!; \
	   pnpm exec vite --mode marketing --port 5185 --strictPort > /tmp/mkt-shots-landing.log 2>&1 & \
	   LANDING_PID=$$!; \
	   for i in $$(seq 1 30); do curl -sf http://localhost:5186/ >/dev/null && curl -sf http://localhost:5185/ >/dev/null && break; sleep 1; done; \
	   MARKETING_SHOTS_URL=http://localhost:5186 MARKETING_LANDING_URL=http://localhost:5185 \
	     pnpm marketing:screenshots; \
	   STATUS=$$?; \
	   kill $$DEMO_PID $$LANDING_PID 2>/dev/null || true; \
	   exit $$STATUS)

## Capture the "Using Tidings" docs screenshots (light+dark WebP pairs) from the
## built static-fixture demo, served on :4179. Writes to docs-site/src/assets/screenshots/.
docs-screenshots:
	cd frontend && pnpm demo:build
	cd frontend && \
	  STAMP="verify-stamp-$$$$-$$(date +%s%N).txt"; \
	  printf '%s' "$$STAMP" > dist/$$STAMP; \
	  PORT=$$(node -e 'const s=require("net").createServer();s.listen(0,()=>{console.log(s.address().port);s.close();})'); \
	  pnpm exec serve dist -l $$PORT > /tmp/docs-shots-serve-$$PORT.log 2>&1 & \
	  SERVER_PID=$$!; \
	  ready=0; \
	  for i in $$(seq 1 30); do \
	    if curl -sf "http://localhost:$$PORT/$$STAMP" 2>/dev/null | grep -q "$$STAMP"; then ready=1; break; fi; \
	    sleep 1; \
	  done; \
	  if [ $$ready -ne 1 ]; then \
	    echo "docs-screenshots: server on port $$PORT never served our build stamp $$STAMP (see /tmp/docs-shots-serve-$$PORT.log)"; \
	    kill $$SERVER_PID 2>/dev/null || true; \
	    rm -f dist/$$STAMP; \
	    exit 1; \
	  fi; \
	  DOCS_SHOTS_URL="http://localhost:$$PORT" pnpm exec tsx ../scripts/media/generate_docs_screenshots.ts; \
	  STATUS=$$?; \
	  kill $$SERVER_PID 2>/dev/null || true; \
	  rm -f dist/$$STAMP; \
	  exit $$STATUS

## OpenAPI contract sync: regenerate openapi.json + the frontend types and fail on drift.
## Mirrors CI's openapi-check + frontend-codegen-check jobs so a local green
## verify cannot ship a stale api.generated.ts that only CI catches.
verify-openapi:
	$(MAKE) openapi
	git diff --exit-code openapi.json
	cd frontend && pnpm codegen
	git diff --exit-code frontend/src/types/api.generated.ts

## Issue a new agent bearer token. Args: LABEL='laptop-claude' [SCOPE=read+write|read]. Token is printed once; only the hash is persisted to data/config.json.
agent-token:
	@uv run python scripts/agent/agent_token.py generate --label "$(LABEL)" --scope "$(or $(SCOPE),read+write)"

## List all configured agent tokens (hashes only — raw values are never recoverable).
agent-token-show:
	@uv run python scripts/agent/agent_token.py show

## Revoke an agent token by id. Args: ID=<id from agent-token-show>.
agent-token-revoke:
	@uv run python scripts/agent/agent_token.py revoke --id "$(ID)"

## Maintainer-only: lint the local .pii-patterns alphabet, push it to the PII_PATTERNS
## GitHub Actions secret, and write the .pii-patterns.sha256 stamp that the pre-push
## staleness check compares against. Run from the main checkout (where .pii-patterns lives).
sync-pii-patterns:
	@test -f .pii-patterns || { echo "sync-pii-patterns: no .pii-patterns in $$(pwd) — run from the main checkout"; exit 1; }
	uv run python scripts/pii/lint_pii_patterns.py --patterns .pii-patterns --min-count 120
	gh secret set PII_PATTERNS < .pii-patterns
	sha256sum .pii-patterns | cut -d' ' -f1 > .pii-patterns.sha256
	@echo ">>> PII_PATTERNS secret refreshed and staleness stamp written"

## Maintainer-only: real-data collision check — download the live transaction export and
## search the tracked tree for real values (the inverse of the pattern-alphabet audit).
## Deletes the export CSV afterward; full findings land in gitignored logs/audit/.
pii-collision-check:
	uv run python scripts/pii/real_data_collision_check.py --download --include-matches

## Supply-chain audit: pip-audit + pnpm audit. (The former IOC scan script and its
## guide were removed in the OSS migration; Dependabot + the CI security-scan job cover that ground.)
audit:
	uv run pip-audit --ignore-vuln CVE-2025-69872
	cd frontend && pnpm audit --prod --audit-level high

#################################################################################
# PROJECT RULES                                                                 #
#################################################################################


#################################################################################
# Self Documenting Commands                                                     #
#################################################################################

.DEFAULT_GOAL := help

# Inspired by <http://marmelab.com/blog/2016/02/29/auto-documented-makefile.html>
# sed script explained:
# /^##/:
# 	* save line in hold space
# 	* purge line
# 	* Loop:
# 		* append newline + line to hold space
# 		* go to next line
# 		* if line starts with doc comment, strip comment character off and loop
# 	* remove target prerequisites
# 	* append hold space (+ newline) to line
# 	* replace newline plus comments by `---`
# 	* print line
# Separate expressions are necessary because labels cannot be delimited by
# semicolon; see <http://stackoverflow.com/a/11799865/1968>
.PHONY: help
help:
	@echo "$$(tput bold)Available rules:$$(tput sgr0)"
	@echo
	@sed -n -e "/^## / { \
		h; \
		s/.*//; \
		:doc" \
		-e "H; \
		n; \
		s/^## //; \
		t doc" \
		-e "s/:.*//; \
		G; \
		s/\\n## /---/; \
		s/\\n/ /g; \
		p; \
	}" ${MAKEFILE_LIST} \
	| LC_ALL='C' sort --ignore-case \
	| awk -F '---' \
		-v ncol=$$(tput cols) \
		-v indent=19 \
		-v col_on="$$(tput setaf 6)" \
		-v col_off="$$(tput sgr0)" \
	'{ \
		printf "%s%*s%s ", col_on, -indent, $$1, col_off; \
		n = split($$2, words, " "); \
		line_length = ncol - indent; \
		for (i = 1; i <= n; i++) { \
			line_length -= length(words[i]) + 1; \
			if (line_length <= 0) { \
				line_length = ncol - indent - length(words[i]) - 1; \
				printf "\n%*s ", -indent, " "; \
			} \
			printf "%s ", words[i]; \
		} \
		printf "\n"; \
	}' \
	| more $(shell test $(shell uname) = Darwin && echo '--no-init --raw-control-chars')
