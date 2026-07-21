# API agent guide (src/api)

Backend addendum to `/workspace/CLAUDE.md` covering the FastAPI layer:
`main.py` (app factory), `routers/` (one module per `/api/v1/*` resource),
`models/` (Pydantic schemas, one module per resource), `dependencies.py`
(service factories), `auth.py` (bearer middleware), `errors.py` (unified
error shape).

## Contract

- Declare routers as `APIRouter(tags=["<resource>"])` with **no prefix** —
  `create_app()` applies `prefix="/api/v1"` when it registers each module in
  the `_ROUTERS` tuple (`src/api/main.py`). A new router isn't live until it's
  added to that tuple.
- Raise `HTTPException(status, detail)` for errors — registered handlers wrap
  it into the unified `{error, code, details}` body with a machine code
  derived from the status (`code_from_status`). Use `ApiException`
  (`src/api/errors.py`) only when you need a custom `code` or structured
  `details`.
- Request/response schemas are Pydantic models in
  `src/api/models/<resource>.py`, re-exported from `src/api/models/__init__.py`;
  set `response_model` on every route.

## Conventions

- Get services via the `Depends(get_*)` factories in `dependencies.py` —
  never construct storage or services inline; the factories honor the
  dual-backend (DynamoDB/SQLite) selection.
- Services are synchronous. Call them from async handlers via `run_sync(...)`
  (thread executor) instead of blocking the event loop.
- Mutating endpoints that must not touch the demo dataset call
  `ensure_not_demo(...)` from `dependencies.py`.
- Bearer auth is middleware with a per-scope allowlist (`SCOPE_ALLOWLISTS` in
  `auth.py`): `read` = GET-only on `/api/v1/*`, `read+write` = any method, so
  new `/api/v1/` endpoints are covered automatically; a new scope is a
  one-line addition there. Auth is a no-op while no agent tokens exist
  (zero-config localhost quickstart).

## After any route or model change

- Run `make verify-openapi` — it regenerates `openapi.json` **and**
  `frontend/src/types/api.generated.ts` and fails on drift (CI gates both).
- Run `uv run pytest tests/ -m "not integration"`.
