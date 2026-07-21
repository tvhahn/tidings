"""Pydantic request/response schemas for the attachments endpoints.

Attachments reference their transaction by the stable ``tx_id`` surrogate at the
API boundary only; the store persists the ``forwarded_to`` + ``date_file_name``
composite. Responses therefore carry ``tx_id`` (computed) and never the raw
composite.
"""

from typing import Any

from pydantic import BaseModel, Field


class AttachmentResponse(BaseModel):
    """A single attachment row as seen by the API."""

    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    kind: str  # "receipt" | "document"
    tx_id: str | None = Field(None, description="Linked transaction id; null when unfiled.")
    parse_status: str  # "none" | "parsed" | "failed"
    parse_json: dict[str, Any] | None = Field(None, description="Parsed receipt data, when present.")
    parse_error: str | None = None
    created_at: str
    updated_at: str


class AttachmentListResponse(BaseModel):
    count: int
    attachments: list[AttachmentResponse]


class LinkAttachmentRequest(BaseModel):
    """Link an attachment to a transaction, or unlink it with ``tx_id: null``."""

    tx_id: str | None = Field(None, description="Transaction id to link to; null unlinks.")


class AttachmentDeleteResponse(BaseModel):
    id: str
    status: str  # "deleted"


class ReceiptCandidate(BaseModel):
    """One transaction a parsed receipt might explain, ranked by the matcher."""

    tx_id: str
    tier: int = Field(description="1 = exact match, 2 = amount within window, 3 = tip window.")
    day_distance: int
    amount_distance: float
    company: str
    amount: float
    date: str
    category: str
    already_has_receipt: bool


class ReceiptCandidatesResponse(BaseModel):
    """Ranked match candidates for a parsed receipt.

    ``auto_link_candidate`` is true only when exactly one tier-1 candidate exists
    and the attachment arrived unlinked — the signal that the client should link
    the receipt to the first candidate. This GET performs no write; the client
    fires ``POST /attachments/{id}/link`` when the flag is set (the ``read``
    scope's GET-only contract, and the demo dataset, both depend on that).
    """

    attachment_id: str
    auto_link_candidate: bool
    candidates: list[ReceiptCandidate]
