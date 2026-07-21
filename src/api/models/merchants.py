"""Pydantic models for the merchant intelligence endpoint."""

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "MerchantIntelligenceResponse",
    "MerchantIntelligenceSummary",
    "MerchantPriceChange",
    "MerchantRecord",
]


FrequencyType = Literal["fixed", "variable", "lumpy", "none"]


class MerchantPriceChange(BaseModel):
    """Latest detected price change for a recurring merchant."""

    old_amount: float
    new_amount: float
    since_month: str = Field(..., description="YYYY-MM month the new price first appeared.")


class MerchantRecord(BaseModel):
    """Per-merchant intelligence over the analyzed window."""

    company: str
    total: float
    monthly_amounts: list[float]
    monthly_counts: list[int]
    months_active: int
    avg_amount: float
    frequency_type: FrequencyType
    category: str
    is_recurring: bool
    price_change: MerchantPriceChange | None = None
    is_new: bool
    is_churned: bool


class MerchantPriceChangeRow(BaseModel):
    """Flattened price-change entry for the summary section."""

    merchant: str
    old_amount: float
    new_amount: float
    since_month: str


class MerchantIntelligenceSummary(BaseModel):
    """Aggregate roll-up across all merchants."""

    recurring_burn_rate: float = Field(..., description="Sum of avg_amount across all merchants classified as fixed.")
    recurring_count: int
    discretionary_this_month: float
    new_merchants: list[str]
    churned_merchants: list[str]
    price_changes: list[MerchantPriceChangeRow]


class MerchantIntelligencePeriod(BaseModel):
    """Inclusive window of months consumed for the calculation."""

    from_: str = Field(..., alias="from")
    to: str

    model_config = {"populate_by_name": True}


class MerchantIntelligenceResponse(BaseModel):
    """Full payload for ``GET /api/v1/merchants/intelligence``."""

    month: str
    months_analyzed: int
    period: MerchantIntelligencePeriod
    merchants: list[MerchantRecord]
    summary: MerchantIntelligenceSummary
