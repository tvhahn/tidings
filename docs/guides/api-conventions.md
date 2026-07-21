# API conventions (/api/v1)

The contract rules the surface follows. New endpoints must comply; deviations
need a comment at the route and a line here.

- **Versioning** — everything mounts at `/api/v1`; breaking changes ship as `/api/v2`.
- **Errors** — every 4xx/5xx body is `{error, code, details}` (`src/api/errors.py`).
  Raise `HTTPException(status, detail)` for the default code, `ApiException` for a
  custom machine code.
- **Status codes** — 422: request shape/value invalid (including unparseable uploads).
  404: unknown or unparseable opaque resource id. 409: state conflict (duplicates,
  version conflicts, already-running jobs). 413: upload size caps. 202: accepted
  background job. Creates return **200** with a body identifying the resource (blessed
  2026-07 — see docs/specs/2026-07-02-api-python-quality-audit/). Avoid 400.
  Category rename/delete use a deliberately coarse 409: one `except ValueError` catches
  several service meanings (not found, already exists, protected) with only the message
  as discriminator, and we do not parse message text to pick a status code.
- **Months** — `YYYY-MM`, validated by `src/api/utils.py` (`MONTH_PATTERN`,
  `MONTH_RE`). Never inline a month regex.
- **Lists** — wrap in an object with a `count` (`{items|<resource>s: [...], count}`);
  never return a bare JSON array (it can't grow metadata).
- **Mutation acks** — return the affected resource, a bespoke result model, or
  `{ok: true}`. (`/auth/*` uses `{status}` — grandfathered.)
- **Identifiers in paths** — opaque ids (tx_id, statement_id) are single segments;
  user-authored names that may contain `/` use `:path` params (categories) or
  query-param identity (category icons).
- **Optimistic concurrency** — config-like resources carry `version`; writers take
  `expected_version` and 409 via `run_with_conflict_handling`.
- **Blocking work** — handlers are `async def` + `run_sync(...)` for storage/CPU/network,
  or plain `def` (FastAPI threadpools it) when nothing awaits.
- **Deployment constraint** — background-job state (insights, daily summaries) is
  process-local: run exactly one uvicorn worker.
- **Known asymmetry** — `query_month(projection=…)` is honored by DynamoDB, ignored by
  SQLite (returns all columns). Aggregations must not depend on fields outside their
  projection.
