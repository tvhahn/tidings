"""Search endpoints: cross-month transaction search and CSV export.

**Filter semantics.** Filters are intentionally *not* uniform across fields:

- ``q`` — **case-insensitive substring across merchant, note, and category**
  (``Company`` OR ``Comment`` OR ``Category``, any-of). This is the free-text
  box: one needle, matched against several fields at once.
- ``company`` — **case-insensitive substring**. Merchant strings arrive with
  payment-processor noise (e.g. ``"Sq *coffee Spot Cen"``,
  ``"Spotify P0123ab456"``), so exact match would be useless.
- ``category``, ``institution``, ``type`` — **case-insensitive exact match**.
  These are clean enum-like values where partial match would return the wrong
  rows.

The split is load-bearing domain knowledge, not an inconsistency to harmonize.
"""

import asyncio
import csv
import io
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_spending_summary, run_sync
from src.api.models import SearchByFilterRequest, SearchResponse, SearchSummary
from src.api.serializers import (
    PROJECTION_NAMES,
    TRANSACTION_LIST_PROJECTION,
    to_transaction_response,
)
from src.api.utils import MONTH_PATTERN, generate_month_keys
from src.finance.app_timezone import TZ_ABBREV_SUFFIX_RE
from src.finance.decimal_utils import decimal_to_float
from src.finance.protocols import ISpendingSummary, TransactionItem

CsvFlavor = Literal["search", "backup"]

SEARCH_CSV_COLUMNS: list[str] = [
    "Date",
    "Amount",
    "Company",
    "Category",
    "Institution",
    "Type",
    "Name",
    "Comment",
    "Statement Source",
    "Ignored",
]

# Backup CSV superset — same first 10 columns as Search, then identity +
# change-history (CategoryAudit) + trash + email provenance + expanded
# statement-source fields + SQLite-only created_at. A plain Search CSV is a
# valid subset: missing columns are recomputed on import.
BACKUP_CSV_COLUMNS: list[str] = [
    *SEARCH_CSV_COLUMNS,
    # identity / round-trip
    "ForwardedTo",
    "DateFileName",
    "TransactionHash",
    # change history
    "CategoryAuditSource",
    "CategoryAuditReviewedAt",
    "CategoryAuditMatchedRule",
    "CategoryAuditConfidence",
    "CategoryAuditTier",
    "CategoryAuditPreviousCategory",
    "CategoryAuditPreviousSource",
    "CategoryAuditModel",
    "CategoryAuditFallbackReason",
    "CategoryAuditSchemaVersion",
    # trash state
    "DeletedAt",
    # email provenance
    "Subject",
    "FromName",
    "FromEmail",
    "ToName",
    "ToEmail",
    "FileName",
    "Body",
    # statement provenance (expanded from StatementSource JSON)
    "StatementInstitution",
    "StatementAccountType",
    "StatementPeriodStart",
    "StatementPeriodEnd",
    "StatementPdfPath",
    # SQLite-only
    "CreatedAt",
]

# `_generate_csv` is the transaction CSV serializer; the data-backup exporter
# (`src/finance/data_backup.py`) reuses it so the backup CSV matches the search
# export byte-for-byte. It stays underscore-prefixed to signal "not a public
# router API" — this export list just marks the cross-module reuse as
# intentional. (The finance->router import direction is a known layering wart,
# noted for a future move of the serializer into the finance layer.)
__all__ = ["_generate_csv"]

router = APIRouter(tags=["search"])

_MAX_MONTHS = 24
_WEB_CAP = 1000

# Filter parameter descriptions — kept as constants to keep signatures scannable.
_DESC_FROM = "Inclusive start month, YYYY-MM."
_DESC_TO = "Inclusive end month, YYYY-MM. Must be >= `from`; range capped at 24 months."
_DESC_CATEGORY = "Case-insensitive **exact** match (clean enum value)."
_DESC_INSTITUTION = "Case-insensitive **exact** match (clean enum value)."
_DESC_COMPANY = (
    "Case-insensitive **substring** match. Merchant strings are noisy "
    "(payment-processor codes, store numbers), so partial match is the correct default."
)
_DESC_TYPE = "Case-insensitive **exact** match (clean enum value: purchase, withdrawal, preauth, e-transfer)."
_DESC_Q = "Free-text search across merchant, note, and category (case-insensitive substring; any-of)."
_DESC_MIN_AMOUNT = "Inclusive lower bound on Amount."
_DESC_MAX_AMOUNT = "Inclusive upper bound on Amount."
_DESC_INCLUDE_IGNORED = "If true, include rows flagged as Ignored."
_DESC_INCLUDE_DELETED = "If true, include soft-deleted rows."


