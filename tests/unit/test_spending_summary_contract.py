"""Dual-backend contract for the spending-summary (monthly aggregation) pair.

Each scenario runs against *both* ``SpendingSummary`` (DynamoDB via moto) and
``SpendingSummaryLocal`` (SQLite via tmp_path), asserting identical observable
behavior. The two summary classes share aggregation logic via
``SpendingSummaryBase``; the only backend-specific surface is ``query_month``,
which reads the same ``Transactions`` store each backend's transaction DB
writes to — so the contract seeds rows through the paired transaction DB, then
reads them back through the summary.

Mirrors the house shape in ``test_parse_failure_store.py``: a
``@pytest.fixture(params=["dynamodb", "sqlite"])`` fixture, moto-backed
DynamoDB vs a real tmp SQLite file, and the shared ``dyn_resource`` fixture
from ``tests/unit/conftest.py`` (which pre-provisions the Transactions table).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from src.finance.spending_summary import SpendingSummary
from src.finance.spending_summary_local import SpendingSummaryLocal
from src.finance.transaction_db import TransactionsDB
from src.finance.transaction_db_local import TransactionsDBLocal

if TYPE_CHECKING:
    from pathlib import Path


FORWARDED_TO = "user@example.com"


def _seed_txn(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "forwarded_to": FORWARDED_TO,
        "date": "02/15/2026 10:30 PST",
        "amount": 50.0,
        "company": "Store A",
        "category": "groceries",
        "institution": "RBC",
        "transaction_type": "purchase",
        "name": "Alice",
        "subject": "Receipt",
        "body": "$50.00",
        "file_name": "fixture.eml",
    }
    base.update(overrides)
    return base


class _Pair(NamedTuple):
    """A summary reader paired with the transaction DB that feeds its store."""

    summary: Any
    db: Any


class TestSpendingSummaryContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def pair(
        self,
        request: pytest.FixtureRequest,
        dyn_resource: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> _Pair:
        # The DynamoDB summary fans out over user_mapping.get_forwarded_to_addresses();
        # SpendingSummary binds it at import time, so patch that module's name (and
        # the source, which TransactionsDB reads) to the seeded address so the test
        # doesn't depend on the contributor's data/config/user_mappings.csv.
        monkeypatch.setattr(
            "src.finance.spending_summary.get_forwarded_to_addresses",
            lambda: [FORWARDED_TO],
        )
        monkeypatch.setattr(
            "src.finance.user_mapping.get_forwarded_to_addresses",
            lambda: [FORWARDED_TO],
        )
        if request.param == "dynamodb":
            return _Pair(
                summary=SpendingSummary(dyn_resource=dyn_resource),
                db=TransactionsDB(dyn_resource=dyn_resource),
            )
        db_path = tmp_path / "summary.db"
        return _Pair(
            summary=SpendingSummaryLocal(db_path=db_path),
            db=TransactionsDBLocal(db_path=db_path),
        )

    # -- query_month: write-then-read round-trip ----------------------------

    def test_query_month_roundtrip_returns_seeded_rows(self, pair: _Pair) -> None:
        pair.db.add_transaction(
            _seed_txn(company="Store A", amount=50.0, file_name="a.eml", date="02/15/2026 10:30 PST")
        )
        pair.db.add_transaction(
            _seed_txn(
                company="Store B",
                amount=25.0,
                category="entertainment",
                file_name="b.eml",
                date="02/16/2026 10:30 PST",
            )
        )
        items = pair.summary.query_month("2026-02")
        assert len(items) == 2
        # Both backends expose PascalCase item keys.
        assert {it["Company"] for it in items} == {"Store A", "Store B"}
        by_company = {it["Company"]: it for it in items}
        assert Decimal(str(by_company["Store A"]["Amount"])) == Decimal(50)
        assert by_company["Store B"]["Category"] == "entertainment"
        assert by_company["Store A"]["TransactionType"] == "purchase"

    def test_query_month_scopes_to_the_requested_month(self, pair: _Pair) -> None:
        pair.db.add_transaction(_seed_txn(company="Jan Store", file_name="jan.eml", date="01/10/2026 10:00 PST"))
        pair.db.add_transaction(_seed_txn(company="Feb Store", file_name="feb.eml", date="02/15/2026 10:30 PST"))
        feb = pair.summary.query_month("2026-02")
        assert len(feb) == 1
        assert feb[0]["Company"] == "Feb Store"
        assert len(pair.summary.query_month("2026-01")) == 1

    def test_query_month_missing_returns_empty_list(self, pair: _Pair) -> None:
        assert pair.summary.query_month("2030-09") == []

    # -- get_summary: aggregation parity ------------------------------------

    def test_get_summary_aggregates_categories_with_year_month(self, pair: _Pair) -> None:
        pair.db.add_transaction(_seed_txn(company="Safeway", amount=100.0, category="groceries", file_name="s1.eml"))
        pair.db.add_transaction(
            _seed_txn(
                company="Starbucks",
                amount=50.0,
                category="restaurant/dining",
                file_name="s2.eml",
                date="02/16/2026 10:30 PST",
            )
        )
        pair.db.add_transaction(
            _seed_txn(
                company="Landlord",
                amount=200.0,
                category="rent",
                file_name="s3.eml",
                date="02/17/2026 10:30 PST",
            )
        )
        result = pair.summary.get_summary("2026-02")
        assert result["year_month"] == "2026-02"
        assert result["total_spending"] == Decimal(350)
        assert result["spending_count"] == 3
        assert result["by_category"] == {
            "groceries": {"amount": Decimal(100), "count": 1},
            "restaurant/dining": {"amount": Decimal(50), "count": 1},
            "rent": {"amount": Decimal(200), "count": 1},
        }

    def test_get_summary_missing_month_is_zeroed(self, pair: _Pair) -> None:
        result = pair.summary.get_summary("2030-09")
        assert result["year_month"] == "2030-09"
        assert result["total_spending"] == Decimal(0)
        assert result["spending_count"] == 0
        assert result["by_category"] == {}

    def test_get_summary_excludes_soft_deleted(self, pair: _Pair) -> None:
        dfn_a = pair.db.add_transaction(_seed_txn(company="Store A", amount=50.0, file_name="a.eml"))
        assert isinstance(dfn_a, str)
        pair.db.add_transaction(
            _seed_txn(company="Store B", amount=30.0, file_name="b.eml", date="02/16/2026 10:30 PST")
        )
        pair.db.set_deleted(FORWARDED_TO, dfn_a, deleted=True)

        result = pair.summary.get_summary("2026-02")
        assert result["total_spending"] == Decimal(30)
        assert result["spending_count"] == 1

    def test_get_summary_excludes_ignored(self, pair: _Pair) -> None:
        dfn_a = pair.db.add_transaction(_seed_txn(company="Store A", amount=50.0, file_name="a.eml"))
        assert isinstance(dfn_a, str)
        pair.db.add_transaction(
            _seed_txn(company="Store B", amount=30.0, file_name="b.eml", date="02/16/2026 10:30 PST")
        )
        pair.db.set_ignored(FORWARDED_TO, dfn_a, ignored=True)

        result = pair.summary.get_summary("2026-02")
        assert result["total_spending"] == Decimal(30)
        assert result["spending_count"] == 1

    # -- get_summary_with_comparison: month-over-month parity ---------------

    def test_comparison_current_previous_and_delta(self, pair: _Pair) -> None:
        pair.db.add_transaction(
            _seed_txn(company="Feb Store", amount=200.0, file_name="feb.eml", date="02/10/2026 10:00 PST")
        )
        pair.db.add_transaction(
            _seed_txn(company="Jan Store", amount=100.0, file_name="jan.eml", date="01/10/2026 10:00 PST")
        )
        result = pair.summary.get_summary_with_comparison("2026-02")
        assert result["current"]["year_month"] == "2026-02"
        assert result["previous"]["year_month"] == "2026-01"
        assert result["current"]["total_spending"] == Decimal(200)
        assert result["previous"]["total_spending"] == Decimal(100)
        assert result["delta_amount"] == Decimal(100)
        assert result["delta_percent"] == 100.0

    def test_comparison_zero_previous_yields_infinite_delta_percent(self, pair: _Pair) -> None:
        pair.db.add_transaction(
            _seed_txn(company="Feb Store", amount=150.0, file_name="feb.eml", date="02/10/2026 10:00 PST")
        )
        result = pair.summary.get_summary_with_comparison("2026-02")
        assert result["previous"]["total_spending"] == Decimal(0)
        assert result["delta_percent"] == float("inf")

    def test_comparison_both_zero_yields_flat_delta(self, pair: _Pair) -> None:
        result = pair.summary.get_summary_with_comparison("2030-09")
        assert result["delta_amount"] == Decimal(0)
        assert result["delta_percent"] == 0.0
