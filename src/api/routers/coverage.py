"""Ingestion-coverage endpoint: per-institution bank-alert cadence + capture rate."""

from fastapi import APIRouter, Depends

from src.api.dependencies import (
    get_coverage_service,
    run_sync,
)
from src.api.models import CoverageResponse
from src.finance.coverage_service import CoverageService

router = APIRouter(tags=["coverage"])


@router.get(
    "/coverage",
    response_model=CoverageResponse,
    operation_id="getCoverage",
    summary="Per-institution bank-alert cadence and passive email-capture rate",
)
async def get_coverage(
    service: CoverageService = Depends(get_coverage_service),
):
    """Return each institution's modeled alert cadence — whether it is ``active``,
    ``quiet``, ``dormant``, or ``irregular`` — plus the passive capture rate
    measured from statement reconciliation (``null`` where no statements exist).

    Read-only; served from a 1-hour in-memory cache.
    """
    return await run_sync(service.get_coverage)
