"""Merchant alias CRUD backed by DynamoDB with JSON file backup."""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3

from src.finance.aws_region import get_aws_region
from src.finance.demo_clock import app_today
from src.finance.dynamodb_utils import dynamo_put_versioned

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_PERSONAL_DIR = Path(__file__).resolve().parents[2] / "data" / "config"


class MerchantAliasServiceBase:
    """Shared business logic for merchant aliases (storage-agnostic)."""

    ALIASES_SK = "CONFIG#merchant_aliases"

    def get_aliases(self) -> dict[str, Any] | None:
        """Return the full aliases item or None if not yet created.

        Returns dict with keys: Data (dict[str, str] aliases map),
        Version (int), UpdatedAt (str).
        """
        raise NotImplementedError

    def _put_all(self, data: dict[str, Any], expected_version: int | None) -> int:
        raise NotImplementedError

    def put_all_aliases(self, data: dict[str, Any], expected_version: int | None) -> int:
        """Replace the full aliases map at once with optimistic locking.

        Used by seed script and bulk operations.
        Returns new version. Raises ClientError on conflict.
        """
        return self._put_all(data, expected_version)

    def get_aliases_map(self) -> dict[str, str]:
        """Return just the aliases data map (lowercase key -> canonical name).

        Returns empty dict if no aliases configured.
        """
        item = self.get_aliases()
        if not item:
            return {}
        return dict(item.get("Data", {}))

    def put_alias(self, raw_name: str, canonical_name: str) -> int:
        """Add or update a single alias. Returns new version."""
        item = self.get_aliases()
        if item is None:
            data = {}
            expected_version = None
        else:
            data = dict(item.get("Data", {}))
            expected_version = int(item.get("Version", 0))

        data[raw_name.lower()] = canonical_name
        return self._put_all(data, expected_version)

    def delete_alias(self, raw_name: str) -> int:
        """Remove a single alias. Returns new version. Raises KeyError if not found."""
        item = self.get_aliases()
        if item is None:
            raise KeyError(raw_name)

        data = dict(item.get("Data", {}))
        key = raw_name.lower()
        if key not in data:
            raise KeyError(raw_name)

        del data[key]
        expected_version = int(item.get("Version", 0))
        return self._put_all(data, expected_version)

    def _write_backup(self, data: dict[str, Any]) -> None:
        """Write aliases to data/config/merchant_aliases.json (gitignored)."""
        try:
            _PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
            with open(_PERSONAL_DIR / "merchant_aliases.json", "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
        except Exception:
            logger.exception("Failed to write merchant aliases backup")


class MerchantAliasService(MerchantAliasServiceBase):
    """CRUD operations for merchant aliases in DynamoDB.

    Uses the same CategoryConfig table as OverrideService and CategoryService,
    with a distinct sort key (CONFIG#merchant_aliases).
    """

    TABLE_NAME = "CategoryConfig"

    def __init__(self, dyn_resource: "DynamoDBServiceResource | None" = None, user_id: str = "default"):
        if dyn_resource is None:
            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    def get_aliases(self) -> dict[str, Any] | None:
        """Return the full aliases item or None if not yet created.

        Returns dict with keys: Data (aliases map), Version, UpdatedAt.
        """
        try:
            response = self.table.get_item(Key={"PK": self.USER_PK, "SK": self.ALIASES_SK})
        except Exception:
            logger.warning("Failed to read merchant aliases from DynamoDB", exc_info=True)
            return None
        item = response.get("Item")
        if not item:
            return None
        return item

    def _put_all(self, data: dict[str, Any], expected_version: int | None) -> int:
        """Write the full aliases map with optimistic locking + JSON backup."""
        new_version = (expected_version or 0) + 1

        item = {
            "PK": self.USER_PK,
            "SK": self.ALIASES_SK,
            "Data": data,
            "Version": new_version,
            "UpdatedAt": app_today().isoformat(),
        }
        dynamo_put_versioned(self.table, item, expected_version)
        self._write_backup(data)
        return new_version
