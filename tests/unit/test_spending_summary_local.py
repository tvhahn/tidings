"""Tests for SpendingSummaryLocal — SQLite-backed spending aggregation."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.finance.spending_summary_local import SpendingSummaryLocal
from src.finance.transaction_db_local import TransactionsDBLocal

FORWARDED_TO = "user@example.com"


def _add_purchase(
    db: Any,
    company: str,
    amount: float,
    category: str,
    date_str: str = "02/15/2026 10:30 PST",
    file_suffix: str = "",
) -> None:
    """Helper: insert a purchase transaction into the SQLite DB."""
    db.add_transaction(
        {
            "forwarded_to": FORWARDED_TO,
            "file_name": f"test{file_suffix}.eml",
            "date": date_str,
            "amount": amount,
            "company": company,
            "category": category,
            "institution": "RBC",
            "transaction_type": "purchase",
            "user_id": "alice",
            "name": "Alice",
            "from_name": "RBC",
            "from_email": "alerts@rbc.com",
            "to_name": "Alice",
            "to_email": FORWARDED_TO,
            "subject": "Transaction Alert",
            "body": "body",
        }
    )


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def db(tmp_db_path: Path) -> TransactionsDBLocal:
    return TransactionsDBLocal(db_path=tmp_db_path)


@pytest.fixture
def summary(tmp_db_path: Path) -> SpendingSummaryLocal:
    return SpendingSummaryLocal(db_path=tmp_db_path)


class TestQueryMonth:
    def test_returns_transactions_for_month(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Store A", 50.0, "groceries", file_suffix="1")
        _add_purchase(db, "Store B", 25.0, "entertainment", file_suffix="2")
        items = summary.query_month("2026-02")
        assert len(items) == 2

    def test_returns_empty_for_no_transactions(self, summary: SpendingSummaryLocal) -> None:
        items = summary.query_month("2025-01")
        assert items == []

    def test_ignores_other_months(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Jan Store", 10.0, "groceries", date_str="01/10/2026 10:00 PST", file_suffix="jan")
        _add_purchase(db, "Feb Store", 20.0, "groceries", date_str="02/15/2026 10:30 PST", file_suffix="feb")
        items = summary.query_month("2026-02")
        assert len(items) == 1
        assert items[0]["Company"] == "Feb Store"

    def test_projection_args_ignored(self, db: Any, summary: SpendingSummaryLocal) -> None:
        """projection and expression_names args are accepted but ignored."""
        _add_purchase(db, "Store", 10.0, "groceries", file_suffix="1")
        items = summary.query_month("2026-02", projection="Company", expression_names={"#c": "Company"})
        assert len(items) == 1


class TestAggregate:
    def test_sums_purchases(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Store A", 50.0, "groceries", file_suffix="1")
        _add_purchase(db, "Store B", 25.0, "groceries", file_suffix="2")
        items = summary.query_month("2026-02")
        result = summary.aggregate(items)
        assert result["total_spending"] >= 75.0

    def test_empty_aggregate(self, summary: SpendingSummaryLocal) -> None:
        result = summary.aggregate([])
        assert result["total_spending"] == 0
        assert result["by_category"] == {}

    def test_multiple_categories(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Safeway", 100.0, "groceries", file_suffix="1")
        _add_purchase(db, "Starbucks", 50.0, "restaurant/dining", file_suffix="2")
        _add_purchase(db, "Landlord", 200.0, "rent", file_suffix="3")
        items = summary.query_month("2026-02")
        result = summary.aggregate(items)
        assert result["total_spending"] == Decimal("350.00")
        assert result["spending_count"] == 3
        assert result["by_category"] == {
            "groceries": {"amount": Decimal("100.0"), "count": 1},
            "restaurant/dining": {"amount": Decimal("50.0"), "count": 1},
            "rent": {"amount": Decimal("200.0"), "count": 1},
        }


class TestGetSummary:
    def test_returns_year_month(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Store", 10.0, "groceries", file_suffix="1")
        result = summary.get_summary("2026-02")
        assert result["year_month"] == "2026-02"

    def test_total_spending(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Store A", 100.0, "groceries", file_suffix="1")
        _add_purchase(db, "Store B", 50.0, "entertainment", file_suffix="2")
        result = summary.get_summary("2026-02")
        assert result["total_spending"] >= 150.0


class TestGetSummaryWithComparison:
    def test_returns_current_and_previous(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Feb Store", 200.0, "groceries", date_str="02/10/2026 10:00 PST", file_suffix="feb")
        _add_purchase(db, "Jan Store", 100.0, "groceries", date_str="01/10/2026 10:00 PST", file_suffix="jan")

        result = summary.get_summary_with_comparison("2026-02")
        assert "current" in result
        assert "previous" in result
        assert result["current"]["year_month"] == "2026-02"
        assert result["previous"]["year_month"] == "2026-01"

    def test_delta_amount_calculated(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Feb Store", 200.0, "groceries", date_str="02/10/2026 10:00 PST", file_suffix="feb")
        _add_purchase(db, "Jan Store", 100.0, "groceries", date_str="01/10/2026 10:00 PST", file_suffix="jan")

        result = summary.get_summary_with_comparison("2026-02")
        # Current (200) - Previous (100) = positive delta
        assert result["delta_amount"] > 0

    def test_zero_previous_month(self, db: Any, summary: SpendingSummaryLocal) -> None:
        _add_purchase(db, "Feb Store", 150.0, "groceries", date_str="02/10/2026 10:00 PST", file_suffix="feb")

        result = summary.get_summary_with_comparison("2026-02")
        assert result["previous"]["total_spending"] == 0
        # inf when current > 0 and previous == 0
        assert result["delta_percent"] == float("inf")

    def test_both_zero(self, summary: SpendingSummaryLocal) -> None:
        result = summary.get_summary_with_comparison("2025-06")
        assert result["delta_percent"] == 0.0
