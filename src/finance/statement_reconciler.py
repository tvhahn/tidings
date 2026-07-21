"""Three-tier reconciliation engine for statement transactions against DynamoDB records."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.finance.category_resolver import resolve_override
from src.finance.category_suggest import CategorySuggester
from src.finance.config_loader import get_category_overrides, get_override_context
from src.finance.embedding_cache import EmbeddingCache
from src.finance.openai_client import OpenAIClient
from src.finance.protocols import ISpendingSummary

logger = logging.getLogger(__name__)

# Statement types → compatible DynamoDB TransactionTypes
STATEMENT_TO_DB_TYPE_MAP = {
    "withdrawal": {"purchase", "withdrawal", "preauth"},
    "deposit": {"e-transfer", "deposit"},
}


@dataclass
class MatchedTransaction:
    index: int  # position in the input `transactions` list — row identity for the API layer
    statement_txn: dict[str, Any]
    db_item: dict[str, Any]
    company_differs: bool
    cleaned_description: str
    raw_description: str
    suggested_category: str = ""


@dataclass
class AmbiguousTransaction:
    index: int
    statement_txn: dict[str, Any]
    candidates: list[dict[str, Any]]
    reason: str
    cleaned_description: str = ""
    raw_description: str = ""
    suggested_category: str = "miscellaneous"


@dataclass
class NewTransaction:
    index: int
    statement_txn: dict[str, Any]
    cleaned_description: str
    raw_description: str
    suggested_category: str


@dataclass
class SuspectedDuplicate:
    index: int
    statement_txn: dict[str, Any]
    db_item: dict[str, Any]
    cleaned_description: str
    raw_description: str
    suggested_category: str
    reason: str  # e.g., "type mismatch: withdrawal ≠ e-transfer"


@dataclass
class PreviouslyImportedTransaction:
    index: int
    statement_txn: dict[str, Any]
    db_item: dict[str, Any]
    cleaned_description: str
    raw_description: str
    suggested_category: str = ""


@dataclass
class ReconcileResult:
    matched: list[MatchedTransaction] = field(default_factory=list)
    ambiguous: list[AmbiguousTransaction] = field(default_factory=list)
    suspected_duplicates: list[SuspectedDuplicate] = field(default_factory=list)
    new: list[NewTransaction] = field(default_factory=list)
    previously_imported: list[PreviouslyImportedTransaction] = field(default_factory=list)


def _date_str_to_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD to a datetime object."""
    return datetime.strptime(date_str, "%Y-%m-%d")  # noqa: DTZ007 — date-only value, compared date-to-date


def _db_date_to_date(db_date: str) -> datetime | None:
    """Extract date from DynamoDB Date field (MM/DD/YYYY HH:MM TZ)."""
    try:
        parts = db_date.split()
        return datetime.strptime(parts[0], "%m/%d/%Y")  # noqa: DTZ007 — date-only value, compared date-to-date
    except (ValueError, IndexError):
        return None


def _types_compatible(stmt_type: str, db_type: str | None) -> bool:
    """Check if statement type is compatible with DB transaction type."""
    if not db_type:
        return False
    compatible = STATEMENT_TO_DB_TYPE_MAP.get(stmt_type, set())
    return db_type.lower() in compatible


# DB types that are definitively inflows or outflows
_DB_INFLOW_TYPES = {"deposit"}
_DB_OUTFLOW_TYPES = {"purchase", "withdrawal", "preauth"}
# Note: "e-transfer" is intentionally excluded — it can be sent (outflow) or received (inflow)


def _same_direction(stmt_type: str, db_type: str) -> bool:
    """Check if statement and DB types could represent the same money direction.

    Returns False only when we can definitively prove opposite directions:
    - statement deposit (inflow) vs DB purchase/withdrawal/preauth (outflow)
    - statement withdrawal (outflow) vs DB deposit (inflow)
    """
    if stmt_type == "withdrawal":
        return db_type.lower() not in _DB_INFLOW_TYPES
    if stmt_type == "deposit":
        return db_type.lower() not in _DB_OUTFLOW_TYPES
    return True


def _suggest_category(company: str) -> str:
    """Look up category via the tiered resolver, default to miscellaneous."""
    overrides, aliases = get_override_context()
    match = resolve_override(company, overrides, aliases=aliases)
    return match.category.lower() if match else "miscellaneous"


def _get_overlapping_months(period_start: str, period_end: str) -> list[str]:
    """Get all YYYY-MM months that overlap with the statement period."""
    start = _date_str_to_date(period_start)
    end = _date_str_to_date(period_end)
    months = set()
    current = start.replace(day=1)
    while current <= end:
        months.add(current.strftime("%Y-%m"))
        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return sorted(months)


