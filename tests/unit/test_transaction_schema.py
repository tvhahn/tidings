"""Tests for add_transaction() DynamoDB item schema and Decimal conversion."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.finance.transaction_db import TransactionsDB


def _mock_table() -> MagicMock:
    """Create a mock DynamoDB table that accepts writes."""
    table = MagicMock(name="dynamodb_table")
    table.query.return_value = {"Count": 0, "Items": []}
    table.put_item.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
    return table


def _make_db() -> tuple[TransactionsDB, MagicMock]:
    """Create a TransactionsDB with a mocked DynamoDB resource."""
    dyn_resource = MagicMock()
    table = _mock_table()
    dyn_resource.Table.return_value = table
    db = TransactionsDB(dyn_resource)
    return db, table


def _make_full_transaction(**overrides: Any) -> dict[str, Any]:
    """Build a complete transaction data dict."""
    data: dict[str, Any] = {
        "forwarded_to": "user@example.com",
        "file_name": "emails/test.eml",
        "date": "01/15/2026 14:30 PST",
        "institution": "RBC",
        "amount": 45.67,
        "company": "Starbucks",
        "transaction_type": "purchase",
        "category": "Restaurant/Dining",
        "from_name": "RBC Alerts",
        "from_email": "alerts@rbc.com",
        "to_name": "User",
        "to_email": "user@example.com",
        "subject": "Transaction Alert",
        "body": "A purchase of $45.67 at Starbucks",
        "name": "Demo User",
        "user_id": "default",
    }
    data.update(overrides)
    return data


def _get_put_item(table: MagicMock) -> dict[str, Any]:
    """Extract the Item dict from the last put_item call."""
    call_kwargs = table.put_item.call_args
    return call_kwargs.kwargs.get("Item") or call_kwargs[1]["Item"]


class TestDynamoDBItemSchema:
    """Verify the DynamoDB Item has all expected fields with correct types."""

    def test_all_17_fields_present(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction())
        item = _get_put_item(table)

        expected_fields = [
            "ForwardedTo",
            "DateFileName",
            "FileName",
            "Date",
            "UserId",
            "FromName",
            "FromEmail",
            "ToName",
            "ToEmail",
            "Institution",
            "Subject",
            "Body",
            "Name",
            "Amount",
            "Company",
            "TransactionType",
            "Category",
            "TransactionHash",
        ]
        for field in expected_fields:
            assert field in item, f"Missing field: {field}"

    def test_forwarded_to_matches_input(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(forwarded_to="a@b.com"))
        item = _get_put_item(table)
        assert item["ForwardedTo"] == "a@b.com"

    def test_date_file_name_format(self):
        db, table = _make_db()
        db.add_transaction(
            _make_full_transaction(
                date="01/15/2026 14:30 PST",
                file_name="emails/inbox/test_email.eml",
            )
        )
        item = _get_put_item(table)
        # Format looks like YYYY.MM.DD_HH.MM_filename
        assert item["DateFileName"].startswith("2026.01.15_14.30_")
        assert item["DateFileName"].endswith("test_email.eml")

    def test_emails_lowercased(self):
        db, table = _make_db()
        db.add_transaction(
            _make_full_transaction(
                from_email="Alerts@RBC.COM",
                to_email="User@Example.COM",
            )
        )
        item = _get_put_item(table)
        assert item["FromEmail"] == "alerts@rbc.com"
        assert item["ToEmail"] == "user@example.com"

    def test_category_lowercased(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(category="Restaurant/Dining"))
        item = _get_put_item(table)
        assert item["Category"] == "restaurant/dining"

    def test_missing_category_defaults_to_miscellaneous(self):
        db, table = _make_db()
        data = _make_full_transaction()
        data["category"] = None
        db.add_transaction(data)
        item = _get_put_item(table)
        assert item["Category"] == "miscellaneous"

    def test_transaction_hash_is_sha256(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction())
        item = _get_put_item(table)
        assert len(item["TransactionHash"]) == 64
        # Should be valid hex
        int(item["TransactionHash"], 16)

    def test_category_audit_persisted_when_provided(self):
        db, table = _make_db()
        audit = {
            "reviewed_at": "2026-04-15T10:00:00+00:00",
            "source": "override_normalized",
            "matched_rule": "COFFEE SPOT",
            "confidence": 1.0,
        }
        db.add_transaction(_make_full_transaction(), category_audit=audit)
        item = _get_put_item(table)
        assert item["CategoryAudit"] == audit

    def test_category_audit_absent_when_not_provided(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction())
        item = _get_put_item(table)
        assert "CategoryAudit" not in item

    def test_category_audit_confidence_is_decimal(self):
        """Regression: DynamoDB rejects Python floats. Confidence must serialize as Decimal."""
        db, table = _make_db()
        audit = {"source": "override", "matched_rule": "X", "confidence": 1.0, "reviewed_at": "now"}
        db.add_transaction(_make_full_transaction(), category_audit=audit)
        item = _get_put_item(table)
        assert isinstance(item["CategoryAudit"]["confidence"], Decimal)


class TestDecimalConversion:
    """Verify amount is properly converted to Decimal for DynamoDB."""

    def test_amount_is_decimal_type(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(amount=45.67))
        item = _get_put_item(table)
        assert isinstance(item["Amount"], Decimal)

    def test_amount_precision_preserved(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(amount=99.99))
        item = _get_put_item(table)
        assert item["Amount"] == Decimal("99.99")

    def test_small_amount(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(amount=0.01))
        item = _get_put_item(table)
        assert item["Amount"] == Decimal("0.01")

    def test_large_amount(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(amount=999999.99))
        item = _get_put_item(table)
        assert item["Amount"] == Decimal("999999.99")

    def test_whole_number_amount(self):
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(amount=100.0))
        item = _get_put_item(table)
        assert item["Amount"] == Decimal("100.0")

    def test_floating_point_edge_case(self):
        """Float precision: Decimal(str()) handles 0.1+0.2."""
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(amount=0.1 + 0.2))
        item = _get_put_item(table)
        # str(0.30000000000000004) = "0.30000000000000004"
        # This is the actual behavior — Decimal(str(float)) preserves float repr
        assert isinstance(item["Amount"], Decimal)

    def test_missing_amount_is_rejected(self):
        """A parsed transaction with no `amount` is treated as invalid and not written.

        Previously the row was persisted with Amount=None, which caused non-transaction
        emails (e.g. Google security alerts that fell through parse_email unchanged)
        to appear on the dashboard as zero-value transactions.
        """
        db, table = _make_db()
        data = _make_full_transaction()
        del data["amount"]
        result = db.add_transaction(data)
        assert result is None
        table.put_item.assert_not_called()

    def test_amount_from_string_via_parser(self):
        """Simulate the parser path: regex str -> float() -> Decimal(str())."""
        # Parser does: float("1,234.56".replace(",", "")) = 1234.56
        parsed_amount = float("1,234.56".replace(",", ""))
        db, table = _make_db()
        db.add_transaction(_make_full_transaction(amount=parsed_amount))
        item = _get_put_item(table)
        assert item["Amount"] == Decimal("1234.56")


class TestRequiredFieldValidation:
    """Verify add_transaction rejects missing required fields."""

    def test_missing_forwarded_to_returns_none(self):
        db, _table = _make_db()
        data = _make_full_transaction()
        data["forwarded_to"] = None
        result = db.add_transaction(data)
        assert result is None

    def test_missing_file_name_returns_none(self):
        db, _table = _make_db()
        data = _make_full_transaction()
        data["file_name"] = None
        result = db.add_transaction(data)
        assert result is None

    def test_missing_date_returns_none(self):
        db, _table = _make_db()
        data = _make_full_transaction()
        data["date"] = None
        result = db.add_transaction(data)
        assert result is None


class TestAddTransactionErrorHandling:
    """Verify add_transaction() propagates ClientError from put_item."""

    def test_client_error_on_put_item_propagates(self):
        db, table = _make_db()
        # error_response: Any sidesteps botocore's private _ClientErrorResponseTypeDef
        # TypedDict invariance — plain dict is correct at runtime.
        error_response: Any = {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}}
        table.put_item.side_effect = ClientError(error_response, "PutItem")

        with pytest.raises(ClientError) as exc_info:
            db.add_transaction(_make_full_transaction())
        response: Any = exc_info.value.response
        assert response["Error"]["Code"] == "ProvisionedThroughputExceededException"

    def test_duplicate_transaction_returns_false(self):
        db, table = _make_db()
        table.query.return_value = {"Count": 1, "Items": [{"ForwardedTo": "user@example.com"}]}
        result = db.add_transaction(_make_full_transaction())
        assert result is False
        table.put_item.assert_not_called()


class TestGetItem:
    """Tests for TransactionsDB.get_item()."""

    def test_returns_item_when_found(self):
        db, _table = _make_db()
        expected = {"ForwardedTo": "user@example.com", "DateFileName": "2026.01.15_14.30_test.eml", "Amount": 50}
        db.dyn_resource.Table.return_value.get_item.return_value = {"Item": expected}
        result = db.get_item("user@example.com", "2026.01.15_14.30_test.eml")
        assert result == expected

    def test_returns_none_when_not_found(self):
        db, _table = _make_db()
        db.dyn_resource.Table.return_value.get_item.return_value = {}
        result = db.get_item("user@example.com", "2026.01.15_14.30_test.eml")
        assert result is None

    def test_uses_correct_key(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.get_item.return_value = {}
        db.get_item("a@b.com", "2026.02.01_10.00_email.eml")
        table.get_item.assert_called_once_with(
            Key={"ForwardedTo": "a@b.com", "DateFileName": "2026.02.01_10.00_email.eml"}
        )


class TestAddTransactionReturnValue:
    """Verify add_transaction returns the DateFileName string."""

    def test_returns_date_file_name_string(self):
        db, _table = _make_db()
        result = db.add_transaction(_make_full_transaction())
        assert isinstance(result, str)
        assert result.startswith("2026.01.15_14.30_")

    def test_return_value_is_truthy(self):
        db, _table = _make_db()
        result = db.add_transaction(_make_full_transaction())
        assert result  # truthy, backward-compatible with `if is_new:`


class TestUpdateContext:
    """Tests for TransactionsDB.update_context()."""

    def test_stores_context_map(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.return_value = {}

        context = {"category_month_total": 340.5, "merchant_month_count": 3}
        db.update_context("user@example.com", "2026.02.15_10.30_test.eml", context)

        table.update_item.assert_called_once()
        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["UpdateExpression"] == "SET TransactionContext = :ctx"
        ctx_val = call_kwargs["ExpressionAttributeValues"][":ctx"]
        assert ctx_val["merchant_month_count"] == Decimal(3)

    def test_converts_floats_to_decimal(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.return_value = {}

        context = {"category_month_total": 100.5, "category_budget_pct": 85.1}
        db.update_context("user@example.com", "2026.02.15_10.30_test.eml", context)

        ctx_val = table.update_item.call_args.kwargs["ExpressionAttributeValues"][":ctx"]
        assert isinstance(ctx_val["category_month_total"], Decimal)
        assert isinstance(ctx_val["category_budget_pct"], Decimal)

    def test_fails_open_on_error(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "test"}}, "UpdateItem"
        )

        # Should not raise
        db.update_context("user@example.com", "2026.02.15_10.30_test.eml", {"total": 100.0})


class TestSetIgnored:
    """Tests for TransactionsDB.set_ignored()."""

    def test_sets_ignored_true(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.return_value = {"Attributes": {}}
        db.set_ignored("user@example.com", "2026.01.15_14.30_test.eml", True)

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["UpdateExpression"] == "SET Ignored = :val"
        assert call_kwargs["ExpressionAttributeValues"][":val"] is True

    def test_sets_ignored_false(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.return_value = {"Attributes": {"Ignored": True}}
        db.set_ignored("user@example.com", "2026.01.15_14.30_test.eml", False)

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["ExpressionAttributeValues"][":val"] is False

    def test_returns_previous_ignored_value(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.return_value = {"Attributes": {"Ignored": True}}
        old = db.set_ignored("user@example.com", "2026.01.15_14.30_test.eml", False)
        assert old is True

    def test_returns_none_when_no_previous_value(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.return_value = {"Attributes": {}}
        old = db.set_ignored("user@example.com", "2026.01.15_14.30_test.eml", True)
        assert old is None

    def test_uses_correct_key(self):
        db, table = _make_db()
        table = db.dyn_resource.Table.return_value
        table.update_item.return_value = {"Attributes": {}}
        db.set_ignored("a@b.com", "2026.02.01_10.00_email.eml", True)

        call_kwargs = table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {
            "ForwardedTo": "a@b.com",
            "DateFileName": "2026.02.01_10.00_email.eml",
        }
        assert call_kwargs["ReturnValues"] == "UPDATED_OLD"
