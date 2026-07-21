"""Enrich transactions with month-to-date spending context for SMS notifications."""

import logging
from decimal import Decimal
from typing import Any

from dateutil.parser import parse

from src.finance.app_timezone import get_tzinfos
from src.finance.protocols import IBudgetService, ITransactionsDB, TransactionItem

logger = logging.getLogger(__name__)

SPENDING_TYPES = {"purchase", "withdrawal", "preauth"}


class TransactionContextEnricher:
    """Build month-to-date spending context for a transaction.

    Fail-open: returns None on any error so the pipeline always continues.
    """

    def __init__(self, transactions_db: ITransactionsDB, budget_service: IBudgetService | None = None):
        self.transactions_db = transactions_db
        self.budget_service = budget_service

    def enrich(self, transaction_data: dict[str, Any]) -> dict[str, Any] | None:
        """Return a context dict or None on any error."""
        try:
            return self._build_context(transaction_data)
        except Exception:
            logger.exception("Context enrichment failed — continuing without context")
            return None

    def _build_context(self, txn: dict[str, Any]) -> dict[str, Any] | None:
        forwarded_to = txn.get("forwarded_to")
        date_str = txn.get("date")
        category = (txn.get("category") or "").lower()
        company = (txn.get("company") or "").lower()

        if not forwarded_to or not date_str or not category:
            return None

        year_month = self._extract_year_month(date_str)
        if not year_month:
            return None

        items = self._query_month_partition(forwarded_to, year_month)

        # Callers (imap_poller, lambda_function) write the txn before calling
        # enrich(), so the loop below already sees the current transaction —
        # do not add it again here.
        category_total = Decimal(0)
        merchant_count = 0

        for item in items:
            if item.get("DeletedAt"):
                continue
            if item.get("Ignored"):
                continue
            item_type = item.get("TransactionType")
            if item_type not in SPENDING_TYPES:
                continue

            item_category = (item.get("Category") or "").lower()
            if item_category == category:
                amount = item.get("Amount")
                if amount is not None:
                    category_total += Decimal(str(amount))

            item_company = (item.get("Company") or "").lower()
            if item_company == company:
                merchant_count += 1

        context = {
            "category_month_total": float(category_total),
            "merchant_month_count": merchant_count,
        }

        # Add budget fields if available
        self._add_budget_context(context, category, year_month)

        return context

    def _add_budget_context(self, context: dict[str, Any], category: str, year_month: str) -> None:
        """Add budget target and percentage if a budget is configured."""
        if not self.budget_service:
            return

        try:
            year = int(year_month.split("-", maxsplit=1)[0])
            targets_item = self.budget_service.get_targets(year)
            if not targets_item:
                return

            categories = targets_item.get("Data", {}).get("categories", {})
            cat_config = categories.get(category)
            if not cat_config:
                return

            monthly_amount = cat_config.get("monthly_amount")
            if not monthly_amount or float(monthly_amount) <= 0:
                return

            monthly_float = float(monthly_amount)
            context["category_budget_target"] = monthly_float
            context["category_budget_pct"] = round(context["category_month_total"] / monthly_float * 100, 1)
        except Exception:
            logger.exception("Budget lookup failed — continuing without budget context")

    def _query_month_partition(self, forwarded_to: str, year_month: str) -> list[TransactionItem]:
        """Delegate month-partition query to the storage backend."""
        return self.transactions_db.query_month_partition(forwarded_to, year_month)

    @staticmethod
    def _extract_year_month(date_str: str) -> str | None:
        """Parse a date string and return YYYY-MM or None."""
        try:
            dt = parse(date_str, tzinfos=get_tzinfos())
            return dt.strftime("%Y-%m")
        except (ValueError, TypeError):
            return None