def _filter_items(
    items: list[TransactionItem],
    *,
    category: str | None,
    company: str | None,
    institution: str | None,
    txn_type: str | None,
    min_amount: float | None,
    max_amount: float | None,
    include_ignored: bool,
    include_deleted: bool,
    q: str | None = None,
) -> list[TransactionItem]:
    """Apply post-query filters to raw DynamoDB items."""
    result = items

    if not include_deleted:
        result = [i for i in result if not i.get("DeletedAt")]
    if not include_ignored:
        result = [i for i in result if not i.get("Ignored")]

    if q:
        needle = q.lower()
        result = [
            i
            for i in result
            if needle in (i.get("Company") or "").lower()
            or needle in (i.get("Comment") or "").lower()
            or needle in (i.get("Category") or "").lower()
        ]

    if category:
        cat_lower = category.lower()
        result = [i for i in result if (i.get("Category") or "").lower() == cat_lower]

    if company:
        co_lower = company.lower()
        result = [i for i in result if co_lower in (i.get("Company") or "").lower()]

    if institution:
        inst_lower = institution.lower()
        result = [i for i in result if (i.get("Institution") or "").lower() == inst_lower]

    if txn_type:
        type_lower = txn_type.lower()
        result = [i for i in result if (i.get("TransactionType") or "").lower() == type_lower]

    if min_amount is not None:
        result = [i for i in result if float(i.get("Amount") or 0) >= min_amount]

    if max_amount is not None:
        result = [i for i in result if float(i.get("Amount") or 0) <= max_amount]

    return result


def _build_summary(items: Sequence[Mapping[str, Any]], months_queried: int) -> SearchSummary:
    """Compute summary stats from filtered items."""
    total = 0.0
    by_category: dict[str, float] = {}
    for item in items:
        amt = float(item.get("Amount") or 0)
        total += amt
        cat = (item.get("Category") or "miscellaneous").lower()
        by_category[cat] = by_category.get(cat, 0.0) + amt

    count = len(items)
    return SearchSummary(
        total_count=count,
        total_amount=round(total, 2),
        avg_amount=round(total / count, 2) if count else 0.0,
        by_category={k: round(v, 2) for k, v in by_category.items()},
        months_queried=months_queried,
    )


async def _fetch_and_filter(
    summary: ISpendingSummary,
    month_keys: list[str],
    *,
    category: str | None,
    company: str | None,
    institution: str | None,
    txn_type: str | None,
    min_amount: float | None,
    max_amount: float | None,
    include_ignored: bool,
    include_deleted: bool,
    q: str | None = None,
) -> list[TransactionItem]:
    """Fetch all months concurrently and apply filters."""
    results = await asyncio.gather(
        *[run_sync(summary.query_month, ym, TRANSACTION_LIST_PROJECTION, PROJECTION_NAMES) for ym in month_keys]
    )

    all_items: list[TransactionItem] = []
    for month_items in results:
        all_items.extend(month_items)

    filtered = _filter_items(
        all_items,
        category=category,
        company=company,
        institution=institution,
        txn_type=txn_type,
        min_amount=min_amount,
        max_amount=max_amount,
        include_ignored=include_ignored,
        include_deleted=include_deleted,
        q=q,
    )

    # Sort newest first
    filtered.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)
    return filtered


@router.get(
    "/transactions/search",
    response_model=SearchResponse,
    operation_id="searchTransactions",
    summary="Cross-month transaction search with filters",
)
async def search_transactions(
    summary: ISpendingSummary = Depends(get_spending_summary),
    from_month: str = Query(..., alias="from", pattern=MONTH_PATTERN, description=_DESC_FROM),
    to_month: str = Query(..., alias="to", pattern=MONTH_PATTERN, description=_DESC_TO),
    q: str | None = Query(None, description=_DESC_Q),
    category: str | None = Query(None, description=_DESC_CATEGORY),
    institution: str | None = Query(None, description=_DESC_INSTITUTION),
    company: str | None = Query(None, description=_DESC_COMPANY),
    type: str | None = Query(None, description=_DESC_TYPE),  # noqa: A002 — public query-param name in the API contract
    min_amount: float | None = Query(None, description=_DESC_MIN_AMOUNT),
    max_amount: float | None = Query(None, description=_DESC_MAX_AMOUNT),
    include_ignored: bool = Query(False, description=_DESC_INCLUDE_IGNORED),
    include_deleted: bool = Query(False, description=_DESC_INCLUDE_DELETED),
):
    month_keys = generate_month_keys(from_month, to_month, max_months=_MAX_MONTHS)

    filtered = await _fetch_and_filter(
        summary,
        month_keys,
        category=category,
        company=company,
        institution=institution,
        txn_type=type,
        min_amount=min_amount,
        max_amount=max_amount,
        include_ignored=include_ignored,
        include_deleted=include_deleted,
        q=q,
    )

    total_matching = len(filtered)
    capped = total_matching > _WEB_CAP
    display = filtered[:_WEB_CAP] if capped else filtered

    return SearchResponse(
        transactions=[to_transaction_response(i) for i in display],
        summary=_build_summary(filtered, len(month_keys)),
        capped=capped,
        total_matching=total_matching,
    )


