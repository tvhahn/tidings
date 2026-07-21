"""Statement import schemas."""

from typing import Literal

from pydantic import BaseModel

__all__ = [
    "AmbiguousItem",
    "BulkActionUpdateItem",
    "BulkTransactionUpdate",
    "BulkTransactionUpdateResponse",
    "ImportAction",
    "ImportActionType",
    "ImportByIdRequest",
    "ImportRequest",
    "ImportResponse",
    "MatchedItem",
    "NewItem",
    "PreviouslyImportedItem",
    "RawStatementTxn",
    "ReconcileSummary",
    "StatementDbMatch",
    "StatementDbMatchWithType",
    "StatementDeleteResponse",
    "StatementDetailResponse",
    "StatementListResponse",
    "StatementMetadata",
    "StatementSummaryItem",
    "StatementTransaction",
    "StatementTransactionItem",
    "StatementUploadResponse",
    "SuspectedDuplicateItem",
    "TransactionActionUpdate",
    "TransactionActionUpdateResponse",
]


class RawStatementTxn(BaseModel):
    """Raw transaction emitted by a statement parser (PDF/CSV).

    Used inside reconciliation items (MatchedItem.statement_txn etc.) where the
    cleaned (display) description is carried on the parent item, not the txn
    itself.
    """

    date: str
    description: str
    amount: float
    type: Literal["withdrawal", "deposit"]
    balance: float | None


class StatementTransaction(RawStatementTxn):
    """Top-level statement row, enriched with the cleaned display description.

    Used for `StatementUploadResponse.transactions` — the full list shown in
    the upload preview before reconciliation tiers are applied.
    """

    cleaned_description: str


class StatementMetadata(BaseModel):
    institution: str
    account_type: str
    period_start: str | None
    period_end: str | None
    transaction_count: int
    # True when the AI fallback (statement_parser_ai) produced the rows instead
    # of a deterministic bank parser — surfaced so the review UI can flag it.
    parsed_with_ai: bool = False


class StatementDbMatch(BaseModel):
    """Reference to an existing transaction matched against a statement row."""

    forwarded_to: str
    date_file_name: str
    company: str | None
    amount: float | None
    category: str | None


class StatementDbMatchWithType(StatementDbMatch):
    """Variant carrying the existing transaction's type — used by the
    suspected-duplicate flow so the frontend can show both the statement's
    inferred type and the existing record's type."""

    transaction_type: str | None


class MatchedItem(BaseModel):
    index: int
    row_id: str
    statement_txn: RawStatementTxn
    db_match: StatementDbMatch
    company_differs: bool
    cleaned_description: str
    raw_description: str
    suggested_category: str


class AmbiguousItem(BaseModel):
    index: int
    row_id: str
    statement_txn: RawStatementTxn
    candidates: list[StatementDbMatch]
    reason: str
    cleaned_description: str
    raw_description: str
    suggested_category: str
    enrichable: bool


class NewItem(BaseModel):
    index: int
    row_id: str
    statement_txn: RawStatementTxn
    cleaned_description: str
    raw_description: str
    suggested_category: str


class SuspectedDuplicateItem(BaseModel):
    index: int
    row_id: str
    statement_txn: RawStatementTxn
    db_match: StatementDbMatchWithType
    cleaned_description: str
    raw_description: str
    suggested_category: str
    reason: str


class PreviouslyImportedItem(BaseModel):
    index: int
    row_id: str
    statement_txn: RawStatementTxn
    db_match: StatementDbMatch
    cleaned_description: str
    raw_description: str
    suggested_category: str


class ReconcileSummary(BaseModel):
    total_parsed: int
    matched_count: int
    ambiguous_count: int
    suspected_duplicate_count: int = 0
    new_count: int
    previously_imported_count: int = 0
    imported_count: int = 0
    enriched_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0


class StatementUploadResponse(BaseModel):
    statement_id: str
    transactions: list[StatementTransaction]
    metadata: StatementMetadata
    matched: list[MatchedItem]
    ambiguous: list[AmbiguousItem]
    suspected_duplicates: list[SuspectedDuplicateItem]
    new: list[NewItem]
    previously_imported: list[PreviouslyImportedItem]
    summary: ReconcileSummary


ImportActionType = Literal["import", "skip", "enrich", "update"]


class ImportAction(BaseModel):
    index: int
    action: ImportActionType
    category: str | None = None
    company: str | None = None
    forwarded_to: str | None = None
    date_file_name: str | None = None


class ImportRequest(BaseModel):
    actions: list[ImportAction]
    metadata: StatementMetadata
    # The frontend echoes back the rows it received in
    # StatementUploadResponse.transactions — same model, now enforced.
    transactions: list[StatementTransaction]
    filename: str
    statement_id: str | None = None


class ImportResponse(BaseModel):
    imported: int
    skipped: int
    duplicates: int
    enriched: int = 0
    updated: int = 0


class StatementSummaryItem(BaseModel):
    id: str
    filename: str
    institution: str
    account_type: str
    period_start: str | None
    period_end: str | None
    uploaded_at: str
    updated_at: str
    completed_at: str | None
    total_parsed: int
    matched_count: int
    ambiguous_count: int
    suspected_duplicate_count: int
    new_count: int
    previously_imported_count: int
    imported_count: int
    enriched_count: int
    updated_count: int
    skipped_count: int
    duplicate_count: int
    status: Literal["pending_review", "in_progress", "complete"]
    parsed_with_ai: bool = False


class StatementListResponse(BaseModel):
    statements: list[StatementSummaryItem]
    count: int


class StatementTransactionItem(BaseModel):
    tx_index: int
    row_id: str  # stable per-row id; URL key for PATCH (replaces positional tx_index)
    reconcile_tier: Literal["matched", "ambiguous", "suspected_duplicate", "new", "previously_imported"]
    date: str
    raw_description: str
    cleaned_description: str
    amount: float
    type: str
    balance: float | None
    db_forwarded_to: str | None
    db_date_file_name: str | None
    db_company: str | None
    db_amount: float | None
    db_category: str | None
    db_transaction_type: str | None
    company_differs: bool
    enrichable: bool
    reason: str | None
    candidates: list[StatementDbMatch] | None
    suggested_category: str
    action: str
    edited_company: str | None
    edited_category: str | None
    action_result: str | None
    acted_at: str | None


class StatementDetailResponse(BaseModel):
    id: str
    filename: str
    institution: str
    account_type: str
    period_start: str | None
    period_end: str | None
    uploaded_at: str
    updated_at: str
    completed_at: str | None
    total_parsed: int
    matched_count: int
    ambiguous_count: int
    suspected_duplicate_count: int
    new_count: int
    previously_imported_count: int
    imported_count: int
    enriched_count: int
    updated_count: int
    skipped_count: int
    duplicate_count: int
    status: str
    parsed_with_ai: bool = False
    transactions: list[StatementTransactionItem]


class TransactionActionUpdate(BaseModel):
    action: ImportActionType
    company: str | None = None
    category: str | None = None


class TransactionActionUpdateResponse(BaseModel):
    ok: bool
    tx_index: int
    row_id: str
    action: str


class BulkActionUpdateItem(BaseModel):
    tx_index: int
    action: ImportActionType
    company: str | None = None
    category: str | None = None


class BulkTransactionUpdate(BaseModel):
    updates: list[BulkActionUpdateItem]


class BulkTransactionUpdateResponse(BaseModel):
    ok: bool
    updated: int


class ImportByIdRequest(BaseModel):
    statement_id: str


class StatementDeleteResponse(BaseModel):
    ok: bool
