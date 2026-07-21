"""Tests for TransactionContextEnricher — month-to-date spending context."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from src.finance.transaction_context import TransactionContextEnricher
from tests.factories import make_transaction_item

# The enricher reads only these four columns off each queried row. Keeping the
# item thin (a strict subset of make_transaction_item's shape) is load-bearing:
# tests assert exact month totals/counts, so extra spend-bearing rows from the
# full factory item would skew them.
_ENRICHER_FIELDS = ("Amount", "Category", "Company", "TransactionType")


def _make_enricher(
    items: list[dict[str, Any]] | None = None,
    budget_service: MagicMock | None = None,
) -> tuple[TransactionContextEnricher, MagicMock]:
    """Create an enricher with a mock transactions_db."""
    transactions_db = MagicMock(name="transactions_db")
    transactions_db.query_month_partition.return_value = items or []
    enricher = TransactionContextEnricher(transactions_db, budget_service)
    return enricher, transactions_db


def _make_txn(**overrides: Any) -> dict[str, Any]:
    """Build a minimal transaction data dict."""
    base: dict[str, Any] = {
        "forwarded_to": "user@example.com",
        "date": "02/15/2026 10:30 PST",
        "category": "restaurant/dining",
        "company": "Starbucks",
        "amount": 12.50,
        "transaction_type": "purchase",
    }
    base.update(overrides)
    return base


def _make_dynamo_item(**overrides: Any) -> dict[str, Any]:
    """Build the thin DynamoDB item the enricher consumes.

    Delegates column shapes to the shared ``make_transaction_item`` factory (so
    e.g. ``Amount`` stays a ``Decimal`` in one place), then subsets to the four
    fields the enricher reads and pins this module's spending-context defaults
    (restaurant/dining @ $25). Overrides — including extra keys like
    ``DeletedAt``/``Ignored`` that exclusion tests add — are applied last.
    """
    item = make_transaction_item(
        Amount=Decimal("25.00"),
        Category="restaurant/dining",
        Company="Tim Hortons",
        TransactionType="purchase",
    )
    base: dict[str, Any] = {key: item[key] for key in _ENRICHER_FIELDS}
    base.update(overrides)
    return base


def _dynamo_from_txn(txn: dict[str, Any]) -> dict[str, Any]:
    """Mirror what add_transaction would write for `txn`. Production calls
    add_transaction before enrich, so the txn is in the partition when
    enrich queries it — tests must include it explicitly."""
    return _make_dynamo_item(
        Amount=Decimal(str(txn["amount"])),
        Category=txn["category"],
        Company=txn["company"],
        TransactionType=txn["transaction_type"],
    )


# ---------------------------------------------------------------------------
# Basic enrichment
# ---------------------------------------------------------------------------


class TestEnrichBasic:
    def test_returns_context_dict(self):
        txn = _make_txn()
        enricher, _ = _make_enricher(items=[_dynamo_from_txn(txn)])
        ctx = enricher.enrich(txn)
        assert isinstance(ctx, dict)
        assert "category_month_total" in ctx
        assert "merchant_month_count" in ctx

    def test_sums_matching_category_only(self):
        txn = _make_txn(amount=10.00)
        items = [
            _make_dynamo_item(Amount=Decimal("30.00"), Category="restaurant/dining"),
            _make_dynamo_item(Amount=Decimal("100.00"), Category="groceries"),
            _dynamo_from_txn(txn),
        ]
        enricher, _ = _make_enricher(items=items)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        # 30 prior r/d + 10 current r/d = 40 (groceries skipped)
        assert ctx["category_month_total"] == 40.0

    def test_counts_merchant_occurrences(self):
        txn = _make_txn(company="Starbucks")
        items = [
            _make_dynamo_item(Company="Starbucks"),
            _make_dynamo_item(Company="Starbucks"),
            _make_dynamo_item(Company="Tim Hortons"),
            _dynamo_from_txn(txn),
        ]
        enricher, _ = _make_enricher(items=items)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        # 2 prior + 1 current = 3 Starbucks
        assert ctx["merchant_month_count"] == 3

    def test_case_insensitive_merchant_match(self):
        txn = _make_txn(company="starbucks")
        items = [_make_dynamo_item(Company="STARBUCKS"), _dynamo_from_txn(txn)]
        enricher, _ = _make_enricher(items=items)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert ctx["merchant_month_count"] == 2

    def test_case_insensitive_category_match(self):
        txn = _make_txn(category="restaurant/dining", amount=5.0)
        items = [
            _make_dynamo_item(Amount=Decimal("20.00"), Category="Restaurant/Dining"),
            _dynamo_from_txn(txn),
        ]
        enricher, _ = _make_enricher(items=items)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert ctx["category_month_total"] == 25.0

    def test_excludes_deposits(self):
        txn = _make_txn(amount=10.0)
        items = [
            _make_dynamo_item(
                Amount=Decimal("500.00"),
                Category="restaurant/dining",
                TransactionType="e-transfer",
            ),
            _dynamo_from_txn(txn),
        ]
        enricher, _ = _make_enricher(items=items)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        # e-transfer should not be counted in spending
        assert ctx["category_month_total"] == 10.0

    def test_excludes_deleted(self):
        txn = _make_txn(amount=10.0)
        items = [
            _make_dynamo_item(
                Amount=Decimal("50.00"),
                Category="restaurant/dining",
                DeletedAt="2026-02-10T00:00:00+00:00",
            ),
            _dynamo_from_txn(txn),
        ]
        enricher, _ = _make_enricher(items=items)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert ctx["category_month_total"] == 10.0

    def test_excludes_ignored(self):
        txn = _make_txn(amount=10.0)
        items = [
            _make_dynamo_item(
                Amount=Decimal("50.00"),
                Category="restaurant/dining",
                Ignored=True,
            ),
            _dynamo_from_txn(txn),
        ]
        enricher, _ = _make_enricher(items=items)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert ctx["category_month_total"] == 10.0

    def test_empty_month(self):
        txn = _make_txn(amount=15.0)
        enricher, _ = _make_enricher(items=[_dynamo_from_txn(txn)])
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert ctx["category_month_total"] == 15.0
        assert ctx["merchant_month_count"] == 1


# ---------------------------------------------------------------------------
# Budget context
# ---------------------------------------------------------------------------


class TestEnrichWithBudget:
    def _make_budget_service(self, monthly_amount: float = 400.0) -> MagicMock:
        """Create a mock BudgetService."""
        svc = MagicMock()
        svc.get_targets.return_value = {
            "Data": {
                "categories": {
                    "restaurant/dining": {
                        "monthly_amount": Decimal(str(monthly_amount)),
                    }
                }
            }
        }
        return svc

    def test_budget_fields_present(self):
        svc = self._make_budget_service(400.0)
        txn = _make_txn(amount=100.0)
        enricher, _ = _make_enricher(items=[_dynamo_from_txn(txn)], budget_service=svc)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert ctx["category_budget_target"] == 400.0
        assert ctx["category_budget_pct"] == 25.0

    def test_budget_omitted_when_no_service(self):
        txn = _make_txn()
        enricher, _ = _make_enricher(items=[_dynamo_from_txn(txn)], budget_service=None)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert "category_budget_target" not in ctx
        assert "category_budget_pct" not in ctx

    def test_budget_omitted_for_unbudgeted_category(self):
        svc = MagicMock()
        svc.get_targets.return_value = {"Data": {"categories": {"groceries": {"monthly_amount": Decimal(300)}}}}
        txn = _make_txn(category="restaurant/dining")
        enricher, _ = _make_enricher(items=[_dynamo_from_txn(txn)], budget_service=svc)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert "category_budget_target" not in ctx

    def test_budget_omitted_when_no_targets(self):
        svc = MagicMock()
        svc.get_targets.return_value = None
        txn = _make_txn()
        enricher, _ = _make_enricher(items=[_dynamo_from_txn(txn)], budget_service=svc)
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert "category_budget_target" not in ctx

    def test_correct_pct_calculation(self):
        svc = self._make_budget_service(200.0)
        txn = _make_txn(amount=20.0)
        items = [
            _make_dynamo_item(Amount=Decimal("80.00"), Category="restaurant/dining"),
            _dynamo_from_txn(txn),
        ]
        enricher, _ = _make_enricher(items=items, budget_service=svc)
        # 80 prior + 20 current = 100 out of 200 = 50%
        ctx = enricher.enrich(txn)
        assert ctx is not None
        assert ctx["category_budget_pct"] == 50.0


# ---------------------------------------------------------------------------
# Fail-open behavior
# ---------------------------------------------------------------------------


class TestFailOpen:
    def test_returns_none_on_db_error(self):
        enricher, transactions_db = _make_enricher()
        transactions_db.query_month_partition.side_effect = Exception("db error")
        ctx = enricher.enrich(_make_txn())
        assert ctx is None

    def test_returns_none_on_missing_date(self):
        enricher, _ = _make_enricher()
        ctx = enricher.enrich(_make_txn(date=None))
        assert ctx is None

    def test_returns_none_on_unparseable_date(self):
        enricher, _ = _make_enricher()
        ctx = enricher.enrich(_make_txn(date="not-a-date"))
        assert ctx is None

    def test_returns_none_on_budget_error(self):
        svc = MagicMock()
        svc.get_targets.side_effect = Exception("boom")
        enricher, _ = _make_enricher(items=[], budget_service=svc)
        # Budget error should not prevent enrichment — just omit budget fields
        ctx = enricher.enrich(_make_txn())
        assert ctx is not None
        assert "category_budget_target" not in ctx

    def test_returns_none_on_missing_forwarded_to(self):
        enricher, _ = _make_enricher()
        ctx = enricher.enrich(_make_txn(forwarded_to=None))
        assert ctx is None


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


class TestQueryConstruction:
    def test_correct_partition_key(self):
        enricher, transactions_db = _make_enricher(items=[])
        enricher.enrich(_make_txn(forwarded_to="test@example.com"))
        args = transactions_db.query_month_partition.call_args.args
        assert args[0] == "test@example.com"

    def test_begins_with_correct_year_month(self):
        enricher, transactions_db = _make_enricher(items=[])
        enricher.enrich(_make_txn(date="03/20/2026 15:00 PST"))
        args = transactions_db.query_month_partition.call_args.args
        assert args[1] == "2026-03"

    def test_query_called_once_per_enrich(self):
        txn = _make_txn(amount=10.0)
        enricher, transactions_db = _make_enricher(
            items=[_make_dynamo_item(), _make_dynamo_item(), _dynamo_from_txn(txn)]
        )
        ctx = enricher.enrich(txn)
        assert transactions_db.query_month_partition.call_count == 1
        assert ctx is not None
        # 2 prior items (matching category) + current txn
        assert ctx["category_month_total"] == 60.0  # 25 + 25 + 10
