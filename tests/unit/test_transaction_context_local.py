"""End-to-end tests for TransactionContextEnricher backed by SQLite.

Uses a real TransactionsDBLocal (no mocks) to verify the full pipeline:
SQLite write → query_month_partition → enricher aggregation.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.finance.transaction_context import TransactionContextEnricher
from src.finance.transaction_db_local import TransactionsDBLocal

FORWARDED_TO = "user@example.com"


def _base_txn(**overrides: Any) -> dict[str, Any]:
    data = {
        "forwarded_to": FORWARDED_TO,
        "file_name": "test.eml",
        "date": "02/15/2026 10:30 PST",
        "amount": 25.00,
        "company": "Tim Hortons",
        "category": "restaurant/dining",
        "institution": "RBC",
        "transaction_type": "purchase",
        "user_id": "default",
        "name": "Alice",
        "from_name": "RBC",
        "from_email": "alerts@rbc.com",
        "to_name": "Alice",
        "to_email": FORWARDED_TO,
        "subject": "Transaction Alert",
        "body": "You spent money",
    }
    data.update(overrides)
    return data


def _make_txn(**overrides: Any) -> dict[str, Any]:
    """Build a transaction dict as would be passed to enrich()."""
    base = {
        "forwarded_to": FORWARDED_TO,
        "date": "02/15/2026 10:30 PST",
        "category": "restaurant/dining",
        "company": "Starbucks",
        "amount": 12.50,
        "transaction_type": "purchase",
    }
    base.update(overrides)
    return base


@pytest.fixture
def db(tmp_path: Path) -> TransactionsDBLocal:
    return TransactionsDBLocal(db_path=tmp_path / "test.db")


@pytest.fixture
def enricher(db: TransactionsDBLocal) -> TransactionContextEnricher:
    return TransactionContextEnricher(db, budget_service=None)


def _add_self(db: TransactionsDBLocal, **overrides: Any) -> None:
    """Mirror production: add the txn-being-enriched to the DB before enrich.

    Defaults match `_make_txn` so _add_self(db) writes the same logical
    transaction that `enricher.enrich(_make_txn())` will look for.
    """
    overrides.setdefault("file_name", "current.eml")
    overrides.setdefault("company", "Starbucks")
    overrides.setdefault("amount", 12.50)
    db.add_transaction(_base_txn(**overrides))


class TestEnricherWithSQLite:
    def test_returns_context_dict(self, db: Any, enricher: Any) -> None:
        _add_self(db)
        ctx = enricher.enrich(_make_txn())
        assert isinstance(ctx, dict)
        assert "category_month_total" in ctx
        assert "merchant_month_count" in ctx

    def test_sums_matching_category(self, db: Any, enricher: Any) -> None:
        # Two prior purchases in same category
        db.add_transaction(_base_txn(file_name="a.eml", amount=30.00, category="restaurant/dining"))
        db.add_transaction(_base_txn(file_name="b.eml", amount=20.00, category="restaurant/dining"))
        _add_self(db, amount=10.0, category="restaurant/dining")
        ctx = enricher.enrich(_make_txn(amount=10.0, category="restaurant/dining"))
        # 30 + 20 prior + 10 current = 60
        assert ctx["category_month_total"] == 60.0

    def test_does_not_sum_other_categories(self, db: Any, enricher: Any) -> None:
        db.add_transaction(_base_txn(file_name="a.eml", amount=100.00, category="groceries"))
        _add_self(db, amount=10.0, category="restaurant/dining")
        ctx = enricher.enrich(_make_txn(amount=10.0, category="restaurant/dining"))
        assert ctx["category_month_total"] == 10.0

    def test_counts_same_month_only(self, db: Any, enricher: Any) -> None:
        # Feb transaction
        db.add_transaction(_base_txn(file_name="feb.eml", date="02/10/2026 09:00 PST", company="Starbucks"))
        # Jan transaction — should not be counted
        db.add_transaction(_base_txn(file_name="jan.eml", date="01/10/2026 09:00 PST", company="Starbucks"))
        _add_self(db, date="02/15/2026 10:30 PST", company="Starbucks")
        ctx = enricher.enrich(_make_txn(date="02/15/2026 10:30 PST", company="Starbucks"))
        # 1 prior Feb visit + 1 current = 2
        assert ctx["merchant_month_count"] == 2

    def test_excludes_deleted(self, db: Any, enricher: Any) -> None:
        dfn = db.add_transaction(_base_txn(file_name="prior.eml", amount=50.00))
        db.set_deleted(FORWARDED_TO, dfn, True)
        _add_self(db, amount=10.0)
        ctx = enricher.enrich(_make_txn(amount=10.0))
        assert ctx["category_month_total"] == 10.0

    def test_excludes_ignored(self, db: Any, enricher: Any) -> None:
        dfn = db.add_transaction(_base_txn(file_name="prior.eml", amount=50.00))
        db.set_ignored(FORWARDED_TO, dfn, True)
        _add_self(db, amount=10.0)
        ctx = enricher.enrich(_make_txn(amount=10.0))
        assert ctx["category_month_total"] == 10.0

    def test_first_visit_when_db_empty(self, db: Any, enricher: Any) -> None:
        _add_self(db)
        ctx = enricher.enrich(_make_txn())
        assert ctx["merchant_month_count"] == 1

    def test_repeat_merchant_counts_all(self, db: Any, enricher: Any) -> None:
        db.add_transaction(_base_txn(file_name="prior.eml", company="Starbucks"))
        _add_self(db, company="Starbucks")
        ctx = enricher.enrich(_make_txn(company="Starbucks"))
        assert ctx["merchant_month_count"] == 2

    def test_case_insensitive_merchant_match(self, db: Any, enricher: Any) -> None:
        db.add_transaction(_base_txn(file_name="prior.eml", company="STARBUCKS"))
        _add_self(db, company="starbucks")
        ctx = enricher.enrich(_make_txn(company="starbucks"))
        assert ctx["merchant_month_count"] == 2

    def test_budget_context_with_mock_budget_service(self, db: Any, tmp_path: Path) -> None:
        budget_service = MagicMock()
        budget_service.get_targets.return_value = {
            "Data": {"categories": {"restaurant/dining": {"monthly_amount": Decimal(400)}}}
        }
        enricher = TransactionContextEnricher(db, budget_service=budget_service)
        _add_self(db, amount=100.0)
        ctx = enricher.enrich(_make_txn(amount=100.0))
        assert ctx is not None
        assert ctx["category_budget_target"] == 400.0
        assert ctx["category_budget_pct"] == 25.0

    def test_fail_open_on_db_error(self, db: Any, enricher: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(db, "query_month_partition", lambda *a, **kw: (_ for _ in ()).throw(Exception("db error")))
        ctx = enricher.enrich(_make_txn())
        assert ctx is None
