"""Per-category icon overrides backed by DynamoDB.

Stores only user-set overrides; defaults live in the frontend icon catalog.
Shape: {category_lowercase: lucide_icon_name}.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3

from src.finance.aws_region import get_aws_region
from src.finance.category_icons import ALLOWED_ICON_NAMES
from src.finance.demo_clock import app_today
from src.finance.dynamodb_utils import dynamo_put_versioned

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

logger = logging.getLogger(__name__)

_PERSONAL_DIR = Path(__file__).resolve().parents[2] / "data" / "config"


class CategoryIconServiceBase:
    """Shared business logic for category icon overrides (storage-agnostic)."""

    ICONS_SK = "CONFIG#category_icons"

    def get_icons(self) -> dict[str, Any] | None:
        """Return the full icons item or None if not yet created.

        Returns dict with keys: Data (dict[str, str] lowercase-name -> icon name),
        Version (int), UpdatedAt (str).
        """
        raise NotImplementedError

    def _put_all(self, data: dict[str, str], expected_version: int | None) -> int:
        raise NotImplementedError

    def get_icons_map(self) -> dict[str, str]:
        """Return just the overrides data map (lowercase name -> icon name).

        Returns empty dict if no overrides configured.
        """
        item = self.get_icons()
        if not item:
            return {}
        return dict(item.get("Data", {}))

    def set_icon(self, category: str, icon_name: str) -> int:
        """Set or update the icon for a category. Returns new version.

        Raises ValueError if icon_name is not in the allowlist.
        """
        if icon_name not in ALLOWED_ICON_NAMES:
            raise ValueError(f"Icon '{icon_name}' is not in the allowed icon catalog")

        item = self.get_icons()
        if item is None:
            data: dict[str, str] = {}
            expected_version = None
        else:
            data = dict(item.get("Data", {}))
            expected_version = int(item.get("Version", 0))

        data[category.lower()] = icon_name
        return self._put_all(data, expected_version)

    def clear_icon(self, category: str) -> int:
        """Remove the icon override for a category (reset to default).

        Returns new version. Silently no-ops if there was no override.
        """
        item = self.get_icons()
        if item is None:
            return 0

        data = dict(item.get("Data", {}))
        key = category.lower()
        if key not in data:
            return int(item.get("Version", 0))

        del data[key]
        expected_version = int(item.get("Version", 0))
        return self._put_all(data, expected_version)

    def rename_category(self, old_name: str, new_name: str) -> int:
        """Rekey an override from old_name to new_name. Returns new version.

        No-op (returns current version) if no override exists for old_name.
        """
        item = self.get_icons()
        if item is None:
            return 0

        data = dict(item.get("Data", {}))
        old_key = old_name.lower()
        if old_key not in data:
            return int(item.get("Version", 0))

        icon = data.pop(old_key)
        data[new_name.lower()] = icon
        expected_version = int(item.get("Version", 0))
        return self._put_all(data, expected_version)

    def delete_category(self, name: str) -> int:
        """Alias for clear_icon — called from the category delete cascade."""
        return self.clear_icon(name)

    def _write_backup(self, data: dict[str, str]) -> None:
        """Write icon overrides to data/config/category_icons.json (gitignored)."""
        try:
            _PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
            with open(_PERSONAL_DIR / "category_icons.json", "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
        except Exception:
            logger.exception("Failed to write category icons backup")


class CategoryIconService(CategoryIconServiceBase):
    """DynamoDB CRUD for category icon overrides.

    Shares the CategoryConfig table with the other category config services,
    distinguished by the CONFIG#category_icons sort key.
    """

    TABLE_NAME = "CategoryConfig"

    def __init__(self, dyn_resource: "DynamoDBServiceResource | None" = None, user_id: str = "default"):
        if dyn_resource is None:
            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    def get_icons(self) -> dict[str, Any] | None:
        try:
            response = self.table.get_item(Key={"PK": self.USER_PK, "SK": self.ICONS_SK})
        except Exception:
            logger.debug("Failed to read category icons from DynamoDB", exc_info=True)
            return None
        item = response.get("Item")
        if not item:
            return None
        return item

    def _put_all(self, data: dict[str, str], expected_version: int | None) -> int:
        new_version = (expected_version or 0) + 1

        item = {
            "PK": self.USER_PK,
            "SK": self.ICONS_SK,
            "Data": data,
            "Version": new_version,
            "UpdatedAt": app_today().isoformat(),
        }
        dynamo_put_versioned(self.table, item, expected_version)
        self._write_backup(data)
        return new_version
