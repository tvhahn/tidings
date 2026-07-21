"""Budget configuration and status schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InputMode = Literal["monthly", "yearly"]
CategoryType = Literal["fixed", "variable", "lumpy"]
PaceStatusValue = Literal["under", "on_track", "over"]
ForecastQuality = Literal["forecast", "historical", "limited", "committed"]

__all__ = [
    "BudgetCategoryConfig",
    "BudgetCategoryConfigInput",
    "BudgetConfigResponse",
    "BudgetConfigUpdateRequest",
    "BudgetGroupConfig",
    "BudgetStatusResponse",
    "CategoryPaceDetail",
    "ForecastQuality",
    "GroupPace",
    "GroupsResponse",
    "GroupsUpdateRequest",
    "HistoricalAveragesResponse",
    "HistoricalCategoryAverage",
    "PaceStatus",
    "UnbudgetedCategory",
]


class BudgetCategoryConfig(BaseModel):
    target: float
    input_mode: InputMode
    monthly_amount: float
    category_type: CategoryType


class BudgetGroupConfig(BaseModel):
    name: str
    categories: list[str]


class GroupsResponse(BaseModel):
    year: int
    groups: list[BudgetGroupConfig]
    version: int


class GroupsUpdateRequest(BaseModel):
    groups: list[BudgetGroupConfig]
    version: int | None


class BudgetConfigResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "year": 2026,
                    "spending_ceiling": 48000.00,
                    "categories": {
                        "groceries": {
                            "target": 7200.00,
                            "input_mode": "monthly",
                            "monthly_amount": 600.00,
                            "category_type": "variable",
                        },
                        "rent": {
                            "target": 24000.00,
                            "input_mode": "monthly",
                            "monthly_amount": 2000.00,
                            "category_type": "fixed",
                        },
                    },
                    "groups": [
                        {"name": "Essentials", "categories": ["groceries", "rent"]},
                    ],
                    "targets_version": 3,
                    "groups_version": 1,
                    "allocated_total": 31200.00,
                    "unallocated": 16800.00,
                }
            ]
        }
    )
    year: int
    spending_ceiling: float
    categories: dict[str, BudgetCategoryConfig]
    groups: list[BudgetGroupConfig]
    targets_version: int
    groups_version: int
    allocated_total: float
    unallocated: float


class BudgetCategoryConfigInput(BaseModel):
    target: float
    input_mode: InputMode
    category_type: CategoryType


class BudgetConfigUpdateRequest(BaseModel):
    spending_ceiling: float
    categories: dict[str, BudgetCategoryConfigInput]
    groups: list[BudgetGroupConfig]
    targets_version: int | None
    groups_version: int | None


class PaceStatus(BaseModel):
    spending_ceiling: float
    ytd_spent: float
    expected_pace: float
    variance: float
    status: PaceStatusValue
    headline: str
    projected_month_total: float | None = Field(
        default=None,
        description=(
            "Projected current-month spend across budgeted non-lumpy categories. "
            "None when forecasting is unavailable (non-current year, no history, or error)."
        ),
    )
    projected_month_status: PaceStatusValue | None = Field(
        default=None,
        description="Projected total vs the same categories' combined monthly budget.",
    )


class CategoryPaceDetail(BaseModel):
    category: str
    target: float
    input_mode: InputMode
    monthly_amount: float
    category_type: CategoryType
    current_month_spent: float
    current_month_expected: float
    ytd_spent: float
    ytd_expected: float
    variance: float
    pace_percent: float
    status: PaceStatusValue
    monthly_spent: list[float]
    prior_year_total: float | None
    forecast_month_total: float | None = Field(
        default=None,
        description="Projected month-end total. Variable and fixed categories only.",
    )
    forecast_lower: float | None = Field(
        default=None, description="P25 of the projection. None when history is too thin."
    )
    forecast_upper: float | None = Field(
        default=None, description="P75 of the projection. None when history is too thin."
    )
    forecast_pct: float | None = Field(
        default=None,
        description="Projection as a percent of the monthly budget. None when the budget is 0.",
    )
    forecast_quality: ForecastQuality | None = Field(
        default=None,
        description=(
            "forecast = curve-based projection; historical = typical-month average "
            "(early month or few transactions); limited = linear extrapolation from <2 months of history; "
            "committed = a recurring-dominated category (≥70% of its trailing mean is expected recurring "
            "charges), projected as spent + still-expected committed charges + everyday remainder "
            "rather than a smeared curve (bounds are None)."
        ),
    )


class GroupPace(BaseModel):
    name: str
    budgeted_total: float
    ytd_spent: float
    expected_pace: float
    variance: float
    status: PaceStatusValue
    categories: list[CategoryPaceDetail]
    monthly_totals: list[float]
    prior_year_total: float | None


class UnbudgetedCategory(BaseModel):
    category: str
    ytd_spent: float
    monthly_avg_historical: float
    current_month_spent: float


class BudgetStatusResponse(BaseModel):
    year: int
    as_of: str
    elapsed_year_fraction: float
    overall: PaceStatus
    groups: list[GroupPace]
    unbudgeted: list[UnbudgetedCategory]
    monthly_totals: list[float]
    prior_year_total: float | None
    compare_year: int | None


class HistoricalCategoryAverage(BaseModel):
    monthly_avg: float
    total: float
    months_active: int
    suggested_type: str
    suggested_monthly: float
    suggested_annual: float


class HistoricalAveragesResponse(BaseModel):
    months_analyzed: int
    period: dict[str, str]
    categories: dict[str, HistoricalCategoryAverage]
