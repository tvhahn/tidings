"""Ingestion hook: a NEW transaction whose Company matches an ignore rule
arrives Ignored at write time, in both storage backends.

The write-time lookup goes through ``config_loader.get_ignore_context`` (a
module-global cached read from storage). These tests patch that seam directly so
they never touch the real ``data/`` config or DB — matching the isolation the
override tests rely on.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import src.finance.config_loader as config_module
from src.finance.transaction_db import TransactionsDB
from src.finance.transaction_db_local import TransactionsDBLocal

FORWARDED_TO = "user@example.com"


def _txn(**overrides: Any) -> dict[str, Any]:
    data = {
        "forwarded_to": FORWARDED_TO,
        "file_name": "test.eml",
        "date": "02/15/2026 10:30 PST",
        "amount": 42.50,
        "company": "MAPLETRADE INC.",
        "category": "investments",
        "institution": "RBC",
        "transaction_type": "purchase",
    }
    data.update(overrides)
    return data


@pytest.fixture
def patch_rules(monkeypatch: pytest.MonkeyPatch):
    """Return a setter that pins the ignore-rule context for the write path."""

    def _set(patterns: list[str], aliases: dict[str, str] | None = None) -> None:
        monkeypatch.setattr(config_module, "get_ignore_context", lambda: (patterns, aliases or {}))

    return _set


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------


class TestSqliteIngestion:
    def test_matching_transaction_arrives_ignored(self, tmp_path: Path, patch_rules) -> None:
        patch_rules(["MAPLETRADE INC."])
        db = TransactionsDBLocal(db_path=tmp_path / "t.db")
        dfn = db.add_transaction(_txn())
        assert isinstance(dfn, str)
        item = db.get_item(FORWARDED_TO, dfn)
        assert item is not None
        assert item["Ignored"] is True

    def test_normalized_match_arrives_ignored(self, tmp_path: Path, patch_rules) -> None:
        patch_rules(["MiscPayment CARDCO #221"])
        db = TransactionsDBLocal(db_path=tmp_path / "t.db")
        dfn = db.add_transaction(_txn(company="MiscPayment CARDCO #888"))
        assert isinstance(dfn, str)
        assert db.get_item(FORWARDED_TO, dfn)["Ignored"] is True

    def test_non_matching_transaction_not_ignored(self, tmp_path: Path, patch_rules) -> None:
        patch_rules(["MAPLETRADE INC."])
        db = TransactionsDBLocal(db_path=tmp_path / "t.db")
        dfn = db.add_transaction(_txn(company="STARBUCKS", category="dining"))
        assert isinstance(dfn, str)
        # Ignored defaults to False (row_to_item omits falsy ignored → key absent).
        assert db.get_item(FORWARDED_TO, dfn).get("Ignored", False) is False

    def test_no_rules_means_not_ignored(self, tmp_path: Path, patch_rules) -> None:
        patch_rules([])
        db = TransactionsDBLocal(db_path=tmp_path / "t.db")
        dfn = db.add_transaction(_txn())
        assert isinstance(dfn, str)
        assert db.get_item(FORWARDED_TO, dfn).get("Ignored", False) is False

    def test_explicit_ignored_flag_honored(self, tmp_path: Path, patch_rules) -> None:
        patch_rules([])
        db = TransactionsDBLocal(db_path=tmp_path / "t.db")
        dfn = db.add_transaction(_txn(company="STARBUCKS", ignored=True))
        assert isinstance(dfn, str)
        assert db.get_item(FORWARDED_TO, dfn)["Ignored"] is True


# ---------------------------------------------------------------------------
# DynamoDB backend
# ---------------------------------------------------------------------------


def _dynamo_db() -> tuple[TransactionsDB, MagicMock]:
    table = MagicMock(name="table")
    table.query.return_value = {"Count": 0, "Items": []}  # dedup check: no existing row
    table.put_item.return_value = {}
    dyn = MagicMock()
    dyn.Table.return_value = table
    return TransactionsDB(dyn), table


class TestDynamoIngestion:
    def test_matching_transaction_sets_ignored(self, patch_rules) -> None:
        patch_rules(["MAPLETRADE INC."])
        db, table = _dynamo_db()
        result = db.add_transaction(_txn())
        assert isinstance(result, str)
        item = table.put_item.call_args[1]["Item"]
        assert item["Ignored"] is True

    def test_non_matching_transaction_omits_ignored(self, patch_rules) -> None:
        patch_rules(["MAPLETRADE INC."])
        db, table = _dynamo_db()
        result = db.add_transaction(_txn(company="STARBUCKS"))
        assert isinstance(result, str)
        item = table.put_item.call_args[1]["Item"]
        assert "Ignored" not in item
