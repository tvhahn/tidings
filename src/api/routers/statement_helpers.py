"""Helper functions for statement import endpoints."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from src.api.models import StatementMetadata
from src.finance.app_config import get_config
from src.finance.app_timezone import now_local
from src.finance.statement_parser import select_parser
from src.finance.statement_parser_ai import StatementAIError, parse_statement_with_ai
from src.finance.statement_parser_base import StatementParseResult
from src.finance.statement_reconciler import ReconcileResult, reconcile
from src.finance.user_mapping import get_forwarded_to_addresses
from src.finance.user_mapping import get_user_id as _get_user_id

if TYPE_CHECKING:
    from src.finance.embedding_cache import EmbeddingCache
    from src.finance.openai_client import OpenAIClient
    from src.finance.protocols import ISpendingSummary

__all__ = [
    "STATEMENTS_RAW_DIR",
    "ReconciliationItems",
    # Exported (despite the underscore) for the statements router's write-side
    # traversal guard; pyright treats __all__ membership as an intentional export.
    "_safe_filename_component",
    "append_import_history",
    "build_reconciliation_items",
    "build_transaction_rows",
    "get_forwarded_to",
    "get_user_id",
    "parse_and_reconcile",
    "standardized_pdf_name",
    "was_category_edited",
]

STATEMENTS_RAW_DIR = Path("data/raw/statements")

logger = logging.getLogger(__name__)

# The five-tuple `build_reconciliation_items` returns:
# (matched, ambiguous, new, previously_imported, suspected_duplicates), each a
# list of dicts ready for Pydantic construction or SQLite persistence.
ReconciliationItems = tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]

# The router-layer transport seam. Handlers pass their module-level `run_sync`
# (the one `tests/conftest.py::mock_run_sync` patches) so the off-thread parse +
# reconcile calls stay mockable exactly as they were when they lived inline in
# the router.
RunSync = Callable[..., Awaitable[Any]]


async def _parse_with_ai_or_422(
    pdf_bytes: bytes,
    parser_error: str,
    openai_client: "OpenAIClient | None",
) -> StatementParseResult:
    """AI fallback for a failed deterministic parse; 422 when disabled or failed."""
    if not get_config().get("ai_statement_parsing_enabled", False):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{parser_error}. If this bank has no built-in parser, turn on "
                '"Parse statements with AI" in Settings → Intelligence to read it '
                "with your AI provider."
            ),
        )
    try:
        result = await parse_statement_with_ai(pdf_bytes, openai_client=openai_client)
    except StatementAIError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    logger.info(
        "AI statement fallback parsed %d transactions (%s)",
        len(result.transactions),
        result.metadata.get("institution"),
    )
    return result


async def parse_and_reconcile(
    pdf_bytes: bytes,
    *,
    run_sync: RunSync,
    summary: "ISpendingSummary",
    openai_client: "OpenAIClient | None",
    embedding_cache: "EmbeddingCache",
) -> tuple[StatementParseResult, ReconcileResult, ReconciliationItems]:
    """Run the shared parse -> reconcile -> build-items pipeline.

    This is the byte-identical middle that ``upload_statement`` and
    ``reparse_statement`` share: pick a deterministic parser (AI fallback on
    ``ValueError``), reconcile the parsed transactions against stored ones, and
    fold the reconcile result into the five response-item lists. Each handler
    keeps its own tail — PDF acquisition/save, edit carry-over, statement_dict
    construction, and response shaping — because those genuinely differ.

    ``run_sync`` is injected rather than imported so the caller's patchable
    transport seam is preserved. Raises ``HTTPException(422)`` when the
    deterministic parse fails and AI fallback is unavailable or errors.
    """
    parser = select_parser(pdf_bytes)
    try:
        result = await run_sync(parser.parse, pdf_bytes)
    except ValueError as e:
        result = await _parse_with_ai_or_422(pdf_bytes, str(e), openai_client)

    reconcile_result = await run_sync(
        reconcile,
        result.transactions,
        result.cleaned_descriptions,
        result.raw_descriptions,
        result.metadata,
        summary,
        openai_client,
        embedding_cache,
    )

    items = build_reconciliation_items(reconcile_result, result.transactions, result.raw_descriptions)
    return result, reconcile_result, items


def get_forwarded_to() -> str:
    """Get the first ForwardedTo address from user mappings."""
    addresses = get_forwarded_to_addresses()
    if not addresses:
        raise HTTPException(status_code=500, detail="No user mappings configured")
    return addresses[0]


def get_user_id(forwarded_to: str) -> str | None:
    """Get UserId for a ForwardedTo address."""
    return _get_user_id(forwarded_to)


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def _safe_filename_component(value: str) -> str:
    """Reduce untrusted text to a single safe filename component.

    Strips any path segments (Starlette passes the multipart filename
    through verbatim, including `../` sequences) and whitelists to
    filesystem-safe characters. Never returns an empty string.

    Deliberately distinct from ``src.api.utils.sanitize_filename``: this variant
    keeps a wider charset (spaces) because it feeds stored statement artifact
    names. Both strip path components; see there for the attachments/tax variant.
    """
    base = Path(value).name  # drops directory components, incl. `..`
    cleaned = _FILENAME_SAFE_RE.sub("_", base).strip("._ ")
    return cleaned or "statement"


def standardized_pdf_name(
    institution: str,
    account_type: str,
    period_start: str | None,
    period_end: str | None,
    original_filename: str,
) -> str:
    """Build a standardized PDF filename from statement metadata."""
    institution = _safe_filename_component(institution)
    acct = _safe_filename_component(account_type.title())
    if period_start and period_end:
        return f"{institution}_{acct}_{period_start}_to_{period_end}.pdf"
    return f"{institution}_{acct}_{_safe_filename_component(original_filename)}"


def was_category_edited(tx_lookup: dict[int, dict[str, Any]], tx_index: int) -> bool:
    """Check if user explicitly changed the category from suggested default."""
    row = tx_lookup.get(tx_index)
    if not row or not row.get("edited_category"):
        return False
    suggested = (row.get("suggested_category") or "miscellaneous").lower()
    edited = row["edited_category"].lower()
    return edited != suggested


def _db_match_dict(db_item: dict[str, Any], include_txn_type: bool = False) -> dict[str, Any]:
    """Build a db_match dict from a DynamoDB/SQLite item, converting Decimal amounts."""
    from src.finance.decimal_utils import decimal_to_float

    result = {
        "forwarded_to": db_item["ForwardedTo"],
        "date_file_name": db_item["DateFileName"],
        "company": db_item.get("Company"),
        "amount": decimal_to_float(db_item.get("Amount")),
        "category": db_item.get("Category"),
    }
    if include_txn_type:
        result["transaction_type"] = db_item.get("TransactionType")
    return result


def build_reconciliation_items(
    reconcile_result: ReconcileResult,
    transactions: list[dict[str, Any]],
    raw_descriptions: list[str] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Build reconciliation response items from a ReconcileResult.

    Returns (matched, ambiguous, new, previously_imported, suspected_duplicates)
    as lists of dicts ready for Pydantic model construction or SQLite persistence.

    Each item carries a stable `row_id` (see `src/finance/statement_store.py`).
    The id is computed against the same canonical input the SQLite layer
    uses on save, so the response and the persisted rows agree by index.
    """
    from src.finance.decimal_utils import decimal_to_float
    from src.finance.statement_store import _assign_row_ids

    # Pre-compute row_ids for every parsed transaction so each response Item
    # below can attach the same id the persisted row will carry. Uses the
    # parser's `raw_descriptions[i]` when supplied — that's the same string
    # `build_transaction_rows` writes as `raw_description` and the same
    # value `_assign_row_ids` runs on at save-time, so the response and the
    # persisted rows agree on the id.
    raws = raw_descriptions or [str(t.get("description") or "") for t in transactions]
    row_id_inputs = [
        {
            "date": txn.get("date") or "",
            "amount": txn.get("amount"),
            "raw_description": raws[i] if i < len(raws) else "",
        }
        for i, txn in enumerate(transactions)
    ]
    _assign_row_ids(row_id_inputs)
    row_id_by_index = [r["row_id"] for r in row_id_inputs]

    matched: list[dict[str, Any]] = []
    for m in reconcile_result.matched:
        idx = m.index
        matched.append(
            {
                "index": idx,
                "row_id": row_id_by_index[idx],
                "statement_txn": m.statement_txn,
                "db_match": _db_match_dict(m.db_item),
                "company_differs": m.company_differs,
                "cleaned_description": m.cleaned_description,
                "raw_description": m.raw_description,
                "suggested_category": m.suggested_category,
            }
        )

    ambiguous: list[dict[str, Any]] = []
    for a in reconcile_result.ambiguous:
        idx = a.index
        candidates: list[dict[str, Any]] = [
            {
                "forwarded_to": c["ForwardedTo"],
                "date_file_name": c["DateFileName"],
                "company": c.get("Company"),
                "amount": decimal_to_float(c.get("Amount")),
                "category": c.get("Category"),
            }
            for c in a.candidates
        ]
        ambiguous.append(
            {
                "index": idx,
                "row_id": row_id_by_index[idx],
                "statement_txn": a.statement_txn,
                "candidates": candidates,
                "reason": a.reason,
                "cleaned_description": a.cleaned_description,
                "raw_description": a.raw_description,
                "suggested_category": a.suggested_category,
                "enrichable": len(candidates) == 1,
            }
        )

    new: list[dict[str, Any]] = []
    for n in reconcile_result.new:
        idx = n.index
        new.append(
            {
                "index": idx,
                "row_id": row_id_by_index[idx],
                "statement_txn": n.statement_txn,
                "cleaned_description": n.cleaned_description,
                "raw_description": n.raw_description,
                "suggested_category": n.suggested_category,
            }
        )

    previously_imported: list[dict[str, Any]] = []
    for p in reconcile_result.previously_imported:
        idx = p.index
        previously_imported.append(
            {
                "index": idx,
                "row_id": row_id_by_index[idx],
                "statement_txn": p.statement_txn,
                "db_match": _db_match_dict(p.db_item),
                "cleaned_description": p.cleaned_description,
                "raw_description": p.raw_description,
                "suggested_category": p.suggested_category,
            }
        )

    suspected_duplicates: list[dict[str, Any]] = []
    for sd in reconcile_result.suspected_duplicates:
        idx = sd.index
        suspected_duplicates.append(
            {
                "index": idx,
                "row_id": row_id_by_index[idx],
                "statement_txn": sd.statement_txn,
                "db_match": _db_match_dict(sd.db_item, include_txn_type=True),
                "cleaned_description": sd.cleaned_description,
                "raw_description": sd.raw_description,
                "suggested_category": sd.suggested_category,
                "reason": sd.reason,
            }
        )

    return matched, ambiguous, new, previously_imported, suspected_duplicates


