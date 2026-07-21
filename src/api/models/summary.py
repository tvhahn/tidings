"""Summary and trend response schemas."""

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CategorySummary",
    "CompanySummary",
    "DepositSourceSummary",
    "ExpectedChargeInfo",
    "MonthPaceBreakdown",
    "MonthPaceInfo",
    "MonthSummary",
    "SummaryComparisonResponse",
    "TopCategory",
    "TrendMonthEntry",
    "TrendResponse",
]


class CategorySummary(BaseModel):
    amount: float
    count: int


class CompanySummary(BaseModel):
    amount: float
    count: int
    category: str


class DepositSourceSummary(BaseModel):
    amount: float
    count: int


class TopCategory(BaseModel):
    name: str
    amount: float
    count: int


class MonthSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "year_month": "2026-04",
                    "total_spending": 3142.87,
                    "spending_count": 84,
                    "deposit_total": 5200.00,
                    "deposit_count": 2,
                    "by_category": {
                        "groceries": {"amount": 612.45, "count": 18},
                        "restaurants": {"amount": 248.90, "count": 11},
                    },
                    "by_company": {
                        "WHOLE FOODS": {"amount": 412.30, "count": 8, "category": "groceries"},
                    },
                    "deposits_by_company": {
                        "EMPLOYER PAYROLL": {"amount": 5200.00, "count": 2},
                    },
                    "top_categories": [
                        {"name": "groceries", "amount": 612.45, "count": 18},
                        {"name": "restaurants", "amount": 248.90, "count": 11},
                    ],
                }
            ]
        }
    )
    year_month: str
    total_spending: float
    spending_count: int
    deposit_total: float
    deposit_count: int
    by_category: dict[str, CategorySummary]
    by_company: dict[str, CompanySummary]
    deposits_by_company: dict[str, DepositSourceSummary]
    top_categories: list[TopCategory]


class ExpectedChargeInfo(BaseModel):
    """One expected recurring charge for the current month (see ``UpcomingService``).

    Status is derived at query time, never stored: ``upcoming`` (day still
    ahead), ``arrived`` (matched an observed row — carries ``actual_*``),
    ``assumed`` (day passed, statement-observed, awaiting import — counts in the
    projection, never alarming), ``unrecorded`` (day + grace passed for an
    email-observed merchant — a quiet note that counts in NO committed term).
    """

    merchant: str  # normalized key
    display_name: str  # title-cased for display
    amount_estimate: float
    expected_day: int  # median day-of-month, clamped to days_in_month
    status: str  # "upcoming" | "arrived" | "assumed" | "unrecorded"
    channel: str  # "email" | "statement" | "mixed"
    cadence: str  # "monthly" | "annual"
    category: str | None = None
    actual_amount: float | None = None  # arrived only
    actual_date: str | None = None  # arrived only, YYYY-MM-DD
    previous_amount: float | None = None  # annual price memory (last year's charge)


class MonthPaceBreakdown(BaseModel):
    """Commitment-aware decomposition of ``projected_month_total`` (L5).

    ``projected_month_total`` = ``observed_mtd + assumed_committed +
    upcoming_committed + everyday_remainder``. ``observed_mtd`` is the ledger
    truth (arrived recurring + imported statement rows included); the committed
    terms are point estimates over the expected charges; ``everyday_remainder``
    is the discretionary-only curve projection for the rest of the month.
    """

    observed_mtd: float
    assumed_committed: float
    upcoming_committed: float
    everyday_remainder: float
    everyday_daily_rate: float | None = None  # remainder / days_remaining
    days_remaining: int
    charges: list[ExpectedChargeInfo]


class MonthPaceInfo(BaseModel):
    """Mid-month pace context — non-null only when the requested month is the
    current month (see the summary router). Day *position* for every fraction
    lookup is ``day_of_month / days_in_month``.

    ``breakdown`` is the commitment-aware decomposition (L6): non-null only when
    the upcoming-charge derivation succeeds AND penciled charges exist; it
    fails open to ``None`` (curve-only pace) exactly like ``pace`` itself.
    """

    day_of_month: int
    days_in_month: int
    previous_to_date: float
    typical_to_date: float | None
    projected_month_total: float | None
    projected_lower: float | None
    projected_upper: float | None
    forecast_quality: str | None
    breakdown: MonthPaceBreakdown | None = None


class SummaryComparisonResponse(BaseModel):
    current: MonthSummary
    previous: MonthSummary
    delta_amount: float
    delta_percent: float
    pace: MonthPaceInfo | None = None


class TrendMonthEntry(BaseModel):
    year_month: str
    total_spending: float
    spending_count: int
    by_category: dict[str, CategorySummary]


class TrendResponse(BaseModel):
    months: list[TrendMonthEntry]
