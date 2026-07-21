"""Transaction request/response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.models.ingestion import TransactionType

__all__ = [
    "AttentionListResponse",
    "BulkCategoryUpdateItem",
    "BulkCategoryUpdateRequest",
    "BulkCategoryUpdateResponse",
    "BulkCategoryUpdateResult",
    "CategoriesResponse",
    "CategoryAudit",
    "CategoryUpdateRequest",
    "CategoryUpdateResponse",
    "CombinedTransactionsResponse",
    "CommentRequest",
    "CommentResponse",
    "DeleteRequest",
    "DeleteResponse",
    "ExtractionAudit",
    "IgnoreRequest",
    "IgnoreResponse",
    "LatestTimestampResponse",
    "PermanentDeleteResponse",
    "ReviewResponse",
    "TransactionContext",
    "TransactionDetailResponse",
    "TransactionFieldsUpdateRequest",
    "TransactionFieldsUpdateResponse",
    "TransactionListResponse",
    "TransactionResponse",
]


class TransactionContext(BaseModel):
    category_month_total: float
    merchant_month_count: int
    category_budget_target: float | None
    category_budget_pct: float | None


class CategoryAudit(BaseModel):
    source: str | None = None
    tier: str | None = None
    matched_rule: str | None = None
    confidence: float | None = None
    reviewed_at: str | None = None
    previous_category: str | None = None
    previous_source: str | None = None
    model: str | None = None
    fallback_reason: str | None = None
    schema_version: int | None = None


class ExtractionAudit(BaseModel):
    """Provenance for a transaction recovered via the AI extraction fallback.

    Present only on rows the parsers couldn't read but the constrained LLM
    extraction recovered (parse-failure-quarantine path). Absent on
    parser-extracted and statement-imported rows.
    """

    method: str | None = None
    model: str | None = None
    validated: bool | None = None
    extracted_at: str | None = None
    schema_version: int | None = None


class TransactionResponse(BaseModel):
    tx_id: str  # URL-safe surrogate; see src/finance/tx_id.py
    forwarded_to: str
    date_file_name: str
    date: str | None
    amount: float | None
    company: str | None
    category: str | None
    institution: str | None
    transaction_type: str | None
    name: str | None
    category_audit: CategoryAudit | None = None
    extraction_audit: ExtractionAudit | None = None
    ignored: bool
    comment: str | None
    deleted_at: str | None
    context: TransactionContext | None = None
    statement_source: str | None = None


class TransactionDetailResponse(BaseModel):
    tx_id: str
    forwarded_to: str
    date_file_name: str
    subject: str | None
    body: str | None
    from_name: str | None
    from_email: str | None
    to_name: str | None
    to_email: str | None


class TransactionListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "month": "2026-04",
                    "count": 2,
                    "transactions": [
                        {
                            "tx_id": "ZGVmYXVsdEBsb2NhbHwyMDI2LjA0LjE1XzA5LjMyX2VtYWlsXzAxLmVtbA",
                            "forwarded_to": "default@local",
                            "date_file_name": "2026.04.15_09.32_email_01.eml",
                            "date": "04/15/2026 09:32 -0700",
                            "amount": 42.31,
                            "company": "WHOLE FOODS",
                            "category": "groceries",
                            "institution": "RBC",
                            "transaction_type": "purchase",
                            "name": "default",
                            "ignored": False,
                            "comment": None,
                            "deleted_at": None,
                        }
                    ],
                }
            ]
        }
    )
    month: str
    count: int
    transactions: list[TransactionResponse]


class AttentionListResponse(BaseModel):
    month: str
    count: int
    transactions: list[TransactionResponse]


class CombinedTransactionsResponse(BaseModel):
    month: str
    transactions: TransactionListResponse
    attention: AttentionListResponse
    trash: TransactionListResponse


TransactionState = Literal["active", "ignored", "trashed"]


class CategoryUpdateRequest(BaseModel):
    """Partial PATCH for a transaction.

    Any field omitted = no change. ``state`` consolidates the three legacy
    ``/review``, ``/ignore``, ``/delete`` POST endpoints into a single
    state machine. ``category`` is the original purpose of this endpoint
    and remains supported.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"category": "Groceries"},
                {"state": "ignored"},
                {"state": "trashed"},
                {"reviewed": True},
                {"category": "Restaurants", "reviewed": True},
            ]
        }
    )
    category: str | None = None
    state: TransactionState | None = None
    reviewed: bool | None = None