def build_transaction_rows(
    matched: list[dict[str, Any]],
    ambiguous: list[dict[str, Any]],
    new: list[dict[str, Any]],
    previously_imported: list[dict[str, Any]],
    suspected_duplicates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Flatten reconciliation results into rows for SQLite storage."""
    rows: list[dict[str, Any]] = []

    for item in matched:
        db = item.get("db_match", {})
        rows.append(
            {
                "tx_index": item["index"],
                "reconcile_tier": "matched",
                "date": item["statement_txn"]["date"],
                "raw_description": item.get("raw_description", ""),
                "cleaned_description": item.get("cleaned_description", ""),
                "amount": item["statement_txn"]["amount"],
                "type": item["statement_txn"].get("type", "withdrawal"),
                "balance": item["statement_txn"].get("balance"),
                "db_forwarded_to": db.get("forwarded_to"),
                "db_date_file_name": db.get("date_file_name"),
                "db_company": db.get("company"),
                "db_amount": db.get("amount"),
                "db_category": db.get("category"),
                "company_differs": item.get("company_differs", False),
                "enrichable": False,
                "suggested_category": item.get("suggested_category", ""),
            }
        )

    for item in ambiguous:
        candidates = item.get("candidates", [])
        first_candidate = candidates[0] if candidates else {}
        rows.append(
            {
                "tx_index": item["index"],
                "reconcile_tier": "ambiguous",
                "date": item["statement_txn"]["date"],
                "raw_description": item.get("raw_description", ""),
                "cleaned_description": item.get("cleaned_description", ""),
                "amount": item["statement_txn"]["amount"],
                "type": item["statement_txn"].get("type", "withdrawal"),
                "balance": item["statement_txn"].get("balance"),
                "db_forwarded_to": first_candidate.get("forwarded_to"),
                "db_date_file_name": first_candidate.get("date_file_name"),
                "db_company": first_candidate.get("company"),
                "db_amount": first_candidate.get("amount"),
                "db_category": first_candidate.get("category"),
                "company_differs": False,
                "enrichable": item.get("enrichable", False),
                "reason": item.get("reason", ""),
                "candidates_json": json.dumps(candidates),
                "suggested_category": item.get("suggested_category", "miscellaneous"),
            }
        )

    rows.extend(
        {
            "tx_index": item["index"],
            "reconcile_tier": "new",
            "date": item["statement_txn"]["date"],
            "raw_description": item.get("raw_description", ""),
            "cleaned_description": item.get("cleaned_description", ""),
            "amount": item["statement_txn"]["amount"],
            "type": item["statement_txn"].get("type", "withdrawal"),
            "balance": item["statement_txn"].get("balance"),
            "suggested_category": item.get("suggested_category", "miscellaneous"),
        }
        for item in new
    )

    for item in previously_imported:
        db = item.get("db_match", {})
        rows.append(
            {
                "tx_index": item["index"],
                "reconcile_tier": "previously_imported",
                "date": item["statement_txn"]["date"],
                "raw_description": item.get("raw_description", ""),
                "cleaned_description": item.get("cleaned_description", ""),
                "amount": item["statement_txn"]["amount"],
                "type": item["statement_txn"].get("type", "withdrawal"),
                "balance": item["statement_txn"].get("balance"),
                "db_forwarded_to": db.get("forwarded_to"),
                "db_date_file_name": db.get("date_file_name"),
                "db_company": db.get("company"),
                "db_amount": db.get("amount"),
                "db_category": db.get("category"),
                "suggested_category": item.get("suggested_category", ""),
            }
        )

    for item in suspected_duplicates or []:
        db = item.get("db_match", {})
        rows.append(
            {
                "tx_index": item["index"],
                "reconcile_tier": "suspected_duplicate",
                "date": item["statement_txn"]["date"],
                "raw_description": item.get("raw_description", ""),
                "cleaned_description": item.get("cleaned_description", ""),
                "amount": item["statement_txn"]["amount"],
                "type": item["statement_txn"].get("type", "withdrawal"),
                "balance": item["statement_txn"].get("balance"),
                "db_forwarded_to": db.get("forwarded_to"),
                "db_date_file_name": db.get("date_file_name"),
                "db_company": db.get("company"),
                "db_amount": db.get("amount"),
                "db_category": db.get("category"),
                "db_transaction_type": db.get("transaction_type"),
                "reason": item.get("reason", ""),
                "suggested_category": item.get("suggested_category", "miscellaneous"),
            }
        )

    return rows


def append_import_history(
    filename: str,
    metadata: StatementMetadata,
    parsed_count: int,
    imported: int,
    skipped: int,
    duplicates: int,
):
    """Append an import record to data/processed/statements/imports.json."""
    history_dir = Path("data/processed/statements")
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "imports.json"

    records = []
    if history_file.exists():
        try:
            records = json.loads(history_file.read_text())
        except (json.JSONDecodeError, OSError):
            records = []

    records.append(
        {
            "imported_at": now_local().isoformat(),
            "institution": metadata.institution,
            "account_type": metadata.account_type,
            "period_start": metadata.period_start,
            "period_end": metadata.period_end,
            "filename": filename,
            "parsed_count": parsed_count,
            "matched_count": parsed_count - imported - skipped - duplicates,
            "imported_count": imported,
            "skipped_count": skipped,
        }
    )

    history_file.write_text(json.dumps(records, indent=2))