def reconcile(
    transactions: list[dict[str, Any]],
    cleaned_descriptions: list[str],
    raw_descriptions: list[str],
    metadata: dict[str, Any],
    spending_summary: ISpendingSummary,
    openai_client: OpenAIClient | None = None,
    embedding_cache: EmbeddingCache | None = None,
) -> ReconcileResult:
    """Reconcile parsed statement transactions against DynamoDB records.

    Args:
        transactions: Parsed transaction dicts from statement parser
        cleaned_descriptions: Cleaned description for each transaction
        raw_descriptions: Raw description for each transaction
        metadata: Statement metadata with period_start, period_end
        spending_summary: SpendingSummary instance for querying DynamoDB
        openai_client: Optional OpenAIClient for embedding-based category suggestion

    Returns:
        ReconcileResult with matched, ambiguous, and new transactions
    """
    result = ReconcileResult()

    period_start = metadata.get("period_start")
    period_end = metadata.get("period_end")
    if not period_start or not period_end:
        # Can't reconcile without date range — mark all as new
        for i, txn in enumerate(transactions):
            result.new.append(
                NewTransaction(
                    index=i,
                    statement_txn=txn,
                    cleaned_description=cleaned_descriptions[i],
                    raw_description=raw_descriptions[i],
                    suggested_category=_suggest_category(raw_descriptions[i]),
                )
            )
        return result

    # Fetch DB transactions for overlapping months
    months = _get_overlapping_months(period_start, period_end)
    db_items = []
    for month in months:
        db_items.extend(spending_summary.query_month(month))

    # Build embedding-based suggester if OpenAI client is available
    overrides = get_category_overrides()
    suggester = CategorySuggester(openai_client, embedding_cache=embedding_cache)
    suggester.build_corpus(overrides, db_items)

    # Compute the expected StatementSource for this statement
    institution = metadata.get("institution", "")
    account_type = metadata.get("account_type", "")
    period_month = period_start[:7] if period_start else ""
    expected_source = f"{institution}_{account_type.title()}_{period_month}"

    # Build secondary index: previously imported items with matching StatementSource
    # keyed by (date_str_YYYY-MM-DD, rounded_amount) for lookup
    prev_imported_index: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for item in db_items:
        if item.get("DeletedAt"):
            continue
        if item.get("StatementSource") != expected_source:
            continue
        db_date_str = item.get("Date")
        db_amount = item.get("Amount")
        if not db_date_str or db_amount is None:
            continue
        dt = _db_date_to_date(db_date_str)
        if dt is None:
            continue
        date_key = dt.strftime("%Y-%m-%d")
        amount_key = round(float(db_amount), 2)
        key = (date_key, amount_key)
        if key not in prev_imported_index:
            prev_imported_index[key] = []
        prev_imported_index[key].append(item)

    # Build lookup index: {(date_str_YYYY-MM-DD, rounded_amount): [db_items]}
    db_index: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for item in db_items:
        if item.get("DeletedAt"):
            continue
        db_date_str = item.get("Date")
        db_amount = item.get("Amount")
        if not db_date_str or db_amount is None:
            continue
        dt = _db_date_to_date(db_date_str)
        if dt is None:
            continue
        date_key = dt.strftime("%Y-%m-%d")
        amount_key = round(float(db_amount), 2)
        key = (date_key, amount_key)
        if key not in db_index:
            db_index[key] = []
        db_index[key].append(item)

    # Track used DB keys to prevent double-matching
    used_keys: set[tuple[str, str]] = set()

    for i, txn in enumerate(transactions):
        stmt_date = txn["date"]  # YYYY-MM-DD
        stmt_amount = round(txn["amount"], 2)
        stmt_type = txn["type"]
        cleaned = cleaned_descriptions[i]
        raw = raw_descriptions[i]

        # --- Pre-Tier: Previously imported from this statement ---
        prev_key = (stmt_date, stmt_amount)
        prev_candidates = prev_imported_index.get(prev_key, [])
        prev_matches = []
        for item in prev_candidates:
            db_key = (item["ForwardedTo"], item["DateFileName"])
            if db_key in used_keys:
                continue
            if _types_compatible(stmt_type, item.get("TransactionType")):
                prev_matches.append(item)

        if len(prev_matches) >= 1:
            db_item = prev_matches[0]
            db_key = (db_item["ForwardedTo"], db_item["DateFileName"])
            used_keys.add(db_key)
            db_cat = (db_item.get("Category") or "miscellaneous").lower()
            company_matches = cleaned.lower() == (db_item.get("Company") or "").lower()
            suggested_cat = db_cat if company_matches else suggester.suggest(raw)
            result.previously_imported.append(
                PreviouslyImportedTransaction(
                    index=i,
                    statement_txn=txn,
                    db_item=db_item,
                    cleaned_description=cleaned,
                    raw_description=raw,
                    suggested_category=suggested_cat,
                )
            )
            continue

        # --- Tier 1: Exact match (same date + amount + compatible type) ---
        exact_key = (stmt_date, stmt_amount)
        candidates = db_index.get(exact_key, [])
        tier1_matches = []
        for item in candidates:
            db_key = (item["ForwardedTo"], item["DateFileName"])
            if db_key in used_keys:
                continue
            if _types_compatible(stmt_type, item.get("TransactionType")):
                tier1_matches.append(item)

        if len(tier1_matches) == 1:
            db_item = tier1_matches[0]
            db_key = (db_item["ForwardedTo"], db_item["DateFileName"])
            used_keys.add(db_key)
            db_company = (db_item.get("Company") or "").lower()
            company_differs = cleaned.lower() != db_company
            db_cat = (db_item.get("Category") or "miscellaneous").lower()
            suggested_cat = suggester.suggest(raw) if company_differs else db_cat
            result.matched.append(
                MatchedTransaction(
                    index=i,
                    statement_txn=txn,
                    db_item=db_item,
                    company_differs=company_differs,
                    cleaned_description=cleaned,
                    raw_description=raw,
                    suggested_category=suggested_cat,
                )
            )
            continue

        if len(tier1_matches) > 1:
            # N:M ambiguity — flag entire group
            result.ambiguous.append(
                AmbiguousTransaction(
                    index=i,
                    statement_txn=txn,
                    candidates=tier1_matches,
                    reason="multiple same-amount matches",
                    cleaned_description=cleaned,
                    raw_description=raw,
                    suggested_category=suggester.suggest(raw),
                )
            )
            continue

        # --- Tier 2: Suspected duplicate (cross-type match, same direction) ---
        # Check exact date + amount candidates that failed type compatibility
        stmt_dt = _date_str_to_date(stmt_date)
        cross_type_match = None
        for item in candidates:
            db_key = (item["ForwardedTo"], item["DateFileName"])
            if db_key in used_keys:
                continue
            db_type = (item.get("TransactionType") or "").lower()
            if db_type and not _types_compatible(stmt_type, db_type) and _same_direction(stmt_type, db_type):
                cross_type_match = item
                break

        # If no exact-date cross-type match, check fuzzy date range (±2 days)
        if not cross_type_match:
            for day_offset in range(-2, 3):
                if day_offset == 0:
                    continue
                check_date = stmt_dt + timedelta(days=day_offset)
                check_key = (check_date.strftime("%Y-%m-%d"), stmt_amount)
                for item in db_index.get(check_key, []):
                    db_key = (item["ForwardedTo"], item["DateFileName"])
                    if db_key in used_keys:
                        continue
                    db_type = (item.get("TransactionType") or "").lower()
                    if db_type and not _types_compatible(stmt_type, db_type) and _same_direction(stmt_type, db_type):
                        cross_type_match = item
                        break
                if cross_type_match:
                    break

        if cross_type_match:
            db_type = (cross_type_match.get("TransactionType") or "unknown").lower()
            reason = f"type mismatch: {stmt_type} ≠ {db_type}"
            result.suspected_duplicates.append(
                SuspectedDuplicate(
                    index=i,
                    statement_txn=txn,
                    db_item=cross_type_match,
                    cleaned_description=cleaned,
                    raw_description=raw,
                    suggested_category=suggester.suggest(raw),
                    reason=reason,
                )
            )
            continue

        # --- Tier 3: Fuzzy match (±2 days + amount + compatible type) ---
        tier3_matches = []
        for day_offset in range(-2, 3):
            if day_offset == 0:
                continue  # Already checked in Tier 1
            check_date = stmt_dt + timedelta(days=day_offset)
            check_key = (check_date.strftime("%Y-%m-%d"), stmt_amount)
            for item in db_index.get(check_key, []):
                db_key = (item["ForwardedTo"], item["DateFileName"])
                if db_key in used_keys:
                    continue
                if _types_compatible(stmt_type, item.get("TransactionType")):
                    tier3_matches.append((item, abs(day_offset)))

        if tier3_matches:
            candidates_list = [m[0] for m in tier3_matches]
            max_offset = max(m[1] for m in tier3_matches)
            reason = f"date off by {max_offset} day{'s' if max_offset > 1 else ''}"
            result.ambiguous.append(
                AmbiguousTransaction(
                    index=i,
                    statement_txn=txn,
                    candidates=candidates_list,
                    reason=reason,
                    cleaned_description=cleaned,
                    raw_description=raw,
                    suggested_category=suggester.suggest(raw),
                )
            )
            continue

        # --- Tier 4: No match → new ---
        suggested_category = suggester.suggest(raw)
        result.new.append(
            NewTransaction(
                index=i,
                statement_txn=txn,
                cleaned_description=cleaned,
                raw_description=raw,
                suggested_category=suggested_category,
            )
        )

    return result
