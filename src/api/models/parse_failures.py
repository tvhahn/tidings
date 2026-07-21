"""Pydantic models for the parse-failure (dead-letter) quarantine endpoints."""

from pydantic import BaseModel, Field

from src.api.models.ingestion import TransactionType


class ParseFailureSummary(BaseModel):
    """Triage view of a quarantined parse failure — no email body."""

    id: str
    received_at: str
    from_email: str | None
    subject: str | None
    detected_institution: str | None
    failure_stage: str
    status: str
    recovered_date_file_name: str | None
    alert_classifier_result: bool | None


class ParseFailureDetail(ParseFailureSummary):
    """Full view of a quarantined parse failure, including the email body."""

    body: str


class ParseFailureListResponse(BaseModel):
    count: int
    failures: list[ParseFailureSummary]


class RetryResponse(BaseModel):
    failure_id: str
    status: str  # "created" | "duplicate" | "still_failing"
    date_file_name: str | None = None


class DismissResponse(BaseModel):
    failure_id: str
    status: str  # "dismissed"


class ManualResolveRequest(BaseModel):
    """Hand-entered values for a quarantined email the parsers couldn't read.

    Mirrors ``ManualTransactionRequest`` (``src/api/models/ingestion.py``) so the
    resolve endpoint can reuse the same manual-transaction dict-build. ``name``
    is intentionally omitted — the resolve flow defaults the cardholder to the
    configured user.
    """

    date: str = Field(..., description="Transaction date in YYYY-MM-DD format")
    amount: float = Field(..., gt=0, description="Transaction amount")
    company: str = Field(..., min_length=1, description="Merchant/company name")
    category: str | None = Field(None, description="Category (auto-detected from overrides if omitted)")
    transaction_type: TransactionType = Field(
        "purchase", description="purchase, withdrawal, preauth, e-transfer, or deposit"
    )
    institution: str | None = Field(
        None,
        description="Financial institution; defaults to the failure's detected institution, else 'Manual'",
    )


class ManualResolveResponse(BaseModel):
    failure_id: str
    status: str  # "created" | "duplicate"
    date_file_name: str | None = None


class FixtureFromFailureRequest(BaseModel):
    """Optional target institution for a to-fixture write.

    When present, its slug (lowercase, spaces→underscores, non-alphanumerics
    stripped) names the ``tests/test_data/<dir>/`` folder. When omitted, the
    failure's ``detected_institution`` lowercased is used instead.
    """

    institution: str | None = Field(
        None,
        description="Target institution; falls back to the failure's detected institution.",
    )


class FixtureFromFailureResponse(BaseModel):
    """Repo-relative paths of the two fixture files written."""

    txt_path: str
    json_path: str


class RetryAllRequest(BaseModel):
    """Filter for a bulk retry — at least one field is required (422 otherwise)."""

    institution: str | None = Field(None, description="Retry quarantined rows whose detected institution equals this.")
    from_domain: str | None = Field(
        None,
        description="Retry quarantined rows whose sender email domain matches (suffix) this.",
    )


class RetryAllResponse(BaseModel):
    retried: int  # rows attempted
    created: int
    duplicates: int
    still_failing: int