def _filter_items_by_lists(
    items: list[TransactionItem],
    *,
    category_in: list[str] | None,
    merchant_in: list[str] | None,
    institution_in: list[str] | None,
    type_in: list[str] | None,
    min_amount: float | None,
    max_amount: float | None,
    include_ignored: bool,
    include_deleted: bool,
) -> list[TransactionItem]:
    """Apply array (any-of) filters to raw items.

    Parallel to ``_filter_items`` but accepts lists. Empty / None list = no
    filter on that dimension; non-empty list = "row matches if any list
    entry matches." ``merchant_in`` is substring-match (each entry is a
    case-insensitive substring); the other string filters are exact match.
    """
    result = items

    if not include_deleted:
        result = [i for i in result if not i.get("DeletedAt")]
    if not include_ignored:
        result = [i for i in result if not i.get("Ignored")]

    if category_in:
        wanted = {c.lower() for c in category_in}
        result = [i for i in result if (i.get("Category") or "").lower() in wanted]

    if merchant_in:
        needles = [m.lower() for m in merchant_in if m]
        if needles:
            result = [i for i in result if any(n in (i.get("Company") or "").lower() for n in needles)]

    if institution_in:
        wanted = {x.lower() for x in institution_in}
        result = [i for i in result if (i.get("Institution") or "").lower() in wanted]

    if type_in:
        wanted = {x.lower() for x in type_in}
        result = [i for i in result if (i.get("TransactionType") or "").lower() in wanted]

    if min_amount is not None:
        result = [i for i in result if float(i.get("Amount") or 0) >= min_amount]
    if max_amount is not None:
        result = [i for i in result if float(i.get("Amount") or 0) <= max_amount]

    return result


@router.post(
    "/transactions/search-by-filter",
    response_model=SearchResponse,
    operation_id="searchTransactionsByFilter",
    summary="Cross-month transaction search with array-shaped filters (POST body)",
)
async def search_transactions_by_filter(
    body: SearchByFilterRequest,
    summary: ISpendingSummary = Depends(get_spending_summary),
):
    """POST sibling to ``GET /transactions/search``.

    Accepts ``merchant_in``, ``category_in``, ``institution_in``, ``type_in``
    arrays (any-of) plus the same amount range and visibility flags. Use
    when URL-encoding many filter values is awkward (e.g. an agent passing
    a list of 20 merchants).
    """
    month_keys = generate_month_keys(body.from_month, body.to_month, max_months=_MAX_MONTHS)

    results = await asyncio.gather(
        *[run_sync(summary.query_month, ym, TRANSACTION_LIST_PROJECTION, PROJECTION_NAMES) for ym in month_keys]
    )
    all_items: list[TransactionItem] = []
    for month_items in results:
        all_items.extend(month_items)

    filtered = _filter_items_by_lists(
        all_items,
        category_in=body.category_in,
        merchant_in=body.merchant_in,
        institution_in=body.institution_in,
        type_in=body.type_in,
        min_amount=body.min_amount,
        max_amount=body.max_amount,
        include_ignored=body.include_ignored,
        include_deleted=body.include_deleted,
    )
    filtered.sort(key=lambda x: x.get("DateFileName", ""), reverse=True)

    total_matching = len(filtered)
    capped = total_matching > _WEB_CAP
    display = filtered[:_WEB_CAP] if capped else filtered

    return SearchResponse(
        transactions=[to_transaction_response(i) for i in display],
        summary=_build_summary(filtered, len(month_keys)),
        capped=capped,
        total_matching=total_matching,
    )


def _strip_tz(date_str: str | None) -> str:
    """Strip timezone suffix from date string for CSV."""
    if not date_str:
        return ""
    return TZ_ABBREV_SUFFIX_RE.sub("", date_str)