class CategoryUpdateResponse(BaseModel):
    """Response shape for ``PATCH /transactions/{tx_id}``.

    ``old_category`` / ``new_category`` are populated only when the request
    included ``category``. ``state`` / ``reviewed`` / ``deleted_at`` are
    populated only when the corresponding request fields were set.
    """

    tx_id: str
    forwarded_to: str
    date_file_name: str
    old_category: str | None = None
    new_category: str | None = None
    state: TransactionState | None = None
    reviewed: bool | None = None
    deleted_at: str | None = None


class BulkCategoryUpdateItem(BaseModel):
    forwarded_to: str
    date_file_name: str
    category: str


class BulkCategoryUpdateRequest(BaseModel):
    updates: list[BulkCategoryUpdateItem]
    source: str = "manual_bulk"


class BulkCategoryUpdateResult(BaseModel):
    tx_id: str
    forwarded_to: str
    date_file_name: str
    new_category: str
    old_category: str | None = None
    ok: bool
    error: str | None = None


class BulkCategoryUpdateResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BulkCategoryUpdateResult]


class ReviewResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tx_id": "ZGVmYXVsdEBsb2NhbHwyMDI2LjA0LjE1XzA5LjMyX2VtYWlsXzAxLmVtbA",
                    "forwarded_to": "default@local",
                    "date_file_name": "2026.04.15_09.32_email_01.eml",
                    "source": "manual",
                }
            ]
        }
    )
    tx_id: str
    forwarded_to: str
    date_file_name: str
    source: str


class IgnoreRequest(BaseModel):
    ignored: bool


class IgnoreResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tx_id": "ZGVmYXVsdEBsb2NhbHwyMDI2LjA0LjE1XzA5LjMyX2VtYWlsXzAxLmVtbA",
                    "forwarded_to": "default@local",
                    "date_file_name": "2026.04.15_09.32_email_01.eml",
                    "ignored": True,
                }
            ]
        }
    )
    tx_id: str
    forwarded_to: str
    date_file_name: str
    ignored: bool


class DeleteRequest(BaseModel):
    deleted: bool


class DeleteResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tx_id": "ZGVmYXVsdEBsb2NhbHwyMDI2LjA0LjE1XzA5LjMyX2VtYWlsXzAxLmVtbA",
                    "forwarded_to": "default@local",
                    "date_file_name": "2026.04.15_09.32_email_01.eml",
                    "deleted_at": "2026-04-20T18:42:11Z",
                }
            ]
        }
    )
    tx_id: str
    forwarded_to: str
    date_file_name: str
    deleted_at: str | None


class PermanentDeleteResponse(BaseModel):
    tx_id: str
    forwarded_to: str
    date_file_name: str


class TransactionFieldsUpdateRequest(BaseModel):
    company: str | None = None
    amount: float | None = Field(None, gt=0)
    transaction_type: TransactionType | None = None

    @field_validator("company")
    @classmethod
    def _company_stripped_non_empty(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("company must not be empty")
        return v


class TransactionFieldsOldValues(BaseModel):
    company: str | None
    amount: float | None
    transaction_type: str | None


class TransactionFieldsUpdateResponse(BaseModel):
    tx_id: str
    forwarded_to: str
    date_file_name: str
    company: str | None
    amount: float | None
    transaction_type: str | None
    category: str | None
    old_values: TransactionFieldsOldValues


class CommentRequest(BaseModel):
    comment: str | None = None


class CommentResponse(BaseModel):
    tx_id: str
    forwarded_to: str
    date_file_name: str
    comment: str | None


class CategoriesResponse(BaseModel):
    categories: list[str]


class LatestTimestampResponse(BaseModel):
    """Lightweight freshness probe — callers compare `latest` against their last seen value.

    `latest` is the raw DateFileName string (lex-sortable by time), or None when
    the table has no matching rows.
    """

    month: str | None
    latest: str | None
