"""Pydantic models for local data ingestion endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

# Canonical set of transaction types accepted across the manual-entry surfaces
# (manual add + parse-failure resolve). ``_VALID_TRANSACTION_TYPES`` in
# ``src/api/routers/transactions.py`` derives its membership set from this alias
# via ``typing.get_args`` — keep the accepted values in one place here.
TransactionType = Literal["purchase", "withdrawal", "preauth", "e-transfer", "deposit"]


class ManualTransactionRequest(BaseModel):
    date: str = Field(..., description="Transaction date in YYYY-MM-DD format")
    amount: float = Field(..., gt=0, description="Transaction amount")
    company: str = Field(..., min_length=1, description="Merchant/company name")
    category: str | None = Field(None, description="Category (auto-detected if omitted)")
    transaction_type: TransactionType = Field(
        "purchase", description="purchase, withdrawal, preauth, e-transfer, or deposit"
    )
    institution: str | None = Field(None, description="Financial institution")
    name: str | None = Field(None, description="Cardholder name")


class ManualTransactionResponse(BaseModel):
    forwarded_to: str
    date_file_name: str
    category: str
    status: str


class UploadEmlResponse(BaseModel):
    status: str = Field(..., description='"created" on success, "duplicate" if already present')
    date_file_name: str | None = None
    company: str | None = None
    amount: float | None = None
    category: str | None = None
    detail: str | None = None
