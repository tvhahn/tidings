"""Abstract base class for SpendingSummary (DynamoDB) and SpendingSummaryLocal (SQLite).

Contains shared business logic (aggregate, get_summary, get_summary_with_comparison).
Storage-specific query_month is left abstract for each backend.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import date
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta

from src.finance.spending_aggregator import aggregate as _shared_aggregate

if TYPE_CHECKING:
    from src.finance.protocols import TransactionItem

logger = logging.getLogger(__name__)

# Only the attributes _shared_aggregate reads — spares DynamoDB from
# returning email bodies when a summary is fanned out across 12-24 months
# (trend/budget/income-statement). SQLite ignores projections (documented
# asymmetry; see docs/guides/api-conventions.md). None of these six keys is a
# DynamoDB reserved word, so no #-placeholder ExpressionAttributeNames dict is
# needed.
_SUMMARY_PROJECTION = "Amount, Category, Company, TransactionType, Ignored, DeletedAt"


class SpendingSummaryBase(ABC):
    """Storage-agnostic contract and shared logic for spending summaries."""

    # ------------------------------------------------------------------
    # Abstract: storage-specific queries (implemented per backend)
    # ------------------------------------------------------------------

    @abstractmethod
    def query_month(
        self,
        year_month: str,
        projection: str | None = None,
        expression_names: dict[str, str] | None = None,
    ) -> "list[TransactionItem]":
        """Query all transactions for a given YYYY-MM month.

        Args:
            year_month: Month in YYYY-MM format.
            projection: Optional ProjectionExpression (DynamoDB) or ignored (SQLite).
            expression_names: Optional ExpressionAttributeNames (DynamoDB) or ignored (SQLite).
        """

    # ------------------------------------------------------------------
    # Concrete: shared business logic
    # ------------------------------------------------------------------

    def aggregate(self, items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Aggregate a list of transaction items into a spending summary.

        Returns a dict with total_spending, spending_count, deposit_total,
        deposit_count, by_category, by_company, and top_categories.
        """
        return _shared_aggregate(items)

    def get_summary(self, year_month: str) -> dict[str, Any]:
        """Query and aggregate transactions for a single month."""
        items = self.query_month(year_month, _SUMMARY_PROJECTION)
        result = self.aggregate(items)
        result["year_month"] = year_month
        return result

    def get_summary_with_comparison(self, year_month: str) -> dict[str, Any]:
        """Get current month summary with month-over-month comparison."""
        parts = year_month.split("-")
        current_date = date(int(parts[0]), int(parts[1]), 1)
        prev_date = current_date - relativedelta(months=1)
        prev_month = prev_date.strftime("%Y-%m")

        current = self.get_summary(year_month)
        previous = self.get_summary(prev_month)

        delta_amount = current["total_spending"] - previous["total_spending"]
        if previous["total_spending"] > 0:
            delta_percent = float(delta_amount / previous["total_spending"] * 100)
        else:
            delta_percent = float("inf") if current["total_spending"] > 0 else 0.0

        return {
            "current": current,
            "previous": previous,
            "delta_amount": delta_amount,
            "delta_percent": delta_percent,
        }