def _search_row(item: Mapping[str, Any]) -> list[Any]:
    amt = decimal_to_float(item.get("Amount"))
    return [
        _strip_tz(item.get("Date")),
        amt if amt is not None else "",
        item.get("Company", ""),
        item.get("Category", ""),
        item.get("Institution", ""),
        item.get("TransactionType", ""),
        item.get("Name", ""),
        item.get("Comment", ""),
        item.get("StatementSource", ""),
        "true" if item.get("Ignored") else "false",
    ]


def _parse_statement_source(raw: Any) -> dict[str, Any]:
    """StatementSource is persisted as a JSON string; unpack to a dict (empty on failure)."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _backup_row(item: Mapping[str, Any]) -> list[Any]:
    """Extend the search row with all round-trip fields."""
    base = _search_row(item)
    audit = item.get("CategoryAudit") or {}
    stmt = _parse_statement_source(item.get("StatementSource"))
    confidence = audit.get("confidence")
    confidence_out: Any = decimal_to_float(confidence) if confidence is not None else ""

    return [
        *base,
        item.get("ForwardedTo", ""),
        item.get("DateFileName", ""),
        item.get("TransactionHash", ""),
        audit.get("source", ""),
        audit.get("reviewed_at", ""),
        audit.get("matched_rule", ""),
        confidence_out,
        audit.get("tier", "") or "",
        audit.get("previous_category", "") or "",
        audit.get("previous_source", "") or "",
        audit.get("model", "") or "",
        audit.get("fallback_reason", "") or "",
        audit.get("schema_version", "") if audit.get("schema_version") is not None else "",
        item.get("DeletedAt", "") or "",
        item.get("Subject", "") or "",
        item.get("FromName", "") or "",
        item.get("FromEmail", "") or "",
        item.get("ToName", "") or "",
        item.get("ToEmail", "") or "",
        item.get("FileName", "") or "",
        item.get("Body", "") or "",
        stmt.get("institution", "") or "",
        stmt.get("account_type", "") or "",
        stmt.get("period_start", "") or "",
        stmt.get("period_end", "") or "",
        stmt.get("pdf_path", "") or "",
        # SQLite-only — DynamoDB rows never carry this, so the column is blank
        # for DynamoDB backups. row_to_item() maps it from the SQLite column.
        item.get("CreatedAt", "") or "",
    ]


def _generate_csv(items: Sequence[Mapping[str, Any]], flavor: CsvFlavor = "search") -> Iterator[str]:
    """Yield CSV rows from filtered items.

    `flavor="search"` writes the 10-column display CSV used by the Search-tab
    export. `flavor="backup"` writes a superset that round-trips every
    authoritative field on the transaction row (identity keys, CategoryAudit,
    trash state, email/statement provenance).
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    headers = SEARCH_CSV_COLUMNS if flavor == "search" else BACKUP_CSV_COLUMNS
    row_fn = _search_row if flavor == "search" else _backup_row

    writer.writerow(headers)
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)

    for item in items:
        writer.writerow(row_fn(item))
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)


@router.get(
    "/transactions/export",
    response_class=StreamingResponse,
    operation_id="exportTransactionsCsv",
    summary="Stream filtered transactions as CSV",
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV stream of filtered transactions",
        },
    },
)
async def export_transactions(
    summary: ISpendingSummary = Depends(get_spending_summary),
    from_month: str = Query(..., alias="from", pattern=MONTH_PATTERN, description=_DESC_FROM),
    to_month: str = Query(..., alias="to", pattern=MONTH_PATTERN, description=_DESC_TO),
    q: str | None = Query(None, description=_DESC_Q),
    category: str | None = Query(None, description=_DESC_CATEGORY),
    institution: str | None = Query(None, description=_DESC_INSTITUTION),
    company: str | None = Query(None, description=_DESC_COMPANY),
    type: str | None = Query(None, description=_DESC_TYPE),  # noqa: A002 — public query-param name in the API contract
    min_amount: float | None = Query(None, description=_DESC_MIN_AMOUNT),
    max_amount: float | None = Query(None, description=_DESC_MAX_AMOUNT),
    include_ignored: bool = Query(False, description=_DESC_INCLUDE_IGNORED),
    include_deleted: bool = Query(False, description=_DESC_INCLUDE_DELETED),
):
    month_keys = generate_month_keys(from_month, to_month, max_months=_MAX_MONTHS)

    filtered = await _fetch_and_filter(
        summary,
        month_keys,
        category=category,
        company=company,
        institution=institution,
        txn_type=type,
        min_amount=min_amount,
        max_amount=max_amount,
        include_ignored=include_ignored,
        include_deleted=include_deleted,
        q=q,
    )

    return StreamingResponse(
        _generate_csv(filtered),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=transactions_{from_month}_to_{to_month}.csv"},
    )
