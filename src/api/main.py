"""FastAPI application for the finance dashboard."""

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from src.api.auth import bearer_auth_middleware
from src.api.dependencies import shutdown_executor
from src.api.errors import ApiError, code_from_status
from src.api.logging_config import configure_logging
from src.api.routers import (
    activity,
    attachments,
    auth,
    budget,
    categories,
    category_management,
    chatgpt_oauth,
    config,
    coverage,
    daily_summaries,
    groups,
    health,
    ignore_rules,
    income_statement,
    ingestion,
    insights,
    journal,
    merchant_aliases,
    merchants,
    overrides,
    parse_failures,
    search,
    statements,
    statements_crud,
    summary,
    tax,
    transactions,
)
from src.api.routers import (
    data as data_router,
)
from src.finance.decimal_utils import DecimalEncoder


class DecimalJSONResponse(JSONResponse):
    """JSONResponse that automatically converts Decimal values to float."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, cls=DecimalEncoder, ensure_ascii=False).encode("utf-8")


class SpaStaticFiles(StaticFiles):
    """StaticFiles with an SPA fallback for BrowserRouter deep links.

    A hard refresh on a client-side route (/transactions, /summary, …) reaches
    this mount with a path that has no file behind it — serve index.html and
    let the router take over. `api/`-shaped paths keep their 404: an HTML page
    is the wrong answer for a JSON consumer that typo'd an endpoint.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


def _serve_frontend() -> bool:
    """Whether to mount the bundled SPA + auto-load demo data on startup.

    Default `true` preserves the zero-config localhost quickstart. Set
    `SERVE_FRONTEND=false` for headless deployments (agents, bring-your-own-UI,
    pure API consumers) — the static mount and lifespan demo-loader both
    no-op so a real user's data isn't shadowed by the seeded demo DB.
    """
    return os.environ.get("SERVE_FRONTEND", "true").strip().lower() not in {"false", "0", "no"}


def _cors_allowed_origins() -> list[str]:
    """CORS allowlist, comma-separated. `*` = wildcard. Default keeps loopback dev intact."""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _configured_bind_host() -> str | None:
    """The uvicorn `--host` the process was launched with, or None if unset.

    Every launch path passes `--host` on the uvicorn command line (Makefile
    `dev-api`/`serve`, `Dockerfile.prod` CMD), so `sys.argv` is the reliable
    signal. When the flag is absent uvicorn binds loopback (127.0.0.1).
    """
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--host" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--host="):
            return arg.split("=", 1)[1]
    return None


def _is_non_loopback(host: str) -> bool:
    """True when `host` binds an off-box interface (0.0.0.0, ::, a LAN IP)."""
    return host not in {"127.0.0.1", "localhost", "::1"} and not host.startswith("127.")


