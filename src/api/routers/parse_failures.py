"""Parse-failure quarantine endpoints — review, retry, and dismiss the bank
emails the deterministic parsers couldn't read.

Quarantined rows carry the full ``email_details`` dict (as ``email_json``), so a
retry re-runs the deterministic parsers via ``parse_email_body`` to confirm a
parser fix. Retry deliberately does **not** invoke AI extraction — that is the
ingestion-time recovery path, not the manual-confirmation path.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import (
    ensure_not_demo,
    get_override_service,
    get_parse_failure_store,
    get_transactions_db,
    run_sync,
)
from src.api.models.parse_failures import (
    DismissResponse,
    FixtureFromFailureRequest,
    FixtureFromFailureResponse,
    ManualResolveRequest,
    ManualResolveResponse,
    ParseFailureDetail,
    ParseFailureListResponse,
    ParseFailureSummary,
    RetryAllRequest,
    RetryAllResponse,
    RetryResponse,
)
from src.api.serializers import build_manual_transaction_data
from src.finance.category_audit import build_audit
from src.finance.config_loader import get_override_context
from src.finance.fixture_scrub import scrub_body, write_fixture_pair
from src.finance.parse_failure_store_local import VALID_STATUSES

if TYPE_CHECKING:
    from src.finance.protocols import (
        IOverrideService,
        IParseFailureStore,
        ITransactionsDB,
    )

logger = logging.getLogger(__name__)

router = APIRouter(tags=["parse-failures"])

# Keys that map straight onto ParseFailureSummary (the store returns extras like
# created_at/updated_at/file_name that the API surface deliberately omits).
_SUMMARY_KEYS = (
    "id",
    "received_at",
    "from_email",
    "subject",
    "detected_institution",
    "failure_stage",
    "status",
    "recovered_date_file_name",
    "alert_classifier_result",
)


def _body_from_email_json(email_json: str | None) -> str:
    """Extract the email body from the stored ``email_json`` blob."""
    if not email_json:
        return ""
    try:
        details = json.loads(email_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    return str(details.get("body") or "") if isinstance(details, dict) else ""


# --- to-fixture helpers ----------------------------------------------------
#
# The to-fixture endpoint writes into the repo tree by design, so it is gated on
# running from a git checkout (a `.git` directory OR file — worktrees use a
# file) and non-demo mode. These helpers are module-level so router tests can
# monkeypatch them (point the target root at a tmp dir; force the git gate).

# Cap on a single retry-all sweep (L6). Module-level so tests can shrink it.
_RETRY_ALL_CAP = 1_000

# Upper bound on rows fetched from the store per sweep. A larger quarantined
# backlog than this is truncated (and a warning logged), but this keeps the
# single full-row fetch bounded rather than pulling an unbounded partition.
_RETRY_ALL_LIST_LIMIT = 10_000


def _repo_root() -> Path:
    """Repo root: src/api/routers/parse_failures.py → parents[3]."""
    return Path(__file__).resolve().parents[3]


def _is_git_checkout() -> bool:
    """True when the repo root has a ``.git`` entry.

    ``Path.exists()`` is true for both a directory (normal clone) and a file
    (git worktree), which is exactly the pair L5 requires.
    """
    return (_repo_root() / ".git").exists()


def _test_data_root() -> Path:
    """Root under which fixture pairs are written (``tests/test_data``)."""
    return _repo_root() / "tests" / "test_data"


# Distinct from ``src.api.utils.sanitize_filename`` on purpose: this produces a
# lowercased, persisted fixture-directory slug (a stable on-disk contract), not a
# display/attachment filename — so it must not be consolidated with that helper.
def _slugify(value: str) -> str:
    """Lowercase, spaces→underscores, strip non-alphanumerics (keep ``_``).

    Matches the existing ``tests/test_data/`` dir naming (e.g. ``pc_financial``).
    """
    slug = value.strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_]", "", slug)


def _email_domain(from_email: str | None) -> str | None:
    """Return the lowercased domain of an email address, or None."""
    if not from_email or "@" not in from_email:
        return None
    domain = from_email.rsplit("@", 1)[1].strip().strip(">").lower()
    return domain or None


def _domain_matches(from_email: str | None, from_domain: str) -> bool:
    """Suffix-match the sender's domain against ``from_domain``.

    ``rbc.com`` matches both ``alerts.rbc.com`` and ``rbc.com``.
    """
    domain = _email_domain(from_email)
    if domain is None:
        return False
    target = from_domain.strip().lower()
    return bool(target) and (domain == target or domain.endswith("." + target))


@router.get(
    "/parse-failures",
    response_model=ParseFailureListResponse,
    operation_id="listParseFailures",
    summary="List quarantined parse failures (summaries only, no email body)",
)
async def list_parse_failures(
    status: str | None = Query(
        None,
        description="Optional status filter (quarantined, recovered, retried, dismissed).",
    ),
    limit: int = Query(100, ge=1, le=10_000, description="Max rows to return."),
    store: IParseFailureStore = Depends(get_parse_failure_store),
):
    """Return parse-failure summaries, newest first, optionally filtered by status."""
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status {status!r}; expected one of {', '.join(VALID_STATUSES)}",
        )
    failures = await run_sync(store.list_failures, status, limit)
    return ParseFailureListResponse(
        count=len(failures),
        failures=[ParseFailureSummary(**f) for f in failures],
    )


@router.get(
    "/parse-failures/{failure_id}",
    response_model=ParseFailureDetail,
    operation_id="getParseFailure",
    summary="Get a single quarantined parse failure, including the email body",
)
async def get_parse_failure(
    failure_id: str,
    store: IParseFailureStore = Depends(get_parse_failure_store),
):
    """Return a full parse-failure row, including the original email body."""
    row = await run_sync(store.get_failure, failure_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Parse failure not found")
    body = _body_from_email_json(row.get("email_json"))
    return ParseFailureDetail(body=body, **{k: row[k] for k in _SUMMARY_KEYS})


@router.post(
    "/parse-failures/{failure_id}/retry",
    response_model=RetryResponse,
    operation_id="retryParseFailure",
    summary="Re-run the deterministic parsers against a quarantined email",
)
async def retry_parse_failure(
    failure_id: str,
    store: IParseFailureStore = Depends(get_parse_failure_store),
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
):
    """Re-run the deterministic parsers (no AI extraction) against the stored
    email. A successful parse adds the transaction and marks the row retried;
    a duplicate marks it retried; anything else leaves it quarantined.
    """
    row = await run_sync(store.get_failure, failure_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Parse failure not found")

    return await run_sync(_retry_sync, failure_id, row, store, db, override_svc)


def _retry_sync(
    failure_id: str,
    row: dict[str, Any],
    store: IParseFailureStore,
    db: ITransactionsDB,
    override_svc: IOverrideService,
) -> RetryResponse:
    """Synchronous retry body — runs inside the run_sync thread pool."""
    from src.finance.email_pipeline import parse_email_body

    email_details = json.loads(row["email_json"])
    body = str(email_details.get("body") or "")

    # No AI extraction on retry — pass api_client=None. Categorization then falls
    # back to the override lookup below, mirroring upload_eml.
    result = parse_email_body(body, email_details, None)

    if not result or not result.get("company"):
        # Row stays quarantined — the parser still can't read this email.
        return RetryResponse(failure_id=failure_id, status="still_failing")

    # Categorize via the override resolver (no AI), mirroring upload_eml.
    category = result.get("category", "miscellaneous")
    if not category or category == "miscellaneous":
        _, aliases = get_override_context()
        override_cat = override_svc.lookup_category(result.get("company", ""), aliases=aliases)
        if override_cat:
            category = override_cat
    result["category"] = category

    category_audit = result.pop("_category_audit", None)
    db_result = db.add_transaction(result, category_audit)

    if db_result is None:
        # Fields present but the DB rejected them (e.g. missing required field).
        return RetryResponse(failure_id=failure_id, status="still_failing")
    if db_result is False:
        # Duplicate — no new row created, so leave any existing recovery link intact.
        store.set_status(failure_id, "retried")
        return RetryResponse(failure_id=failure_id, status="duplicate")

    assert isinstance(db_result, str)  # noqa: S101 — type-narrowing; False case handled above
    store.set_status(failure_id, "retried", db_result)
    return RetryResponse(failure_id=failure_id, status="created", date_file_name=db_result)


@router.post(
    "/parse-failures/{failure_id}/to-fixture",
    response_model=FixtureFromFailureResponse,
    operation_id="parseFailureToFixture",
    summary="Write a scrubbed test-fixture pair from a quarantined email (dev checkout only)",
)
async def parse_failure_to_fixture(
    failure_id: str,
    body: FixtureFromFailureRequest | None = None,
    store: IParseFailureStore = Depends(get_parse_failure_store),
):
    """Write a scrubbed ``.txt`` + ``.json`` fixture pair from a captured email
    so a new parser can be authored from real evidence.

    Gated to a dev checkout: this writes into the repo's ``tests/test_data/``
    tree, so it refuses (403) unless the server runs from a git checkout and is
    not in demo mode. Never overwrites an existing pair (409).
    """
    ensure_not_demo("Writing fixtures is turned off in demo mode.")
    if not _is_git_checkout():
        raise HTTPException(
            status_code=403,
            detail=(
                "Writing fixtures needs the server running from a git checkout "
                "of the repo — it saves files under tests/test_data/."
            ),
        )

    row = await run_sync(store.get_failure, failure_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Parse failure not found")

    # Pick the institution string once (request body wins, else the detected one),
    # then derive the directory slug from that single choice so both paths get the
    # canonical folder name (e.g. "PC Financial" → pc_financial, not "pc financial").
    institution_arg = (body.institution if body else None) or None
    detected = row.get("detected_institution")
    if institution_arg and institution_arg.strip():
        institution_value = institution_arg.strip()
    elif detected and str(detected).strip():
        institution_value = str(detected).strip()
    else:
        raise HTTPException(
            status_code=422,
            detail="No institution to file under — pass institution in the request body.",
        )

    dir_slug = _slugify(institution_value)
    if not dir_slug:
        raise HTTPException(
            status_code=422,
            detail=(
                "That institution name has no letters or numbers to build a folder name "
                "from — pass an institution with Latin letters or numbers."
            ),
        )

    return await run_sync(_to_fixture_sync, failure_id, row, dir_slug, institution_value)


def _to_fixture_sync(
    failure_id: str,
    row: dict[str, Any],
    dir_slug: str,
    institution_value: str,
) -> FixtureFromFailureResponse:
    """Synchronous fixture write — runs inside the run_sync thread pool."""
    email_json = row.get("email_json")
    details: dict[str, Any] = {}
    if email_json:
        try:
            loaded = json.loads(email_json)
            if isinstance(loaded, dict):
                details = loaded
        except (json.JSONDecodeError, TypeError):
            details = {}

    raw_body = str(details.get("body") or "")
    forwarded_to = details.get("forwarded_to")
    scrubbed = scrub_body(raw_body, forwarded_to=str(forwarded_to) if forwarded_to else None)

    subject = str(row.get("subject") or "")
    file_slug = _slugify(subject) or _slugify(failure_id) or failure_id

    test_data_root = _test_data_root()
    try:
        rel_txt, rel_json = write_fixture_pair(
            test_data_root=test_data_root,
            dir_slug=dir_slug,
            file_slug=file_slug,
            scrubbed_body=scrubbed,
            institution=institution_value,
        )
    except FileExistsError:
        # Bank alerts repeat subjects verbatim (every "INTERAC e-Transfer: You
        # received money" collides), so auto-disambiguate with a short suffix
        # derived from the (unique) failure id before giving up.
        suffix = _slugify(failure_id)[:8] or failure_id[:8]
        disambiguated = f"{file_slug}_{suffix}" if suffix else file_slug
        try:
            rel_txt, rel_json = write_fixture_pair(
                test_data_root=test_data_root,
                dir_slug=dir_slug,
                file_slug=disambiguated,
                scrubbed_body=scrubbed,
                institution=institution_value,
            )
        except FileExistsError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"A fixture named {disambiguated!r} already exists under {dir_slug!r}.",
            ) from exc

    return FixtureFromFailureResponse(txt_path=rel_txt, json_path=rel_json)


@router.post(
    "/parse-failures/retry-all",
    response_model=RetryAllResponse,
    operation_id="retryAllParseFailures",
    summary="Re-run the deterministic parsers across a whole institution's quarantined backlog",
)
async def retry_all_parse_failures(
    body: RetryAllRequest,
    store: IParseFailureStore = Depends(get_parse_failure_store),
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
):
    """Retry every quarantined row matching the filter through the same
    deterministic (no-AI) path as single retry. Useful after a parser lands to
    recover a backlog. At least one of ``institution`` / ``from_domain`` is
    required; the sweep is capped at 1,000 rows and runs synchronously.
    """
    institution = (body.institution or "").strip() or None
    from_domain = (body.from_domain or "").strip() or None
    if institution is None and from_domain is None:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one of institution or from_domain.",
        )

    return await run_sync(_retry_all_sync, institution, from_domain, store, db, override_svc)


def _retry_all_sync(
    institution: str | None,
    from_domain: str | None,
    store: IParseFailureStore,
    db: ITransactionsDB,
    override_svc: IOverrideService,
    cap: int | None = None,
) -> RetryAllResponse:
    """Synchronous bulk retry — filters quarantined rows, then reuses the single
    retry core (`_retry_sync`) so both endpoints share one code path.

    One pass over full rows (``email_json`` included): each matched body is read
    exactly once — no per-row ``get_failure`` re-query. Per-row exceptions are
    logged and counted as ``still_failing`` (the row genuinely stays quarantined)
    so one bad row can never abort the sweep after earlier rows have committed.
    """
    cap = cap if cap is not None else _RETRY_ALL_CAP

    # Full rows carry email_json alongside detected_institution + from_email, so
    # we filter and retry in a single pass. The fetch is bounded; if it comes
    # back full the backlog may be truncated, so surface that rather than
    # silently dropping the tail.
    rows = store.list_failures_full("quarantined", _RETRY_ALL_LIST_LIMIT)
    if len(rows) >= _RETRY_ALL_LIST_LIMIT:
        logger.warning(
            "retry-all considered the first %d quarantined rows; a larger backlog may be truncated.",
            _RETRY_ALL_LIST_LIMIT,
        )

    created = duplicates = still_failing = 0
    for row in rows:
        inst_match = institution is not None and row.get("detected_institution") == institution
        domain_match = from_domain is not None and _domain_matches(row.get("from_email"), from_domain)
        if not (inst_match or domain_match):
            continue

        failure_id = row["id"]
        try:
            result = _retry_sync(failure_id, row, store, db, override_svc)
        except Exception:
            # A single row failing (corrupt/None email_json, DynamoDB throttling,
            # an unexpected parser error) must not 500 the whole sweep after
            # earlier rows already committed. It stays quarantined → still_failing.
            logger.exception("retry-all: row %s failed during retry; leaving it quarantined.", failure_id)
            still_failing += 1
        else:
            if result.status == "created":
                created += 1
            elif result.status == "duplicate":
                duplicates += 1
            else:
                still_failing += 1

        # Cap counts only rows actually processed, so the returned `retried`
        # equals created + duplicates + still_failing by construction.
        if created + duplicates + still_failing >= cap:
            break

    return RetryAllResponse(
        retried=created + duplicates + still_failing,
        created=created,
        duplicates=duplicates,
        still_failing=still_failing,
    )


@router.post(
    "/parse-failures/{failure_id}/resolve",
    response_model=ManualResolveResponse,
    operation_id="resolveParseFailure",
    summary="Record a hand-entered transaction for a quarantined email and mark it resolved",
)
async def resolve_parse_failure(
    failure_id: str,
    body: ManualResolveRequest,
    store: IParseFailureStore = Depends(get_parse_failure_store),
    db: ITransactionsDB = Depends(get_transactions_db),
    override_svc: IOverrideService = Depends(get_override_service),
):
    """Record the values the user typed by hand for a quarantined email and mark
    the failure resolved in one call.

    Unlike retry (which re-runs the deterministic parsers and can only ever
    confirm a parser fix), this accepts manual field overrides — the recovery
    path for the long tail no parser will ever read. The created transaction
    carries a ``manual`` CategoryAudit and no ExtractionAudit, so its provenance
    stays distinguishable from an AI-recovered row even though both reuse the
    store's ``recovered`` status.
    """
    row = await run_sync(store.get_failure, failure_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Parse failure not found")

    return await run_sync(_resolve_sync, failure_id, row, body, store, db, override_svc)


def _resolve_sync(
    failure_id: str,
    row: dict[str, Any],
    body: ManualResolveRequest,
    store: IParseFailureStore,
    db: ITransactionsDB,
    override_svc: IOverrideService,
) -> ManualResolveResponse:
    """Synchronous resolve body — runs inside the run_sync thread pool."""
    transaction_data = build_manual_transaction_data(
        date=body.date,
        amount=body.amount,
        company=body.company,
        transaction_type=body.transaction_type,
        category=body.category,
        # Fall back to the bank the quarantine row detected before "Manual".
        institution=body.institution or row.get("detected_institution"),
        name=None,
        override_svc=override_svc,
    )

    result = db.add_transaction(transaction_data, build_audit("manual"))

    if result is None:
        raise HTTPException(status_code=422, detail="Could not store transaction — check the values")
    if result is False:
        # Already recorded — still flip the row out of the queue (mirrors retry's
        # duplicate handling) so it doesn't dead-end as a quarantined orphan.
        # No new row created, so leave any existing recovery link intact.
        store.set_status(failure_id, "recovered")
        return ManualResolveResponse(failure_id=failure_id, status="duplicate")

    assert isinstance(result, str)  # noqa: S101 — type-narrowing; False case handled above
    store.set_status(failure_id, "recovered", result)
    return ManualResolveResponse(failure_id=failure_id, status="created", date_file_name=result)


@router.delete(
    "/parse-failures/{failure_id}",
    response_model=DismissResponse,
    operation_id="dismissParseFailure",
    summary="Dismiss a quarantined parse failure",
)
async def dismiss_parse_failure(
    failure_id: str,
    store: IParseFailureStore = Depends(get_parse_failure_store),
):
    """Mark a quarantined parse failure as dismissed. 404 if it doesn't exist."""
    updated = await run_sync(store.set_status, failure_id, "dismissed")
    if not updated:
        raise HTTPException(status_code=404, detail="Parse failure not found")
    return DismissResponse(failure_id=failure_id, status="dismissed")
