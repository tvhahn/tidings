"""Tests for add_statement_transaction() in TransactionsDB."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.finance.transaction_db import TransactionsDB, generate_transaction_hash


@pytest.fixture
def db() -> TransactionsDB:
    dyn = MagicMock()
    return TransactionsDB(dyn)


@pytest.fixture
def valid_txn() -> dict[str, Any]:
    return {
        "forwarded_to": "test@example.com",
        "date": "2026-01-15",
        "amount": 98.75,
        "company": "Northwind Energy Co",
        "institution": "RBC",
        "transaction_type": "withdrawal",
        "category": "utilities",
        "statement_source": "RBC_Chequing_2026-01",
        "raw_description": "BillPayment WestlandUtilityCo",
    }


class TestRequiredFieldValidation:
    @pytest.mark.parametrize(
        "missing_field",
        [
            "forwarded_to",
            "date",
            "amount",
            "company",
            "institution",
            "transaction_type",
            "category",
            "statement_source",
        ],
    )
    def test_missing_required_field_returns_none(
        self, db: TransactionsDB, valid_txn: dict[str, Any], missing_field: str
    ) -> None:
        del valid_txn[missing_field]
        result = db.add_statement_transaction(valid_txn)
        assert result is None


class TestSyntheticDateFileName:
    def test_format(self, db: TransactionsDB, valid_txn: dict[str, Any]) -> None:
        table = MagicMock()
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        result = db.add_statement_transaction(valid_txn)

        assert result is not None
        assert result is not False
        assert isinstance(result, str)
        assert result.startswith("2026.01.15_00.00_stmt_RBC_")
        assert result.endswith(".pdf")
        # 8-char hash in the filename
        parts = result.replace(".pdf", "").split("_")
        assert len(parts[-1]) == 8


class TestSyntheticDate:
    def test_date_format(self, db: TransactionsDB, valid_txn: dict[str, Any]) -> None:
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn)

        put_call = table.put_item.call_args
        item = put_call[1]["Item"] if "Item" in put_call[1] else put_call[0][0]
        # Synthetic statement dates use %z offset (drops the tz abbreviation
        # so non-Pacific OSS users don't produce ambiguous tokens).
        # January in America/Los_Angeles (default) is PST = UTC-8 = -0800.
        assert item["Date"] == "01/15/2026 00:00 -0800"


class TestDynamoDBItemShape:
    def test_item_has_required_fields(self, db: TransactionsDB, valid_txn: dict[str, Any]) -> None:
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn)

        item = table.put_item.call_args[1]["Item"]
        assert item["ForwardedTo"] == "test@example.com"
        assert item["Amount"] == Decimal("98.75")
        assert item["Company"] == "Northwind Energy Co"
        assert item["Category"] == "utilities"
        assert item["Institution"] == "RBC"
        assert item["TransactionType"] == "withdrawal"
        assert item["StatementSource"] == "RBC_Chequing_2026-01"
        assert "TransactionHash" in item

    def test_no_email_fields(self, db: TransactionsDB, valid_txn: dict[str, Any]) -> None:
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn)

        item = table.put_item.call_args[1]["Item"]
        for field in ["FromName", "FromEmail", "ToName", "ToEmail", "Subject", "Body", "FileName"]:
            assert field not in item

    def test_optional_name_and_user_id(self, db: TransactionsDB, valid_txn: dict[str, Any]) -> None:
        valid_txn["name"] = "John"
        valid_txn["user_id"] = "default"
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn)

        item = table.put_item.call_args[1]["Item"]
        assert item["Name"] == "John"
        assert item["UserId"] == "default"


class TestCategoryAudit:
    def test_audit_source_is_statement_import(self, db: TransactionsDB, valid_txn: dict[str, Any]):
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn)

        item = table.put_item.call_args[1]["Item"]
        assert item["CategoryAudit"]["source"] == "statement_import"
        assert "reviewed_at" in item["CategoryAudit"]

    def test_custom_audit_source(self, db: TransactionsDB, valid_txn: dict[str, Any]):
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn, audit_source="manual")

        item = table.put_item.call_args[1]["Item"]
        assert item["CategoryAudit"]["source"] == "manual"


class TestDuplicateDetection:
    def test_duplicate_returns_false(self, db: TransactionsDB, valid_txn: dict[str, Any]):
        table = MagicMock()
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 1, "Items": [{"ForwardedTo": "x"}]}

        result = db.add_statement_transaction(valid_txn)
        assert result is False

    def test_not_duplicate_writes_and_returns_date_file_name(self, db: TransactionsDB, valid_txn: dict[str, Any]):
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        result = db.add_statement_transaction(valid_txn)
        assert result is not None
        assert result is not False
        assert table.put_item.called


class TestRawDescriptionHash:
    def test_hash_uses_raw_description(self, db: TransactionsDB, valid_txn: dict[str, Any]):
        """Hash should use raw_description, not cleaned company name."""
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn)

        item = table.put_item.call_args[1]["Item"]
        expected_hash = generate_transaction_hash(
            {
                "forwarded_to": "test@example.com",
                "institution": "RBC",
                "amount": 98.75,
                "company": "BillPayment WestlandUtilityCo",  # raw_description
                "date": "2026-01-15",
                "transaction_type": "withdrawal",
            }
        )
        assert item["TransactionHash"] == expected_hash

    def test_hash_falls_back_to_company_if_no_raw(self, db: TransactionsDB, valid_txn: dict[str, Any]):
        """Without raw_description, hash uses company."""
        del valid_txn["raw_description"]
        table = MagicMock(name="dynamodb_table")
        db.dyn_resource.Table.return_value = table
        table.query.return_value = {"Count": 0, "Items": []}

        db.add_statement_transaction(valid_txn)

        item = table.put_item.call_args[1]["Item"]
        expected_hash = generate_transaction_hash(
            {
                "forwarded_to": "test@example.com",
                "institution": "RBC",
                "amount": 98.75,
                "company": "Northwind Energy Co",  # cleaned company
                "date": "2026-01-15",
                "transaction_type": "withdrawal",
            }
        )
        assert item["TransactionHash"] == expected_hash
