"""Income statement endpoint: annual income vs. expenses view."""

import asyncio

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import (
    get_budget_service,
    get_merchant_alias_service,
    get_spending_summary,
    run_sync,
)
from src.api.models import (
    ExpenseCategoryRow,
    ExpenseSectionResponse,
    IncomeCompanyRow,
    IncomeSectionResponse,
    IncomeStatementResponse,
    ProjectionResponse,
)
from src.finance.income_statement_service import IncomeStatementService
from src.finance.protocols import IBudgetService, IMerchantAliasService, ISpendingSummary

router = APIRouter(tags=["income-statement"])


@router.get(
    "/income-statement",
    response_model=IncomeStatementResponse,
    operation_id="getIncomeStatement",
    summary="Annual income vs. expenses view with projection and savings rate",
)
async def get_income_statement(
    year: int = Query(..., ge=2020, le=2099),
    summary: ISpendingSummary = Depends(get_spending_summary),
    budget_svc: IBudgetService = Depends(get_budget_service),
    alias_svc: IMerchantAliasService = Depends(get_merchant_alias_service),
):
    aliases = await run_sync(alias_svc.get_aliases_map)
    svc = IncomeStatementService(summary, budget_svc, merchant_aliases=aliases)

    # Fetch the 12 month summaries concurrently (positionally Jan..Dec) rather
    # than looping them sequentially inside one run_sync worker, then hand the
    # pre-fetched summaries to the service for aggregation.
    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    monthly_summaries = await asyncio.gather(*[run_sync(summary.get_summary, ym) for ym in months])
    raw = await run_sync(svc.get_income_statement, year, list(monthly_summaries))

    return IncomeStatementResponse(
        year=raw["year"],
        months=raw["months"],
        income=IncomeSectionResponse(
            companies=[IncomeCompanyRow(**c) for c in raw["income"]["companies"]],
            monthly_totals=raw["income"]["monthly_totals"],
            annual_total=raw["income"]["annual_total"],
        ),
        expense_sections=[
            ExpenseSectionResponse(
                type_name=s["type_name"],
                display_name=s["display_name"],
                categories=[
                    ExpenseCategoryRow(
                        category=cat["category"],
                        months=cat["months"],
                        total=cat["total"],
                        companies=[IncomeCompanyRow(**c) for c in cat["companies"]],
                    )
                    for cat in s["categories"]
                ],
                monthly_totals=s["monthly_totals"],
                annual_total=s["annual_total"],
            )
            for s in raw["expense_sections"]
        ],
        total_expenses_monthly=raw["total_expenses_monthly"],
        total_expenses_annual=raw["total_expenses_annual"],
        net_monthly=raw["net_monthly"],
        net_annual=raw["net_annual"],
        savings_rate_monthly=raw["savings_rate_monthly"],
        savings_rate_annual=raw["savings_rate_annual"],
        projection=ProjectionResponse(**raw["projection"]),
        committed_floor=raw["committed_floor"],
    )
