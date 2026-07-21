"""Tests for the DynamoDB Transactions table DDL helpers.

These functions ship in the production deploy path (the table is auto-created
on first use, see CLAUDE.md). Without these tests a silent schema drift —
wrong key names, wrong billing mode, wrong attribute types — would only
surface in AWS, where it's very expensive to debug.
"""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.finance.transaction_db_admin import (
    create_transaction_table,
    delete_all_transactions,
    delete_transaction_table,
)

# ---------------------------------------------------------------------------
# create_transaction_table
# ---------------------------------------------------------------------------


class TestCreateTransactionTable:
    def test_creates_table_with_expected_schema(self) -> None:
        dyn = MagicMock(name="dynamodb_resource")
        table = MagicMock()
        dyn.create_table.return_value = table

        result = create_transaction_table(dyn)

        assert result is table
        dyn.create_table.assert_called_once()
        kwargs = dyn.create_table.call_args.kwargs

        # Schema contract — if any of these change, every reader of the table
        # has to be updated in lockstep.
        assert kwargs["TableName"] == "Transactions"
        assert kwargs["BillingMode"] == "PAY_PER_REQUEST"
        assert kwargs["KeySchema"] == [
            {"AttributeName": "ForwardedTo", "KeyType": "HASH"},
            {"AttributeName": "DateFileName", "KeyType": "RANGE"},
        ]
        assert kwargs["AttributeDefinitions"] == [
            {"AttributeName": "ForwardedTo", "AttributeType": "S"},
            {"AttributeName": "DateFileName", "AttributeType": "S"},
        ]

    def test_waits_for_table_to_exist(self) -> None:
        dyn = MagicMock()
        table = MagicMock(name="dynamodb_table")
        dyn.create_table.return_value = table

        create_transaction_table(dyn)

        table.wait_until_exists.assert_called_once_with()

    def test_propagates_client_error(self) -> None:
        dyn = MagicMock()
        dyn.create_table.side_effect = ClientError(
            {"Error": {"Code": "ResourceInUseException", "Message": "exists"}},
            "CreateTable",
        )

        with pytest.raises(ClientError):
            create_transaction_table(dyn)


# ---------------------------------------------------------------------------
# delete_transaction_table
# ---------------------------------------------------------------------------


class TestDeleteTransactionTable:
    def test_deletes_named_table(self) -> None:
        dyn = MagicMock(name="dynamodb_resource")
        table = MagicMock(name="dynamodb_table")
        dyn.Table.return_value = table

        delete_transaction_table(dyn)

        dyn.Table.assert_called_once_with("Transactions")
        table.delete.assert_called_once_with()
        table.wait_until_not_exists.assert_called_once_with()

    def test_propagates_client_error(self) -> None:
        dyn = MagicMock()
        table = MagicMock()
        dyn.Table.return_value = table
        table.delete.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}},
            "DeleteTable",
        )

        with pytest.raises(ClientError):
            delete_transaction_table(dyn)


# ---------------------------------------------------------------------------
# delete_all_transactions
# ---------------------------------------------------------------------------


class TestDeleteAllTransactions:
    def test_deletes_each_item_via_batch_writer(self) -> None:
        dyn = MagicMock(name="dynamodb_resource")
        table = MagicMock()
        dyn.Table.return_value = table
        table.scan.return_value = {
            "Items": [
                {"ForwardedTo": "a@example.com", "DateFileName": "2026.01.01_x.eml"},
                {"ForwardedTo": "b@example.com", "DateFileName": "2026.01.02_y.eml"},
            ]
        }
        batch = MagicMock(name="batch_writer")
        table.batch_writer.return_value.__enter__.return_value = batch

        delete_all_transactions(dyn)

        dyn.Table.assert_called_once_with("Transactions")
        assert batch.delete_item.call_count == 2
        batch.delete_item.assert_any_call(Key={"ForwardedTo": "a@example.com", "DateFileName": "2026.01.01_x.eml"})
        batch.delete_item.assert_any_call(Key={"ForwardedTo": "b@example.com", "DateFileName": "2026.01.02_y.eml"})

    def test_no_items_means_no_deletes(self) -> None:
        dyn = MagicMock()
        table = MagicMock()
        dyn.Table.return_value = table
        table.scan.return_value = {"Items": []}
        batch = MagicMock(name="batch_writer")
        table.batch_writer.return_value.__enter__.return_value = batch

        delete_all_transactions(dyn)

        batch.delete_item.assert_not_called()

    def test_propagates_client_error(self) -> None:
        dyn = MagicMock()
        table = MagicMock()
        dyn.Table.return_value = table
        table.scan.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}},
            "Scan",
        )

        with pytest.raises(ClientError):
            delete_all_transactions(dyn)
