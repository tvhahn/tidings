"""Merchant intelligence endpoint: recurring detection + burn rate + alerts."""

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import (
    get_merchant_intelligence_service,
    run_sync,
)
from src.api.models import MerchantIntelligenceResponse
from src.api.utils import MONTH_PATTERN
from src.finance.merchant_intelligence import MerchantIntelligenceService

router = APIRouter(tags=["merchants"])


@router.get(
    "/merchants/intelligence",
    response_model=MerchantIntelligenceResponse,
    operation_id="getMerchantIntelligence",
    summary="Recurring-charge detection, price-change alerts, committed burn rate",
)
async def get_merchant_intelligence(
    month: str = Query(..., pattern=MONTH_PATTERN, description="Month in YYYY-MM format."),
    months: int = Query(6, ge=1, le=24, description="Lookback window in months (default 6)."),
    service: MerchantIntelligenceService = Depends(get_merchant_intelligence_service),
):
    """Return recurring-charge detection, price-change alerts, and committed
    burn rate for ``month`` using the prior ``months`` of summary data.
    """
    return await run_sync(service.get_intelligence, month, months)
