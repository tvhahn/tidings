"""Shared DynamoDB utilities."""

from typing import Any

from botocore.exceptions import ClientError

from src.finance.exceptions import VersionConflictError


def dynamo_put_versioned(table: Any, item: dict[str, Any], expected_version: int | None) -> None:
    """put_item with optimistic version locking. Raises VersionConflictError on conflict."""
    if expected_version is None:
        put_kwargs = {"Item": item, "ConditionExpression": "attribute_not_exists(Version)"}
    else:
        put_kwargs = {
            "Item": item,
            "ConditionExpression": "Version = :expected",
            "ExpressionAttributeValues": {":expected": expected_version},
        }
    try:
        table.put_item(**put_kwargs)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise VersionConflictError(f"Expected version {expected_version}") from e
        raise
