"""Budget configuration CRUD backed by DynamoDB."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3

from src.finance.aws_region import get_aws_region
from src.finance.budget_service_base import (
    DEFAULT_GROUPS,
    BudgetServiceBase,
)

# Re-exported under the historical private name for callers/tests that import it here.
from src.finance.decimal_utils import floats_to_decimals as _floats_to_decimals
from src.finance.demo_clock import app_today
from src.finance.dynamodb_utils import dynamo_put_versioned

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

logger = logging.getLogger(__name__)

# DEFAULT_GROUPS is re-exported here so API routers import it from the concrete
# service alongside BudgetService rather than reaching into the base module.
__all__ = ["DEFAULT_GROUPS", "BudgetService"]

_CONFIG_DIR = Path(__file__).resolve().parent / "config"


class BudgetService(BudgetServiceBase):
    """CRUD operations for budget configuration in DynamoDB."""

    TABLE_NAME = "BudgetConfig"

    def __init__(self, dyn_resource: "DynamoDBServiceResource | None" = None, user_id: str = "default"):
        super().__init__()
        if dyn_resource is None:
            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    def create_table(self) -> None:
        """Create BudgetConfig table (PK + SK, PAY_PER_REQUEST)."""
        self.dyn_resource.create_table(
            TableName=self.TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        self.table.wait_until_exists()
        logger.info("Created table %s", self.TABLE_NAME)

    def get_targets(self, year: int) -> dict[str, Any] | None:
        """Get budget targets for a year. Returns None if not configured."""
        response = self.table.get_item(Key={"PK": self.USER_PK, "SK": f"BUDGET#targets#{year}"})
        item = response.get("Item")
        if not item:
            return None
        return item

    def get_groups(self, year: int) -> dict[str, Any] | None:
        """Get category groups for a year. Returns None if not configured."""
        response = self.table.get_item(Key={"PK": self.USER_PK, "SK": f"BUDGET#groups#{year}"})
        item = response.get("Item")
        if not item:
            return None
        return item

    def _store_targets(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        """Persist targets to DynamoDB with optimistic locking."""
        new_version = (expected_version or 0) + 1
        item = {
            "PK": self.USER_PK,
            "SK": f"BUDGET#targets#{year}",
            "Data": _floats_to_decimals(data),
            "Version": new_version,
            "UpdatedAt": app_today().isoformat(),
        }
        dynamo_put_versioned(self.table, item, expected_version)
        return new_version

    def _store_groups(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        """Persist category groups to DynamoDB with optimistic locking."""
        new_version = (expected_version or 0) + 1
        item = {
            "PK": self.USER_PK,
            "SK": f"BUDGET#groups#{year}",
            "Data": _floats_to_decimals(data),
            "Version": new_version,
            "UpdatedAt": app_today().isoformat(),
        }
        dynamo_put_versioned(self.table, item, expected_version)
        return new_version
