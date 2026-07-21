"""Pydantic response schemas for the tax pack endpoints.

``cra_ref`` and ``note`` are informational strings from the mapping seed,
rendered verbatim — the API never interprets them. Transactions carry the
``tx_id`` surrogate only; the storage composite never leaves the backend.
"""

from typing import Literal

from pydantic import BaseModel, Field


class TaxEvidenceCounts(BaseModel):
    """How many of a line's transactions carry each kind of evidence."""

    receipt: int
    email: int
    statement: int


class TaxPackTransaction(BaseModel):
    """One claimable transaction inside a tax line."""

    tx_id: str
    date: str = Field(description="Transaction date, YYYY-MM-DD.")
    company: str
    amount: float
    category: str
    evidence: str  # "receipt" | "email" | "statement"
    forwarded_to: str
    date_file_name: str
    manual: bool = False


class TaxLineResponse(BaseModel):
    """One claim line with its matched transactions for the year."""

    key: str
    label: str
    cra_ref: str | None = Field(None, description="Tax line reference, rendered verbatim.")
    note: str | None = Field(None, description="Optional one-sentence note from the mapping seed.")
    categories: list[str]
    total: float
    transaction_count: int
    evidence_counts: TaxEvidenceCounts
    transactions: list[TaxPackTransaction]
    excluded_transactions: list[TaxPackTransaction] = []


class TaxPackResponse(BaseModel):
    """The full calendar-year tax pack: every mapped line plus a grand total."""

    year: int
    grand_total: float
    lines: list[TaxLineResponse]


class TaxOverrideRequest(BaseModel):
    """Force a transaction into a line (``include``) or drop it out (``exclude``)."""

    tx_id: str
    mode: Literal["include", "exclude"]
    line_key: str | None = Field(None, description="Target line key; required when mode is include.")


class TaxLineOption(BaseModel):
    """A selectable claim line (for the include-override picker)."""

    key: str
    label: str


class TaxLinesResponse(BaseModel):
    """The selectable claim lines: the seed lines plus the synthetic other line."""

    lines: list[TaxLineOption]
