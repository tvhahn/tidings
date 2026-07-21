"""Pydantic models for the ingestion-coverage endpoint.

Mirrors the ``CoverageService.get_coverage()`` snapshot exactly: per-institution
bank-alert cadence (``active`` / ``quiet`` / ``dormant`` / ``irregular``) plus an
optional passive capture rate derived from statement reconciliation. Every field
name matches a key the service emits so the payload round-trips without
translation.
"""

from typing import Literal

from pydantic import BaseModel

__all__ = [
    "CaptureBucket",
    "CaptureBucketInstitution",
    "CaptureBucketType",
    "CaptureSummary",
    "CoverageInstitution",
    "CoverageResponse",
]


CoverageStatus = Literal["active", "quiet", "dormant", "irregular"]


class CoverageInstitution(BaseModel):
    """One institution's modeled alert cadence over the trailing window.

    ``median_gap_days`` / ``threshold_gap_days`` / ``dormant_cutoff_days`` are
    ``None`` for ``irregular`` institutions — below the eligibility bar they have
    no meaningful cadence, so no thresholds are computed.
    """

    institution: str
    status: CoverageStatus
    last_seen_at: str | None
    days_since_last_seen: int | None
    median_gap_days: float | None
    threshold_gap_days: int | None
    dormant_cutoff_days: int | None
    event_days: int


class CaptureBucket(BaseModel):
    """Overall caught/total/rate roll-up for the capture summary."""

    caught: int
    total: int
    rate: float


class CaptureBucketInstitution(BaseModel):
    """Per-institution capture-rate breakdown."""

    institution: str
    caught: int
    total: int
    rate: float


class CaptureBucketType(BaseModel):
    """Per-transaction-type capture-rate breakdown (withdrawal / deposit)."""

    type: str
    caught: int
    total: int
    rate: float


class CaptureSummary(BaseModel):
    """Passive email-capture rate measured from statement reconciliation.

    Present only when the user has imported statements (SQLite-only ledger);
    ``CoverageResponse.capture`` is ``None`` on the DynamoDB path or when no
    reconciled rows exist.
    """

    overall: CaptureBucket
    by_institution: list[CaptureBucketInstitution]
    by_type: list[CaptureBucketType]


class CoverageResponse(BaseModel):
    """Full payload for ``GET /api/v1/coverage``."""

    institutions: list[CoverageInstitution]
    capture: CaptureSummary | None
    window_months: int
    checked_at: str