def _warn_if_auth_bypass_exposed() -> None:
    """Loud reminder — no behaviour change — when the dev auth bypass is on
    while the server binds a non-loopback host. That pairing serves the API
    with cookie auth disabled to anything on the LAN/tailnet (audit S2)."""
    from src.finance.app_config import get_config

    if not get_config().get("auth_bypass_for_dev"):
        return
    host = _configured_bind_host()
    if host is None or not _is_non_loopback(host):
        return
    logging.getLogger(__name__).warning(
        "auth_bypass_for_dev is ON and the server is binding a non-loopback host (%s): "
        "cookie auth is disabled and the API is reachable off-box. Turn the bypass off "
        "in data/config.json for any shared or production deployment.",
        host,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    _warn_if_auth_bypass_exposed()
    scheduler_shutdown: asyncio.Event | None = None
    scheduler_task: asyncio.Task[None] | None = None
    coverage_task: asyncio.Task[None] | None = None
    s3_backup_task: asyncio.Task[None] | None = None
    # Auto-load demo data if demo mode is active and DB is empty.
    # Skipped under SERVE_FRONTEND=false: headless deployments use real data,
    # not the seeded demo fixtures.
    if _serve_frontend():
        from src.finance.app_config import get_config

        cfg = get_config()
        if cfg.get("demo_mode") and cfg.get("storage") != "dynamodb":
            from src.finance.demo_loader import ensure_demo_loaded

            ensure_demo_loaded()

        # Daily summary scheduler — only in user-facing (frontend-serving)
        # mode. Headless agent deployments don't have a UI to display
        # summaries and shouldn't burn LLM credits on a cron.
        if not cfg.get("demo_mode"):
            from src.finance.coverage_notifier import run_coverage_scheduler
            from src.finance.daily_summary_scheduler import run_scheduler
            from src.finance.s3_backup_scheduler import run_s3_backup_scheduler

            scheduler_shutdown = asyncio.Event()
            scheduler_task = asyncio.create_task(run_scheduler(scheduler_shutdown))
            # Sibling daily task: quiet-transition notifications (ingestion
            # coverage). Shares the shutdown event; keyed off the same gating.
            coverage_task = asyncio.create_task(run_coverage_scheduler(scheduler_shutdown))
            # Sibling hourly task: opt-in S3 mirror of attachments/statements.
            # Shares the shutdown event; self-gates on config + AWS credentials.
            s3_backup_task = asyncio.create_task(run_s3_backup_scheduler(scheduler_shutdown))
    try:
        yield
    finally:
        if scheduler_shutdown is not None:
            scheduler_shutdown.set()
            for task in (scheduler_task, coverage_task, s3_backup_task):
                if task is None:
                    continue
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (TimeoutError, asyncio.CancelledError):
                    task.cancel()
                except Exception:
                    logging.getLogger(__name__).exception("Scheduler shutdown error")
        shutdown_executor()


_OPENAPI_TAGS = [
    {"name": "config", "description": "App configuration (storage backend, demo mode, user_id)."},
    {"name": "ingestion", "description": "Transaction ingestion — upload and reparse raw email bodies."},
    {"name": "transactions", "description": "Transaction CRUD, soft delete, attention queue, bulk updates."},
    {"name": "categories", "description": "Predefined category list used by OpenAI function calling."},
    {"name": "summary", "description": "Monthly spending summaries, trends, and comparisons."},
    {"name": "budget", "description": "Budget targets, pace status, and historical averages."},
    {"name": "insights", "description": "AI spending intelligence — streamed briefings and the raw context they use."},
    {"name": "overrides", "description": "Company→category override rules + suggestion engine."},
    {
        "name": "ignore-rules",
        "description": "Merchant auto-ignore rules — pin a merchant to ignored, backfill history, suggestions.",
    },
    {"name": "category-management", "description": "Add, rename, delete categories in the master list."},
    {"name": "groups", "description": "Budget display-only category groupings."},
    {"name": "search", "description": "Cross-month transaction search with CSV export."},
    {"name": "statements", "description": "Statement PDF upload, parsing, and four-tier reconciliation."},
    {"name": "statements-crud", "description": "Persisted statement state — list, detail, delete, edit transactions."},
    {
        "name": "attachments",
        "description": "Per-transaction receipts and documents — upload, list, download, link, delete.",
    },
    {"name": "income-statement", "description": "Yearly personal income statement aggregation."},
    {
        "name": "tax",
        "description": "Calendar-year tax pack: claim-line totals with per-transaction evidence, plus a zip export.",
    },
    {
        "name": "merchants",
        "description": "Merchant intelligence — recurring-charge detection, price changes, burn rate.",
    },
    {"name": "journal", "description": "Day-grouped transaction timeline with MTD running totals."},
    {"name": "daily-summaries", "description": "AI-generated per-day narrative summaries for the journal."},
    {"name": "merchant-aliases", "description": "Merchant alias CRUD for the Tier 2 override resolver."},
    {"name": "data", "description": "Full-data backup: export as zip, import with dedup preview."},
    {
        "name": "parse-failures",
        "description": "Quarantined bank emails the parsers couldn't read — review, retry, dismiss.",
    },
    {"name": "auth", "description": "Third-party OAuth flows (ChatGPT)."},
    {
        "name": "webapp-auth",
        "description": "Webapp cookie-session auth — set/change password, login, logout, sign out all.",
    },
    {"name": "health", "description": "Liveness + last-activity probe (unauthenticated)."},
    {
        "name": "coverage",
        "description": "Per-institution bank-alert cadence — quiet/dormant detection and passive capture rate.",
    },
    {
        "name": "activity",
        "description": "Agent activity ledger — caller introspection (whoami), the write journal, and stale-guarded revert.",
    },
]


# Paths the freshness probe invalidates; 30s browser cache short-circuits repeat
# fetches inside the probe window without breaking the live-data story.
_SHORT_CACHE_PATHS = frozenset(
    {
        "/api/v1/summary",
        "/api/v1/summary/trend",
    }
)

# Active-mutation endpoints (ignore/delete/edit on /journal; generate→poll→refetch
# on /journal/summaries). Header-absence is *not* equivalent to "no caching" —
# without an explicit directive, browsers (notably mobile Safari) fall back to
# heuristic caching, which has masked freshly-mutated state in the wild. Emit
# no-store so HTTP-level caches stay out of the way; React Query's 5-min
# staleTime handles intra-session short-circuiting.
_NO_CACHE_PATHS = frozenset(
    {
        "/api/v1/journal",
        "/api/v1/journal/summaries",
        "/api/v1/journal/summaries/status",
    }
)


async def add_cache_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    if request.method != "GET" or response.status_code >= 400:
        return response
    path = request.url.path
    if path == "/api/v1/categories":
        response.headers.setdefault(
            "Cache-Control",
            "private, max-age=300, stale-while-revalidate=3600",
        )
    elif path in _SHORT_CACHE_PATHS:
        response.headers.setdefault(
            "Cache-Control",
            "private, max-age=30, stale-while-revalidate=300",
        )
    elif path in _NO_CACHE_PATHS:
        response.headers.setdefault("Cache-Control", "no-store")
    return response


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """Rewrite every HTTPException into the unified `{error, code, details}` shape."""
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("__api_error__"):
        payload = ApiError(
            error=str(detail.get("message", "Error")),
            code=str(detail.get("code", "error")),
            details=detail.get("details"),
        )
    else:
        payload = ApiError(
            error=str(detail) if detail else "Error",
            code=code_from_status(exc.status_code),
            details=None,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Wrap FastAPI's 422 validation errors into the unified shape."""
    # jsonable_encoder sanitizes non-serializable ctx (e.g. the ValueError a
    # field_validator raises), matching FastAPI's own default handler.
    payload = ApiError(
        error="Request validation failed",
        code="VALIDATION_ERROR",
        details={"errors": jsonable_encoder(exc.errors())},
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Wrap any otherwise-unhandled exception in the unified `{error, code, details}` shape.

    `src/api/errors.py` promises every 4xx/5xx follows the envelope; without this
    Starlette returns a plain-text 500 for uncaught errors. Also fires for
    exceptions raised in run_sync-offloaded code.
    """
    logging.getLogger(__name__).exception("Unhandled error", exc_info=exc)
    payload = ApiError(error="Internal server error", code="INTERNAL_ERROR", details=None)
    return JSONResponse(status_code=500, content=payload.model_dump())


_ROUTERS = (
    config,
    coverage,
    ingestion,
    transactions,
    categories,
    summary,
    budget,
    insights,
    overrides,
    ignore_rules,
    category_management,
    groups,
    search,
    statements,
    statements_crud,
    attachments,
    income_statement,
    tax,
    journal,
    daily_summaries,
    merchant_aliases,
    merchants,
    parse_failures,
    data_router,
    chatgpt_oauth,
    activity,
    health,
    auth,
)


# Plain-text orientation file served at `/llms.txt` on every running instance
# (self-hosted and headless alike). The llms.txt convention lets LLM tooling
# orient on a host before it reads the schema. `include_in_schema=False` keeps
# it out of the OpenAPI document (no drift); paths outside `/api/v1/` bypass
# bearer auth, so no `PUBLIC_PATHS` entry is needed.
_LLMS_TXT = """\
# Tidings

> A self-hosted personal finance journal built from bank transaction alert
> emails. This is a running Tidings instance; the data on it belongs to its
> owner.

## API

- OpenAPI schema: /openapi.json
- Interactive docs: /docs
- API base: /api/v1/ (bearer token required once agent tokens are configured)

## Project

- Documentation: https://docs.gettidings.com/ (agent index: https://docs.gettidings.com/llms.txt)
- Agent access guide: https://docs.gettidings.com/agent-access/
- Source: https://github.com/tvhahn/tidings
"""


def create_app() -> FastAPI:
    """Build a fresh FastAPI app, reading env vars at construction time.

    Module-level `app = create_app()` covers the production import. Tests
    that flip `SERVE_FRONTEND` / `CORS_ALLOWED_ORIGINS` build their own app
    via this factory so the env-var read isn't frozen at module load.
    """
    app = FastAPI(
        title="Finance Dashboard API",
        version="0.1.0",
        description=(
            "Self-hosted personal finance dashboard API. Ingests bank transaction emails, "
            "categorizes them (with optional OpenAI enrichment), and exposes transactions, budgets, "
            "summaries, and AI spending insights over a consistent JSON HTTP interface.\n\n"
            "**Storage:** dual-backend — DynamoDB (AWS) or SQLite (local/demo). Selection is driven "
            "by `data/config.json`. All endpoints return identical shapes regardless of backend.\n\n"
            "**Versioning:** routes are prefixed with `/api/v1/`. Breaking changes will ship as "
            "`/api/v2/` rather than in-place."
        ),
        openapi_tags=_OPENAPI_TAGS,
        lifespan=lifespan,
        default_response_class=DecimalJSONResponse,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Bearer auth between CORS and GZip: CORS handles preflight first; the
    # auth check runs before any GZip-wrapped response is produced. No-op
    # when `agent_tokens` is empty so the zero-config localhost quickstart
    # in README.md still works.
    app.middleware("http")(bearer_auth_middleware)
    # Compress responses >500 bytes. Neutral on loopback; meaningful if ever served over WAN.
    app.add_middleware(GZipMiddleware, minimum_size=500)

    app.middleware("http")(add_cache_headers)
    app.exception_handler(HTTPException)(http_exception_handler)
    app.exception_handler(RequestValidationError)(validation_exception_handler)
    app.exception_handler(Exception)(unhandled_exception_handler)

    for router_module in _ROUTERS:
        app.include_router(router_module.router, prefix="/api/v1")

    @app.get("/llms.txt", include_in_schema=False)
    async def llms_txt() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        return PlainTextResponse(_LLMS_TXT)

    if _serve_frontend():
        # Static SPA mount must come AFTER API routers so /api/v1/* takes precedence.
        frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
        if frontend_dist.is_dir():
            app.mount("/", SpaStaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
