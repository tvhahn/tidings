"""Tests for TransactionsDBLocal — SQLite-backed transaction storage."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from src.finance.transaction_db_local import TransactionsDBLocal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FORWARDED_TO = "user@example.com"


def _base_txn(**overrides: Any) -> dict[str, Any]:
    """Minimal valid transaction dict accepted by add_transaction()."""
    data = {
        "forwarded_to": FORWARDED_TO,
        "file_name": "test.eml",
        "date": "02/15/2026 10:30 PST",
        "amount": 42.50,
        "company": "Test Store",
        "category": "groceries",
        "institution": "RBC",
        "transaction_type": "purchase",
        "user_id": "alice",
        "name": "Alice",
        "from_name": "RBC",
        "from_email": "alerts@rbc.com",
        "to_name": "Alice",
        "to_email": FORWARDED_TO,
        "subject": "Transaction Alert",
        "body": "You spent $42.50",
    }
    data.update(overrides)
    return data


@pytest.fixture
def db(tmp_path: Path) -> TransactionsDBLocal:
    return TransactionsDBLocal(db_path=tmp_path / "test.db")


# ---------------------------------------------------------------------------
# add_transaction
# ---------------------------------------------------------------------------


class TestAddTransaction:
    def test_returns_date_file_name(self, db: Any) -> None:
        result = db.add_transaction(_base_txn())
        assert result is not False
        assert result is not None
        assert "test.eml" in result

    def test_missing_required_field_returns_none(self, db: Any) -> None:
        txn = _base_txn()
        del txn["forwarded_to"]
        assert db.add_transaction(txn) is None

    @pytest.mark.parametrize("field", ["amount", "institution", "transaction_type"])
    def test_unparsed_email_shaped_row_is_rejected(self, db: Any, field: str) -> None:
        """Rows that lack parser-produced fields (e.g. Google security alerts
        that fell through parse_email) must not be written.

        `company` is NOT required — RBC withdrawals legitimately have no company.
        """
        txn = _base_txn()
        del txn[field]
        assert db.add_transaction(txn) is None

    def test_rbc_withdrawal_shape_is_accepted(self, db: Any) -> None:
        """RBC withdrawal emails have no company by design; they must still be written."""
        txn = _base_txn(transaction_type="withdrawal")
        del txn["company"]
        result = db.add_transaction(txn)
        assert result is not None
        assert result is not False

    def test_duplicate_returns_false(self, db: Any) -> None:
        txn = _base_txn()
        first = db.add_transaction(txn)
        assert first is not False
        second = db.add_transaction(txn)
        assert second is False

    def test_different_companies_are_distinct(self, db: Any) -> None:
        r1 = db.add_transaction(_base_txn(company="Store A", file_name="a.eml"))
        r2 = db.add_transaction(_base_txn(company="Store B", file_name="b.eml"))
        assert r1 is not False
        assert r2 is not False

    def test_category_lowercased(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn(category="Groceries"))
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Category"] == "groceries"

    def test_category_audit_round_trip(self, db: Any) -> None:
        audit = {
            "reviewed_at": "2026-04-15T10:00:00+00:00",
            "source": "override_normalized",
            "matched_rule": "COFFEE SPOT",
            "confidence": 1.0,
        }
        dfn = db.add_transaction(_base_txn(), category_audit=audit)
        item = db.get_item(FORWARDED_TO, dfn)
        assert item["CategoryAudit"] == audit

    def test_no_audit_when_kwarg_omitted(self, db: Any) -> None:
        dfn = db.add_transaction(_base_txn())
        item = db.get_item(FORWARDED_TO, dfn)
        assert "CategoryAudit" not in item


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------


class TestGetItem:
    def test_returns_item(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item is not None
        assert item["Company"] == "Test Store"
        assert item["ForwardedTo"] == FORWARDED_TO

    def test_missing_returns_none(self, db: Any) -> None:
        assert db.get_item(FORWARDED_TO, "nonexistent.eml") is None


# ---------------------------------------------------------------------------
# update_category
# ---------------------------------------------------------------------------


class TestUpdateCategory:
    def test_updates_category(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        old = db.update_category(FORWARDED_TO, date_file_name, "entertainment")
        assert old == "groceries"
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Category"] == "entertainment"

    def test_lowercases_mixed_case_on_update(self, db: Any) -> None:
        """Pin the write-side contract: storage normalizes category to lowercase
        on update_category, matching the add_transaction behavior in
        test_category_lowercased above. An AI that skipped `.lower()` here would
        create inconsistent `Restaurant/Dining` vs `restaurant/dining` values
        and every case-sensitive read (scan_by_category, count_by_category)
        would silently miss them."""
        date_file_name = db.add_transaction(_base_txn())
        db.update_category(FORWARDED_TO, date_file_name, "Restaurant/Dining")
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Category"] == "restaurant/dining"

    def test_sets_category_audit(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        db.update_category(FORWARDED_TO, date_file_name, "entertainment", source="override")
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert "CategoryAudit" in item
        assert item["CategoryAudit"]["source"] == "override"


# ---------------------------------------------------------------------------
# mark_category_reviewed
# ---------------------------------------------------------------------------


class TestMarkCategoryReviewed:
    def test_does_not_change_category(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        db.mark_category_reviewed(FORWARDED_TO, date_file_name, source="audit")
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Category"] == "groceries"
        assert "CategoryAudit" in item


# ---------------------------------------------------------------------------
# set_ignored / set_deleted / set_comment
# ---------------------------------------------------------------------------


class TestFlags:
    def test_set_ignored(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        old = db.set_ignored(FORWARDED_TO, date_file_name, True)
        assert old is False
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Ignored"] is True

    def test_set_deleted(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        old = db.set_deleted(FORWARDED_TO, date_file_name, True)
        assert old is None
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert "DeletedAt" in item

    def test_clear_deleted(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        db.set_deleted(FORWARDED_TO, date_file_name, True)
        db.set_deleted(FORWARDED_TO, date_file_name, False)
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert "DeletedAt" not in item

    def test_set_comment(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        db.set_comment(FORWARDED_TO, date_file_name, "test note")
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Comment"] == "test note"

    def test_clear_comment(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        db.set_comment(FORWARDED_TO, date_file_name, "test note")
        db.set_comment(FORWARDED_TO, date_file_name, None)
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert "Comment" not in item


# ---------------------------------------------------------------------------
# permanently_delete
# ---------------------------------------------------------------------------


class TestPermanentlyDelete:
    def test_returns_item_and_removes_it(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        deleted = db.permanently_delete(FORWARDED_TO, date_file_name)
        assert deleted is not None
        assert deleted["Company"] == "Test Store"
        assert db.get_item(FORWARDED_TO, date_file_name) is None

    def test_missing_returns_none(self, db: Any) -> None:
        assert db.permanently_delete(FORWARDED_TO, "nonexistent.eml") is None


# ---------------------------------------------------------------------------
# scan_by_category / count_by_category / batch_update_category
# ---------------------------------------------------------------------------


class TestCategoryQueries:
    def test_scan_by_category(self, db: Any) -> None:
        db.add_transaction(_base_txn(company="Store A", category="groceries", file_name="a.eml"))
        db.add_transaction(_base_txn(company="Store B", category="entertainment", file_name="b.eml"))
        results = db.scan_by_category("groceries")
        assert len(results) == 1
        assert results[0]["ForwardedTo"] == FORWARDED_TO

    def test_count_by_category(self, db: Any) -> None:
        db.add_transaction(_base_txn(company="Store A", category="groceries", file_name="a.eml"))
        db.add_transaction(_base_txn(company="Store B", category="groceries", file_name="b.eml"))
        assert db.count_by_category("groceries") == 2

    def test_scan_excludes_deleted(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn(category="groceries"))
        db.set_deleted(FORWARDED_TO, date_file_name, True)
        results = db.scan_by_category("groceries")
        assert len(results) == 0

    def test_batch_update_category(self, db: Any) -> None:
        df1 = db.add_transaction(_base_txn(company="A", category="groceries", file_name="a.eml"))
        df2 = db.add_transaction(_base_txn(company="B", category="groceries", file_name="b.eml"))
        items = [
            {"ForwardedTo": FORWARDED_TO, "DateFileName": df1},
            {"ForwardedTo": FORWARDED_TO, "DateFileName": df2},
        ]
        count = db.batch_update_category(items, "food", source="category_rename")
        assert count == 2
        assert db.get_item(FORWARDED_TO, df1)["Category"] == "food"
        assert db.get_item(FORWARDED_TO, df2)["Category"] == "food"


# ---------------------------------------------------------------------------
# update_context
# ---------------------------------------------------------------------------


class TestUpdateContext:
    def test_stores_context(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        ctx = {"category_month_total": 100.0, "merchant_month_count": 3}
        db.update_context(FORWARDED_TO, date_file_name, ctx)
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert "TransactionContext" in item


# ---------------------------------------------------------------------------
# enrich_transaction / update_fields
# ---------------------------------------------------------------------------


class TestEnrichAndUpdateFields:
    def test_enrich_transaction(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        old = db.enrich_transaction(FORWARDED_TO, date_file_name, "Enriched Store", "entertainment")
        # Return dict now carries category_preserved (overwrite path here per the
        # enrich precedence rule — no manual audit + real incoming category).
        assert old == {"old_company": "Test Store", "old_category": "groceries", "category_preserved": False}
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Company"] == "Enriched Store"
        assert item["Category"] == "entertainment"

    def test_enrich_nonexistent_returns_none(self, db: Any) -> None:
        assert db.enrich_transaction(FORWARDED_TO, "ghost.eml", "X", "y") is None

    def test_update_fields_company(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        old = db.update_fields(FORWARDED_TO, date_file_name, {"company": "Updated Store"})
        assert old["old_company"] == "Test Store"
        item = db.get_item(FORWARDED_TO, date_file_name)
        assert item["Company"] == "Updated Store"

    def test_update_fields_empty_returns_none(self, db: Any) -> None:
        date_file_name = db.add_transaction(_base_txn())
        assert db.update_fields(FORWARDED_TO, date_file_name, {}) is None


# ---------------------------------------------------------------------------
# add_statement_transaction
# ---------------------------------------------------------------------------


class TestAddStatementTransaction:
    def _stmt_txn(self, **overrides: Any) -> dict[str, Any]:
        data = {
            "forwarded_to": FORWARDED_TO,
            "date": "2026-01-15",
            "amount": 98.75,
            "company": "Northwind Energy Co",
            "raw_description": "BillPayment WestlandUtilityCo",
            "institution": "RBC",
            "transaction_type": "withdrawal",
            "category": "utilities",
            "statement_source": "RBC_Chequing_2026-01",
            "user_id": "alice",
        }
        data.update(overrides)
        return data

    def test_adds_statement_transaction(self, db: Any) -> None:
        result = db.add_statement_transaction(self._stmt_txn())
        assert result is not None
        assert result is not False
        assert "stmt_RBC" in result

    def test_duplicate_returns_false(self, db: Any) -> None:
        txn = self._stmt_txn()
        db.add_statement_transaction(txn)
        assert db.add_statement_transaction(txn) is False

    def test_missing_required_field_returns_none(self, db: Any) -> None:
        txn = self._stmt_txn()
        del txn["statement_source"]
        assert db.add_statement_transaction(txn) is None


# ---------------------------------------------------------------------------
# query_month_partition
# ---------------------------------------------------------------------------


class TestQueryMonthPartition:
    def test_returns_matching_month(self, db: Any) -> None:
        db.add_transaction(_base_txn(date="02/15/2026 10:30 PST"))
        result = db.query_month_partition(FORWARDED_TO, "2026-02")
        assert len(result) == 1

    def test_empty_month_returns_empty_list(self, db: Any) -> None:
        result = db.query_month_partition(FORWARDED_TO, "2026-02")
        assert result == []

    def test_excludes_other_months(self, db: Any) -> None:
        db.add_transaction(_base_txn(date="02/15/2026 10:30 PST", file_name="feb.eml"))
        db.add_transaction(_base_txn(date="03/10/2026 09:00 PST", file_name="mar.eml"))
        feb = db.query_month_partition(FORWARDED_TO, "2026-02")
        mar = db.query_month_partition(FORWARDED_TO, "2026-03")
        assert len(feb) == 1
        assert len(mar) == 1

    def test_filters_by_forwarded_to(self, db: Any) -> None:
        db.add_transaction(_base_txn(forwarded_to=FORWARDED_TO, file_name="a.eml"))
        db.add_transaction(_base_txn(forwarded_to="other@example.com", file_name="b.eml"))
        result = db.query_month_partition(FORWARDED_TO, "2026-02")
        assert len(result) == 1

    def test_returns_pascal_case_keys(self, db: Any) -> None:
        db.add_transaction(_base_txn())
        item = db.query_month_partition(FORWARDED_TO, "2026-02")[0]
        assert "Amount" in item
        assert "Category" in item
        assert "Company" in item
        assert "TransactionType" in item

    def test_amount_is_decimal(self, db: Any) -> None:
        from decimal import Decimal

        db.add_transaction(_base_txn(amount=42.50))
        item = db.query_month_partition(FORWARDED_TO, "2026-02")[0]
        assert isinstance(item["Amount"], Decimal)
        assert item["Amount"] == Decimal("42.5")

    def test_ignored_is_bool(self, db: Any) -> None:
        dfn = db.add_transaction(_base_txn())
        db.set_ignored(FORWARDED_TO, dfn, True)
        item = db.query_month_partition(FORWARDED_TO, "2026-02")[0]
        assert item.get("Ignored") is True


# ---------------------------------------------------------------------------
# get_latest_date_file_name — freshness probe
# ---------------------------------------------------------------------------


class TestGetLatestDateFileName:
    def test_empty_db_returns_none(self, db: Any) -> None:
        assert db.get_latest_date_file_name() is None
        assert db.get_latest_date_file_name("2026-02") is None

    def test_returns_largest_date_file_name(self, db: Any) -> None:
        db.add_transaction(_base_txn(date="02/15/2026 10:30 PST", file_name="mid.eml"))
        db.add_transaction(_base_txn(date="02/28/2026 20:00 PST", file_name="late.eml"))
        db.add_transaction(_base_txn(date="02/01/2026 08:00 PST", file_name="early.eml"))
        latest = db.get_latest_date_file_name()
        assert latest is not None
        assert latest.startswith("2026.02.28")

    def test_month_filter_scopes_to_that_month(self, db: Any) -> None:
        db.add_transaction(_base_txn(date="02/28/2026 20:00 PST", file_name="feb.eml"))
        db.add_transaction(_base_txn(date="03/02/2026 09:00 PST", file_name="mar.eml"))
        feb_latest = db.get_latest_date_file_name("2026-02")
        mar_latest = db.get_latest_date_file_name("2026-03")
        assert feb_latest is not None
        assert feb_latest.startswith("2026.02.28")
        assert mar_latest is not None
        assert mar_latest.startswith("2026.03.02")

    def test_month_filter_no_match_returns_none(self, db: Any) -> None:
        db.add_transaction(_base_txn(date="02/15/2026 10:30 PST"))
        assert db.get_latest_date_file_name("2026-05") is None

    def test_probe_detects_new_write(self, db: Any) -> None:
        db.add_transaction(_base_txn(date="02/15/2026 10:30 PST", file_name="first.eml"))
        before = db.get_latest_date_file_name("2026-02")
        db.add_transaction(_base_txn(date="02/20/2026 14:00 PST", file_name="second.eml"))
        after = db.get_latest_date_file_name("2026-02")
        assert before is not None
        assert after is not None
        assert after > before


class TestTimezoneRespected:
    """`date_file_name` prefix is local to the configured app timezone."""

    @pytest.fixture
    def set_app_tz(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
        import src.finance.app_config as app_config

        tmp_config = tmp_path / "config.json"
        monkeypatch.setattr(app_config, "_CONFIG_PATH", Path(tmp_config))

        def _apply(tz_name: str) -> None:
            tmp_config.write_text(json.dumps({"timezone": tz_name}))
            app_config.invalidate_config_cache()

        yield _apply
        app_config.invalidate_config_cache()

    def test_berlin_native_date_uses_local_time(self, db: Any, set_app_tz: Callable[[str], None]) -> None:
        set_app_tz("Europe/Berlin")
        # Berlin CEST (April): "23:30 CEST" — date is already in Berlin's zone,
        # so the prefix preserves 23.30 local time without shifting to Pacific.
        result = db.add_transaction(_base_txn(date="04/15/2026 23:30 CEST", file_name="de.eml"))
        assert result is not None
        assert result is not False
        assert result.startswith("2026.04.15_23.30_")

    def test_legacy_pst_suffix_still_resolves_under_berlin_config(
        self, db: Any, set_app_tz: Callable[[str], None]
    ) -> None:
        """Legacy-data invariant: rows with literal ' PST' suffix continue
        to parse as Pacific even when the user has switched to Berlin."""
        set_app_tz("Europe/Berlin")
        result = db.add_transaction(_base_txn(date="02/15/2026 10:30 PST", file_name="legacy.eml"))
        assert result is not None
        assert result is not False
        # 10:30 PST is the stored local time — prefix preserves that literally.
        assert result.startswith("2026.02.15_10.30_")
