"""Income statement schemas."""

from pydantic import BaseModel

__all__ = [
    "ExpenseCategoryRow",
    "ExpenseSectionResponse",
    "IncomeCompanyRow",
    "IncomeSectionResponse",
    "IncomeStatementResponse",
    "ProjectionResponse",
]


class IncomeCompanyRow(BaseModel):
    company: str
    months: list[float]
    total: float


class IncomeSectionResponse(BaseModel):
    companies: list[IncomeCompanyRow]
    monthly_totals: list[float]
    annual_total: float


class ExpenseCategoryRow(BaseModel):
    category: str
    months: list[float]
    total: float
    companies: list[IncomeCompanyRow]


class ExpenseSectionResponse(BaseModel):
    type_name: str
    display_name: str
    categories: list[ExpenseCategoryRow]
    monthly_totals: list[float]
    annual_total: float


class ProjectionResponse(BaseModel):
    annualized_income: float
    annualized_expenses: float
    annualized_net: float
    months_elapsed: int


class IncomeStatementResponse(BaseModel):
    year: int
    months: list[str]
    income: IncomeSectionResponse
    expense_sections: list[ExpenseSectionResponse]
    total_expenses_monthly: list[float]
    total_expenses_annual: float
    net_monthly: list[float]
    net_annual: float
    savings_rate_monthly: list[float | None]
    savings_rate_annual: float | None
    projection: ProjectionResponse
    committed_floor: float
