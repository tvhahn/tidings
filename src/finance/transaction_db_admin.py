"""DynamoDB Transactions table administrative operations (DDL)."""

import logging
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

__all__ = [
    "create_transaction_table",
    "delete_all_transactions",
    "delete_transaction_table",
]

logger = logging.getLogger(__name__)


def create_transaction_table(dyn_resource: "DynamoDBServiceResource") -> "Table":
    """Creates a DynamoDB table for storing transaction data with on-demand pricing."""
    table_name = "Transactions"
    try:
        table = dyn_resource.create_table(
            TableName=table_name,
            KeySchema=[
                {
                    "AttributeName": "ForwardedTo",
                    "KeyType": "HASH",
                },  # Partition key
                {"AttributeName": "DateFileName", "KeyType": "RANGE"},  # Sort key
            ],
            AttributeDefinitions=[
                {"AttributeName": "ForwardedTo", "AttributeType": "S"},
                {"AttributeName": "DateFileName", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        logger.info("Table %s created successfully with on-demand pricing.", table_name)
        return table
    except ClientError:
        logger.exception("Failed to create table %s.", table_name)
        raise


def delete_transaction_table(dyn_resource: "DynamoDBServiceResource") -> None:
    """Deletes the DynamoDB table for transaction data."""
    table_name = "Transactions"
    try:
        table = dyn_resource.Table(table_name)
        table.delete()
        table.wait_until_not_exists()
        logger.info("Table %s deleted successfully.", table_name)
    except ClientError:
        logger.exception("Failed to delete table %s.", table_name)
        raise


def delete_all_transactions(dyn_resource: "DynamoDBServiceResource") -> None:
    """Deletes all entries in the DynamoDB Transactions table."""
    table_name = "Transactions"
    try:
        table = dyn_resource.Table(table_name)

        # Scan the table to get all items
        response = table.scan()
        items = response.get("Items", [])

        # Delete each item
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(
                    Key={
                        "ForwardedTo": item["ForwardedTo"],
                        "DateFileName": item["DateFileName"],
                    }
                )
        logger.info("All items deleted from %s.", table_name)
    except ClientError:
        logger.exception("Failed to delete items from %s.", table_name)
        raise


if __name__ == "__main__":
    import boto3

    INIT_TABLE = False
    DELETE_TABLE = False
    DELETE_ALL = False

    dynamo_resource = boto3.resource("dynamodb")

    if INIT_TABLE:
        create_transaction_table(dynamo_resource)

    if DELETE_TABLE:
        delete_transaction_table(dynamo_resource)

    if DELETE_ALL:
        delete_all_transactions(dynamo_resource)
