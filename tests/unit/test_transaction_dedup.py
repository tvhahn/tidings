"""Tests for transaction deduplication (idempotency key) logic."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.finance.transaction_db import TransactionsDB, generate_transaction_hash

# --- Hash generation tests ---


def test_generate_hash_deterministic():
    """Same input should always produce the same hash."""
    data = {
        "forwarded_to": "user@example.com",
        "institution": "RBC",
        "amount": 45.67,
        "company": "Starbucks",
        "date": "01/15/2026 14:30 PST",
        "transaction_type": "purchase",
    }
    assert generate_transaction_hash(data) == generate_transaction_hash(data)


def test_generate_hash_different_inputs():
    """Different inputs should produce different hashes."""
    data1 = {
        "forwarded_to": "user@example.com",
        "institution": "RBC",
        "amount": 45.67,
        "company": "Starbucks",
        "date": "01/15/2026 14:30 PST",
        "transaction_type": "purchase",
    }
    data2 = {
        "forwarded_to": "user@example.com",
        "institution": "RBC",
        "amount": 99.99,
        "company": "Amazon",
        "date": "01/16/2026 10:00 PST",
        "transaction_type": "purchase",
    }
    assert generate_transaction_hash(data1) != generate_transaction_hash(data2)


def test_generate_hash_normalizes_amount():
    """Amounts like 45.6 and 45.60 should produce the same hash."""
    data1 = {
        "forwarded_to": "user@example.com",
        "institution": "RBC",
        "amount": 45.6,
        "company": "Starbucks",
        "date": "01/15/2026 14:30 PST",
        "transaction_type": "purchase",
    }
    data2 = {
        "forwarded_to": "user@example.com",
        "institution": "RBC",
        "amount": 45.60,
        "company": "Starbucks",
        "date": "01/15/2026 14:30 PST",
        "transaction_type": "purchase",
    }
    assert generate_transaction_hash(data1) == generate_transaction_hash(data2)


def test_generate_hash_handles_none_fields():
    """None values should be handled consistently without errors."""
    data = {
        "forwarded_to": None,
        "institution": None,
        "amount": None,
        "company": None,
        "date": None,
        "transaction_type": None,
    }
    h = generate_transaction_hash(data)
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256 hex digest length
    # Should be deterministic even with all Nones
    assert h == generate_transaction_hash(data)


# --- add_transaction integration tests (mocked DynamoDB) ---


def _make_transaction_data() -> dict[str, Any]:
    """Helper to build a valid transaction data dict."""
    return {
        "forwarded_to": "user@example.com",
        "file_name": "emails/test.eml",
        "date": "01/15/2026 14:30 PST",
        "institution": "RBC",
        "amount": 45.67,
        "company": "Starbucks",
        "transaction_type": "purchase",
        "category": "Restaurant",
    }


def _mock_table():
    """Create a mock DynamoDB table."""
    table = MagicMock(name="dynamodb_table")
    table.query.return_value = {"Count": 0, "Items": []}
    table.put_item.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
    return table


def test_add_transaction_returns_truthy_for_new():
    """New transaction (no duplicate) should write and return a truthy DateFileName string."""
    dyn_resource = MagicMock()
    table = _mock_table()
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    result = db.add_transaction(_make_transaction_data())

    assert isinstance(result, str)
    assert result
    table.put_item.assert_called_once()


@pytest.mark.parametrize("field", ["amount", "institution", "transaction_type"])
def test_add_transaction_rejects_unparsed_email_shaped_data(field):
    """Rows lacking parser-produced fields must not be written to DynamoDB."""
    dyn_resource = MagicMock()
    table = _mock_table()
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    data = _make_transaction_data()
    del data[field]

    assert db.add_transaction(data) is None
    table.put_item.assert_not_called()


def test_add_transaction_returns_false_for_duplicate():
    """Duplicate transaction should skip write and return False."""
    dyn_resource = MagicMock()
    table = _mock_table()
    table.query.return_value = {
        "Count": 1,
        "Items": [{"ForwardedTo": "user@example.com"}],
    }
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    result = db.add_transaction(_make_transaction_data())

    assert result is False
    table.put_item.assert_not_called()


def test_transaction_hash_stored_in_item():
    """TransactionHash should appear in the put_item call."""
    dyn_resource = MagicMock()
    table = _mock_table()
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    data = _make_transaction_data()
    db.add_transaction(data)

    put_item_kwargs = table.put_item.call_args
    item = put_item_kwargs.kwargs.get("Item") or put_item_kwargs[1]["Item"]
    assert "TransactionHash" in item
    assert len(item["TransactionHash"]) == 64


def test_duplicate_check_fail_open():
    """If _transaction_exists errors, the write should still proceed."""
    dyn_resource = MagicMock()
    table = _mock_table()
    # Make query raise a ClientError
    table.query.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "test"}},
        "Query",
    )
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    result = db.add_transaction(_make_transaction_data())

    assert isinstance(result, str)
    assert result
    table.put_item.assert_called_once()


# --- Pagination regression tests ---
# FilterExpression is applied after DynamoDB's 1MB page limit, so a match can
# sit on page 2+ of the partition. A single-page query stops deduplicating once
# the partition outgrows one page (items carry the full raw email Body).


def test_duplicate_on_second_page_is_detected():
    """A duplicate past the first 1MB page must still skip the write."""
    dyn_resource = MagicMock()
    table = _mock_table()
    table.query.side_effect = [
        {"Count": 0, "Items": [], "LastEvaluatedKey": {"ForwardedTo": "u", "DateFileName": "x"}},
        {"Count": 1, "Items": [{"ForwardedTo": "user@example.com"}]},
    ]
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    result = db.add_transaction(_make_transaction_data())

    assert result is False
    table.put_item.assert_not_called()
    assert table.query.call_count == 2
    # Page 2 must resume from page 1's LastEvaluatedKey.
    assert table.query.call_args.kwargs["ExclusiveStartKey"] == {"ForwardedTo": "u", "DateFileName": "x"}


def test_no_duplicate_walks_all_pages_then_writes():
    """An absent hash must be confirmed absent on every page before writing."""
    dyn_resource = MagicMock()
    table = _mock_table()
    table.query.side_effect = [
        {"Count": 0, "Items": [], "LastEvaluatedKey": {"ForwardedTo": "u", "DateFileName": "x"}},
        {"Count": 0, "Items": []},
    ]
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    result = db.add_transaction(_make_transaction_data())

    assert isinstance(result, str)
    assert result
    assert table.query.call_count == 2
    table.put_item.assert_called_once()


def test_find_date_file_name_by_hash_paginates():
    """Hash lookup (bulk-import dedup path) must also walk pages."""
    dyn_resource = MagicMock()
    table = MagicMock(name="dynamodb_table")
    table.query.side_effect = [
        {"Items": [], "LastEvaluatedKey": {"ForwardedTo": "u", "DateFileName": "x"}},
        {"Items": [{"DateFileName": "2026.01.15_14.30_test.eml"}]},
    ]
    dyn_resource.Table.return_value = table

    db = TransactionsDB(dyn_resource)
    result = db.find_date_file_name_by_hash("user@example.com", "a" * 64)

    assert result == "2026.01.15_14.30_test.eml"
    assert table.query.call_count == 2
