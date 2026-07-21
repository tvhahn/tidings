"""Behavioral contract for the dual-backend service pairs.

Of the 7 dual-backend service pairs, this file covers 5 (MerchantAlias,
Category, Override, Budget, Transactions) plus the CategoryIcon twin; the
remaining two pairs live in sibling files — the spending-summary pair in
``test_spending_summary_contract.py`` and the parse-failure store in
``test_parse_failure_store.py``.

CLAUDE.md tells contributors to update both implementations when changing a
config service, but no test enforces parity — the audit (/review-tests) flagged
the resulting drift risk (DynamoDB-side modules at 64-89% coverage; SQLite
twins at 95-100%).

This file fills that gap: each ``Test*Contract`` class is parametrized over
``(dynamodb, sqlite)``, so every scenario runs against *both* implementations
and asserts identical observable behavior. If one twin diverges in shape,
return value, exception type, or version-bump cadence, the assertion fails
and the diff points at exactly which protocol is broken.

Backends
--------
- DynamoDB-side: real ``boto3`` resource against a ``moto`` in-memory fake.
  Concrete tables (``CategoryConfig``, ``BudgetConfig``, ``Transactions``)
  are created once per test via ``mock_aws``, so optimistic-locking
  (``ConditionExpression``) and update-expression evaluation runs through
  the same code path that production uses.
- SQLite-side: ``tmp_path``-scoped DB file via the existing ``*_local``
  classes — no mocking, real schema migrations and queries.

JSON-backup writes (``_write_backup``) are stubbed in both backends so tests
don't touch the developer's ``data/config/`` directory.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest
from botocore.exceptions import ClientError

from src.finance.budget_service import BudgetService
from src.finance.budget_service_local import BudgetServiceLocal
from src.finance.category_icon_service import CategoryIconService
from src.finance.category_icon_service_local import CategoryIconServiceLocal
from src.finance.category_service import CategoryService
from src.finance.category_service_local import CategoryServiceLocal
from src.finance.exceptions import VersionConflictError
from src.finance.merchant_alias_service import MerchantAliasService
from src.finance.merchant_alias_service_local import MerchantAliasServiceLocal
from src.finance.override_service import OverrideService
from src.finance.override_service_local import OverrideServiceLocal
from src.finance.transaction_db import TransactionsDB
from src.finance.transaction_db_base import TransactionsDBBase
from src.finance.transaction_db_local import TransactionsDBLocal

if TYPE_CHECKING:
    from pathlib import Path


# The shared moto ``dyn_resource`` fixture (a real boto3 resource with the
# CategoryConfig/BudgetConfig/Transactions tables provisioned) lives in
# tests/unit/conftest.py so any unit test can opt into storage fidelity.


def _silence_backup(svc: Any) -> Any:
    """Stub the JSON-backup writer so tests don't pollute ``data/config/``."""
    svc._write_backup = lambda *_a, **_kw: None
    return svc


# ---------------------------------------------------------------------------
# MerchantAliasService contract
# ---------------------------------------------------------------------------


class TestMerchantAliasContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def service(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> Any:
        if request.param == "dynamodb":
            return _silence_backup(MerchantAliasService(dyn_resource=dyn_resource))
        return _silence_backup(MerchantAliasServiceLocal(db_path=tmp_path / "aliases.db"))

    def test_returns_none_when_unseeded(self, service: Any) -> None:
        assert service.get_aliases() is None
        assert service.get_aliases_map() == {}

    def test_put_then_get_round_trips(self, service: Any) -> None:
        v = service.put_alias("COSTCO #1234", "Costco")
        assert v == 1
        # Both backends lowercase the storage key.
        assert service.get_aliases_map() == {"costco #1234": "Costco"}

    def test_version_increments_per_mutation(self, service: Any) -> None:
        assert service.put_alias("a", "A") == 1
        assert service.put_alias("b", "B") == 2
        assert service.put_alias("a", "A2") == 3  # update bumps too

    def test_delete_missing_raises_key_error(self, service: Any) -> None:
        with pytest.raises(KeyError):
            service.delete_alias("never-existed")

    def test_delete_existing_removes_entry(self, service: Any) -> None:
        service.put_alias("a", "A")
        service.put_alias("b", "B")
        service.delete_alias("a")
        assert service.get_aliases_map() == {"b": "B"}


# ---------------------------------------------------------------------------
# CategoryService contract
# ---------------------------------------------------------------------------


class TestCategoryServiceContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def service(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> Any:
        if request.param == "dynamodb":
            return _silence_backup(CategoryService(dyn_resource=dyn_resource))
        return _silence_backup(CategoryServiceLocal(db_path=tmp_path / "categories.db"))

    def test_unseeded_get_returns_none(self, service: Any) -> None:
        assert service.get_categories() is None

    def test_add_persists_and_lists(self, service: Any) -> None:
        # `get_categories_list()` falls back to disk defaults until a row
        # exists, so we baseline against pre-add state rather than asserting
        # an exact set.
        baseline = set(service.get_categories_list())
        service.add_category("ContractA")
        service.add_category("ContractB")
        listed = set(service.get_categories_list())
        assert "ContractA" in listed
        assert "ContractB" in listed
        assert listed >= baseline

    def test_add_duplicate_raises_value_error(self, service: Any) -> None:
        service.add_category("ContractDup")
        with pytest.raises(ValueError, match="already exists"):
            service.add_category("ContractDup")

    def test_rename_updates(self, service: Any) -> None:
        service.add_category("ContractOld")
        service.rename_category("ContractOld", "ContractNew")
        listed = service.get_categories_list()
        assert "ContractNew" in listed
        assert "ContractOld" not in listed

    def test_delete_removes(self, service: Any) -> None:
        service.add_category("ContractDelMe")
        service.delete_category("ContractDelMe")
        assert "ContractDelMe" not in service.get_categories_list()


# ---------------------------------------------------------------------------
# OverrideService contract
# ---------------------------------------------------------------------------


class TestOverrideServiceContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def service(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> Any:
        if request.param == "dynamodb":
            return _silence_backup(OverrideService(dyn_resource=dyn_resource))
        return _silence_backup(OverrideServiceLocal(db_path=tmp_path / "overrides.db"))

    def test_unseeded_returns_none(self, service: Any) -> None:
        assert service.get_overrides() is None

    def test_put_then_lookup(self, service: Any) -> None:
        service.put_override("AMAZON.CA", "Miscellaneous")
        item = service.get_overrides()
        assert item is not None
        assert item["Data"]["AMAZON.CA"] == "Miscellaneous"

    def test_lookup_category_finds_exact_match(self, service: Any) -> None:
        service.put_override("Costco", "Groceries")
        assert service.lookup_category("Costco") == "Groceries"

    def test_delete_missing_raises(self, service: Any) -> None:
        with pytest.raises((KeyError, ValueError)):
            service.delete_override("never-existed")


# ---------------------------------------------------------------------------
# CategoryIconService contract
# ---------------------------------------------------------------------------


class TestCategoryIconServiceContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def service(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> Any:
        if request.param == "dynamodb":
            return _silence_backup(CategoryIconService(dyn_resource=dyn_resource))
        return _silence_backup(CategoryIconServiceLocal(db_path=tmp_path / "icons.db"))

    # Both backends store the override map keyed by lowercased category name;
    # the contract is *parity*, not the case convention itself.

    def test_set_then_get(self, service: Any) -> None:
        service.set_icon("Groceries", "ShoppingCart")
        assert service.get_icons_map().get("groceries") == "ShoppingCart"

    def test_clear_removes_override(self, service: Any) -> None:
        service.set_icon("Rent", "Home")
        service.clear_icon("Rent")
        assert "rent" not in service.get_icons_map()

    def test_rename_propagates(self, service: Any) -> None:
        service.set_icon("Food", "Utensils")
        service.rename_category("Food", "Dining")
        m = service.get_icons_map()
        assert m.get("dining") == "Utensils"
        assert "food" not in m


# ---------------------------------------------------------------------------
# BudgetService contract — narrower than the others because the API also
# touches historical-averages logic that depends on a SpendingSummary impl.
# Stick to the storage primitives.
# ---------------------------------------------------------------------------


class TestBudgetServiceContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def service(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> Any:
        if request.param == "dynamodb":
            return BudgetService(dyn_resource=dyn_resource)
        return BudgetServiceLocal(db_path=tmp_path / "budget.db")

    def test_unseeded_returns_none(self, service: Any) -> None:
        assert service.get_targets(2026) is None
        assert service.get_groups(2026) is None

    def test_put_targets_round_trip(self, service: Any) -> None:
        targets = {
            "spending_ceiling": 5000,
            "categories": {
                "groceries": {
                    "target": 600,
                    "input_mode": "monthly",
                    "monthly_amount": 600,
                    "category_type": "variable",
                },
            },
        }
        v = service.put_targets(2026, targets, expected_version=None)
        assert v == 1
        item = service.get_targets(2026)
        assert item is not None
        assert int(item["Data"]["spending_ceiling"]) == 5000

    def test_version_conflict_raises(self, service: Any) -> None:
        service.put_targets(2026, {"spending_ceiling": 1, "categories": {}}, expected_version=None)
        with pytest.raises(VersionConflictError):
            service.put_targets(2026, {"spending_ceiling": 2, "categories": {}}, expected_version=99)

    def test_put_groups_round_trip(self, service: Any) -> None:
        groups = [{"name": "Essentials", "categories": ["groceries", "rent"]}]
        v = service.put_groups(2026, {"groups": groups}, expected_version=None)
        assert v == 1
        item = service.get_groups(2026)
        assert item is not None
        assert item["Data"]["groups"][0]["name"] == "Essentials"


# ---------------------------------------------------------------------------
# TransactionsDB contract — the highest-risk gap (DynamoDB at 71% coverage,
# SQLite at 95%). Beyond add/get_item/set_ignored/get_latest_date_file_name,
# this exercises the update / query / delete surface (update_category,
# update_fields, enrich_transaction, mark_category_reviewed, set_deleted,
# set_comment, permanently_delete, update_context, scan_by_category,
# count_by_category, query_month_partition, scan_all_transactions,
# get_recent_audits) — the real-boto3 paths that MagicMock tests never run.
# ---------------------------------------------------------------------------


def _seed_txn(**overrides: Any) -> dict[str, Any]:
    base = {
        "forwarded_to": "user@example.com",
        "date": "02/15/2026 10:30 PST",
        "amount": 42.50,
        "company": "Test Store",
        "category": "groceries",
        "institution": "RBC",
        "transaction_type": "purchase",
        "name": "Alice",
        "subject": "Receipt",
        "body": "$42.50",
        "file_name": "fixture.eml",
    }
    base.update(overrides)
    return base


def _num(value: Any) -> float:
    """Normalize a numeric across backends — DynamoDB returns Decimal, SQLite float."""
    return float(value)


class TestTransactionsDBContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def db(
        self,
        request: pytest.FixtureRequest,
        dyn_resource: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Any:
        # ``get_latest_date_file_name`` on the DynamoDB twin queries one
        # partition per address returned by user_mapping.get_forwarded_to_addresses().
        # Pin to the seeded address so the test doesn't depend on the
        # contributor's data/config/user_mappings.csv.
        monkeypatch.setattr(
            "src.finance.user_mapping.get_forwarded_to_addresses",
            lambda: ["user@example.com"],
        )
        if request.param == "dynamodb":
            return TransactionsDB(dyn_resource=dyn_resource)
        return TransactionsDBLocal(db_path=tmp_path / "txns.db")

    def test_add_returns_truthy_date_file_name(self, db: Any) -> None:
        result = db.add_transaction(_seed_txn())
        # Both backends return a string (DateFileName) on success; SQLite may
        # also return False on dup, DynamoDB may return None on a swallowed
        # ClientError. Truthy-ness is the contract.
        assert result, f"expected truthy result, got {result!r}"

    def test_duplicate_add_returns_falsy(self, db: Any) -> None:
        db.add_transaction(_seed_txn())
        result = db.add_transaction(_seed_txn())
        assert not result, f"expected falsy on dup, got {result!r}"

    def test_get_latest_date_file_name(self, db: Any) -> None:
        assert db.get_latest_date_file_name() is None
        db.add_transaction(_seed_txn(date="02/15/2026 10:30 PST"))
        db.add_transaction(_seed_txn(date="02/16/2026 10:30 PST", file_name="other.eml"))
        latest = db.get_latest_date_file_name()
        assert latest is not None
        assert "2026.02.16" in latest

    def test_set_ignored_round_trip(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn())
        assert isinstance(dfn, str)
        db.set_ignored("user@example.com", dfn, ignored=True)
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert bool(item.get("Ignored")) is True

    def test_extraction_audit_round_trips(self, db: Any) -> None:
        """add_transaction(extraction_audit=...) persists an intact ExtractionAudit map.

        The map carries a string method, a string model, a bool, and an int
        schema_version — DynamoDB coerces ints to Decimal on the wire, so the
        contract is value-equality after the int() round, not type identity.
        """
        audit = {
            "method": "ai_fallback",
            "model": "gpt-5.4-nano",
            "validated": True,
            "extracted_at": "2026-06-09T12:00:00-07:00",
            "schema_version": 1,
        }
        dfn = db.add_transaction(_seed_txn(), extraction_audit=audit)
        assert isinstance(dfn, str)
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        stored = item.get("ExtractionAudit")
        assert stored is not None, "ExtractionAudit missing from stored row"
        assert stored.get("method") == "ai_fallback"
        assert stored.get("model") == "gpt-5.4-nano"
        assert bool(stored.get("validated")) is True
        assert stored.get("extracted_at") == "2026-06-09T12:00:00-07:00"
        # DynamoDB stores ints as Decimal; SQLite round-trips JSON ints.
        assert int(stored.get("schema_version")) == 1

    def test_extraction_audit_absent_when_not_provided(self, db: Any) -> None:
        """A plain add_transaction leaves no ExtractionAudit on the row."""
        dfn = db.add_transaction(_seed_txn())
        assert isinstance(dfn, str)
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item.get("ExtractionAudit") is None

    # -- update surface -----------------------------------------------------

    def test_update_category_returns_old_and_lowercases(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn(category="groceries"))
        old = db.update_category("user@example.com", dfn, "Dining", source="manual")
        assert old == "groceries"
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        # Both backends lowercase the stored category and stamp the audit source.
        assert item["Category"] == "dining"
        assert item["CategoryAudit"]["source"] == "manual"

    def test_mark_category_reviewed_writes_audit_without_changing_category(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn(category="groceries"))
        db.mark_category_reviewed("user@example.com", dfn, source="audit")
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Category"] == "groceries"
        assert item["CategoryAudit"]["source"] == "audit"

    def test_update_fields_returns_old_values_and_applies_new(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn(company="Old Co", amount=10.0, transaction_type="purchase"))
        old = db.update_fields(
            "user@example.com",
            dfn,
            {"company": "New Co", "amount": 25.5, "transaction_type": "refund"},
        )
        assert old is not None
        assert old["old_company"] == "Old Co"
        assert _num(old["old_amount"]) == 10.0
        assert old["old_transaction_type"] == "purchase"
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Company"] == "New Co"
        assert _num(item["Amount"]) == 25.5
        assert item["TransactionType"] == "refund"

    def test_update_fields_empty_returns_none(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn())
        assert db.update_fields("user@example.com", dfn, {}) is None

    def test_enrich_transaction_updates_company_and_category(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn(company="RAW MERCHANT", category="uncategorized"))
        result = db.enrich_transaction("user@example.com", dfn, "Clean Co", "Dining", statement_source="stmt.pdf")
        # No manual audit and a real (non-misc) incoming category → overwrite path.
        assert result == {"old_company": "RAW MERCHANT", "old_category": "uncategorized", "category_preserved": False}
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Company"] == "Clean Co"
        assert item["Category"] == "dining"

    def test_enrich_preserves_manual_category_over_misc_default(self, db: Any) -> None:
        # The real bug's fixture: a manually-set category must survive a
        # statement_enrich whose category defaults to "miscellaneous".
        dfn = db.add_transaction(_seed_txn(company="RAW MERCHANT", category="insurance"))
        db.update_category("user@example.com", dfn, "insurance", source="manual")
        before = db.get_item("user@example.com", dfn)
        assert before is not None
        audit_before = dict(before["CategoryAudit"])

        result = db.enrich_transaction(
            "user@example.com", dfn, "NORTHWINDINS.", "miscellaneous", source="statement_enrich"
        )
        assert result == {"old_company": "RAW MERCHANT", "old_category": "insurance", "category_preserved": True}

        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Company"] == "NORTHWINDINS."  # enrichment still improves the merchant
        assert item["Category"] == "insurance"  # manual intent preserved
        # Audit left byte-identical — no rewrite to statement_enrich.
        assert item["CategoryAudit"]["source"] == "manual"
        assert dict(item["CategoryAudit"]) == audit_before

    def test_enrich_overwrites_ai_sourced_with_real_category(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn(company="RAW MERCHANT", category="groceries"))
        db.update_category("user@example.com", dfn, "groceries", source="ai")
        result = db.enrich_transaction("user@example.com", dfn, "Clean Co", "Dining", source="statement_enrich")
        assert result == {"old_company": "RAW MERCHANT", "old_category": "groceries", "category_preserved": False}
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Company"] == "Clean Co"
        assert item["Category"] == "dining"
        # Audit rewritten; previous state recorded.
        assert item["CategoryAudit"]["source"] == "statement_enrich"
        assert item["CategoryAudit"]["previous_category"] == "groceries"
        assert item["CategoryAudit"]["previous_source"] == "ai"

    def test_enrich_preserves_ai_category_over_misc_default(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn(company="RAW MERCHANT", category="groceries"))
        db.update_category("user@example.com", dfn, "groceries", source="ai")
        before = db.get_item("user@example.com", dfn)
        assert before is not None
        audit_before = dict(before["CategoryAudit"])

        result = db.enrich_transaction("user@example.com", dfn, "Clean Co", "miscellaneous", source="statement_enrich")
        assert result == {"old_company": "RAW MERCHANT", "old_category": "groceries", "category_preserved": True}
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Company"] == "Clean Co"
        assert item["Category"] == "groceries"  # misc default never beats real info
        assert dict(item["CategoryAudit"]) == audit_before  # audit untouched

    def test_enrich_with_manual_source_overwrites_previous_manual(self, db: Any) -> None:
        # The preview-edit path (source="manual") is a fresh explicit user
        # edit and always wins, even over a previously manual row.
        dfn = db.add_transaction(_seed_txn(company="RAW MERCHANT", category="insurance"))
        db.update_category("user@example.com", dfn, "insurance", source="manual")
        result = db.enrich_transaction("user@example.com", dfn, "Clean Co", "Dining", source="manual")
        assert result == {"old_company": "RAW MERCHANT", "old_category": "insurance", "category_preserved": False}
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Category"] == "dining"
        assert item["CategoryAudit"]["source"] == "manual"
        assert item["CategoryAudit"]["previous_category"] == "insurance"
        assert item["CategoryAudit"]["previous_source"] == "manual"

    def test_enrich_statement_reimport_preserves_manual(self, db: Any) -> None:
        # Covers the "update" action path (source="statement_reimport").
        dfn = db.add_transaction(_seed_txn(company="RAW MERCHANT", category="insurance"))
        db.update_category("user@example.com", dfn, "insurance", source="manual")
        result = db.enrich_transaction(
            "user@example.com", dfn, "Clean Co", "miscellaneous", source="statement_reimport"
        )
        assert result == {"old_company": "RAW MERCHANT", "old_category": "insurance", "category_preserved": True}
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Company"] == "Clean Co"
        assert item["Category"] == "insurance"
        assert item["CategoryAudit"]["source"] == "manual"

    def test_enrich_preserves_unaudited_category_over_misc_default(self, db: Any) -> None:
        # No CategoryAudit at all: a real category still beats the misc default.
        dfn = db.add_transaction(_seed_txn(company="RAW MERCHANT", category="insurance"))
        result = db.enrich_transaction("user@example.com", dfn, "Clean Co", "miscellaneous", source="statement_enrich")
        assert result == {"old_company": "RAW MERCHANT", "old_category": "insurance", "category_preserved": True}
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item["Company"] == "Clean Co"
        assert item["Category"] == "insurance"

    def test_update_context_round_trips(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn())
        db.update_context("user@example.com", dfn, {"note": "hi", "score": 5, "flag": True})
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        ctx = item.get("TransactionContext")
        assert ctx is not None, "TransactionContext missing after update_context"
        assert ctx.get("note") == "hi"
        # DynamoDB stores numbers as Decimal; SQLite re-coerces on read — both are Decimal.
        assert _num(ctx.get("score")) == 5
        assert ctx.get("flag") is True

    # -- delete surface -----------------------------------------------------

    def test_set_deleted_round_trip(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn())
        assert db.set_deleted("user@example.com", dfn, deleted=True) is None
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item.get("DeletedAt")  # a timestamp string is present
        db.set_deleted("user@example.com", dfn, deleted=False)
        restored = db.get_item("user@example.com", dfn)
        assert restored is not None
        assert restored.get("DeletedAt") is None

    def test_set_comment_round_trip(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn())
        assert db.set_comment("user@example.com", dfn, "hello") is None
        item = db.get_item("user@example.com", dfn)
        assert item is not None
        assert item.get("Comment") == "hello"
        # Clearing returns the previous value and removes the attribute.
        assert db.set_comment("user@example.com", dfn, None) == "hello"
        cleared = db.get_item("user@example.com", dfn)
        assert cleared is not None
        assert cleared.get("Comment") is None

    def test_permanently_delete_returns_item_then_none(self, db: Any) -> None:
        dfn = db.add_transaction(_seed_txn(company="ByeCo"))
        deleted = db.permanently_delete("user@example.com", dfn)
        assert deleted is not None
        assert deleted.get("Company") == "ByeCo"
        assert db.get_item("user@example.com", dfn) is None
        # A second delete of the now-absent row returns falsy on both backends.
        assert not db.permanently_delete("user@example.com", dfn)

    # -- query surface ------------------------------------------------------

    def test_scan_and_count_by_category_exclude_deleted(self, db: Any) -> None:
        dfn_a = db.add_transaction(_seed_txn(company="Store A", date="02/15/2026 10:30 PST", category="groceries"))
        db.add_transaction(_seed_txn(company="Store B", date="02/16/2026 10:30 PST", category="groceries"))
        db.add_transaction(_seed_txn(company="Diner", date="02/17/2026 10:30 PST", category="dining"))
        # Soft-deleted rows drop out of both scan and count.
        db.set_deleted("user@example.com", dfn_a, deleted=True)

        assert db.count_by_category("groceries") == 1
        keys = db.scan_by_category("groceries")
        assert len(keys) == 1
        assert keys[0]["ForwardedTo"] == "user@example.com"
        assert "DateFileName" in keys[0]
        # Query is case-insensitive on both backends.
        assert db.count_by_category("Dining") == 1
        assert db.count_by_category("nonexistent") == 0
        assert db.scan_by_category("nonexistent") == []

    def test_query_month_partition_scopes_to_month(self, db: Any) -> None:
        db.add_transaction(_seed_txn(company="Feb Store", amount=10.0, date="02/15/2026 10:30 PST"))
        db.add_transaction(_seed_txn(company="Mar Store", amount=20.0, date="03/20/2026 10:30 PST"))

        feb = db.query_month_partition("user@example.com", "2026-02")
        assert len(feb) == 1
        assert feb[0]["Company"] == "Feb Store"
        assert _num(feb[0]["Amount"]) == 10.0
        assert len(db.query_month_partition("user@example.com", "2026-03")) == 1
        assert db.query_month_partition("user@example.com", "2026-04") == []

    def test_scan_all_transactions_returns_every_row(self, db: Any) -> None:
        db.add_transaction(_seed_txn(company="A", date="02/15/2026 10:30 PST"))
        db.add_transaction(_seed_txn(company="B", date="02/16/2026 10:30 PST"))
        rows = db.scan_all_transactions()
        assert len(rows) == 2
        assert {r["Company"] for r in rows} == {"A", "B"}
        # Both backends return rows sorted ascending by DateFileName.
        assert [r["DateFileName"] for r in rows] == sorted(r["DateFileName"] for r in rows)

    def test_get_recent_audits_newest_first_bounded_and_excludes_deleted(self, db: Any) -> None:
        db.add_transaction(_seed_txn(company="A", date="02/15/2026 10:30 PST", category="groceries"))
        dfn_b = db.add_transaction(_seed_txn(company="B", date="02/16/2026 10:30 PST", category="dining"))
        db.add_transaction(_seed_txn(company="C", date="02/17/2026 10:30 PST", category="transport"))
        db.set_deleted("user@example.com", dfn_b, deleted=True)

        audits = db.get_recent_audits(limit=25)
        assert len(audits) == 2  # soft-deleted row excluded
        cats = [a["Category"].lower() for a in audits]
        assert set(cats) == {"groceries", "transport"}
        assert cats[0] == "transport"  # newest DateFileName first
        # The limit is honored and returns the newest row.
        limited = db.get_recent_audits(limit=1)
        assert len(limited) == 1
        assert limited[0]["Category"].lower() == "transport"


# ---------------------------------------------------------------------------
# bulk_add_transactions error semantics (AUDIT Q2 / L7)
#
# The writer helpers now RAISE on infrastructure failure instead of returning
# None, and ``bulk_add_transactions`` catches per-row exceptions into a distinct
# ``errors`` bucket. This must hold identically for both backends: an
# infrastructure exception is an ``errors`` row, while a bad-data row (missing
# amount) stays an ``invalid`` row — the two are never conflated.
# ---------------------------------------------------------------------------


class TestBulkImportErrorSemantics:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def db_and_error(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> tuple[Any, Exception]:
        """Return (db, representative_infrastructure_error) for each backend."""
        if request.param == "dynamodb":
            return (
                TransactionsDB(dyn_resource=dyn_resource),
                ClientError({"Error": {"Code": "InternalServerError", "Message": "boom"}}, "PutItem"),
            )
        return (
            TransactionsDBLocal(db_path=tmp_path / "txns.db"),
            sqlite3.OperationalError("database is locked"),
        )

    def test_infra_failure_counts_as_error_not_invalid(
        self, db_and_error: tuple[Any, Exception], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A write that raises mid-batch lands in ``errors`` — not ``invalid`` — and the batch keeps going."""
        db, infra_error = db_and_error
        real_insert = db._insert_imported

        def flaky_insert(row: dict[str, Any], audit: Any, occurrence: int = 0) -> Any:
            if row.get("company") == "Boom Co":
                raise infra_error
            return real_insert(row, audit, occurrence=occurrence)

        monkeypatch.setattr(db, "_insert_imported", flaky_insert)
        rows = [
            _seed_txn(company="Good Co", amount=10.0, date="02/15/2026 10:30 PST"),
            _seed_txn(company="Boom Co", amount=20.0, date="02/16/2026 10:30 PST"),
        ]
        counts = db.bulk_add_transactions(rows, strategy="skip")
        assert counts["inserted"] == 1
        assert counts["errors"] == 1
        assert counts["invalid"] == 0

    def test_invalid_data_and_infra_failure_are_distinct_buckets(
        self, db_and_error: tuple[Any, Exception], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One batch with a bad-data row AND an infrastructure failure pins the two buckets apart."""
        db, infra_error = db_and_error
        real_insert = db._insert_imported

        def flaky_insert(row: dict[str, Any], audit: Any, occurrence: int = 0) -> Any:
            if row.get("company") == "Boom Co":
                raise infra_error
            return real_insert(row, audit, occurrence=occurrence)

        monkeypatch.setattr(db, "_insert_imported", flaky_insert)
        rows = [
            _seed_txn(company="Good Co", amount=10.0, date="02/15/2026 10:30 PST"),
            _seed_txn(company="No Amount Co", amount=None, date="02/16/2026 10:30 PST"),  # invalid data
            _seed_txn(company="Boom Co", amount=20.0, date="02/17/2026 10:30 PST"),  # infra failure
        ]
        counts = db.bulk_add_transactions(rows, strategy="skip")
        assert counts["inserted"] == 1
        assert counts["invalid"] == 1
        assert counts["errors"] == 1


# ---------------------------------------------------------------------------
# _resolve_enrich_category — pure decision function (storage-agnostic)
# ---------------------------------------------------------------------------


class TestResolveEnrichCategory:
    _resolve = staticmethod(TransactionsDBBase._resolve_enrich_category)  # pyright: ignore[reportPrivateUsage]

    def test_falsy_existing_category_never_preserved(self) -> None:
        assert self._resolve(None, "manual", "miscellaneous", "statement_enrich") is False
        assert self._resolve("", "manual", "miscellaneous", "statement_enrich") is False

    def test_equal_category_not_preserved(self) -> None:
        # No-op write is fine — case-insensitive equality short-circuits to False.
        assert self._resolve("Insurance", "manual", "insurance", "statement_enrich") is False

    def test_manual_incoming_source_always_overwrites(self) -> None:
        assert self._resolve("insurance", "manual", "dining", "manual") is False

    def test_manual_existing_source_preserved(self) -> None:
        assert self._resolve("insurance", "manual", "dining", "statement_enrich") is True

    def test_misc_incoming_over_real_existing_preserved(self) -> None:
        assert self._resolve("groceries", "ai", "miscellaneous", "statement_enrich") is True
        assert self._resolve("groceries", None, "miscellaneous", "statement_enrich") is True

    def test_non_manual_real_incoming_overwrites(self) -> None:
        assert self._resolve("groceries", "ai", "dining", "statement_enrich") is False
