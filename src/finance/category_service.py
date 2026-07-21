"""Category list CRUD backed by DynamoDB with JSON file backup."""

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

PROTECTED_CATEGORY = "Miscellaneous"


class CategoryServiceBase:
    """Shared business logic for category list management (storage-agnostic)."""

    CATEGORIES_SK = "CONFIG#categories"

    def get_categories(self) -> dict[str, Any] | None:
        """Return the full categories item or None if not yet seeded.

        Returns dict with keys: Data (list[str] sorted category list),
        Version (int), UpdatedAt (str).
        """
        raise NotImplementedError

    def _put_all(self, categories: list[str], expected_version: int | None) -> int:
        raise NotImplementedError

    def put_all_categories(self, categories: list[str], expected_version: int | None) -> int:
        """Replace the full category list at once with optimistic locking.

        Used by seed script and bulk operations.
        Returns new version. Raises ClientError on conflict.
        """
        return self._put_all(categories, expected_version)

    def get_categories_list(self) -> list[str]:
        """Return just the category list, falling back to JSON."""
        item = self.get_categories()
        if item is not None:
            return list(item.get("Data", []))
        return self._load_from_json()

    def add_category(self, name: str) -> int:
        """Add a new category. Returns new version.

        Raises ValueError if the name already exists (case-insensitive).
        """
        item = self.get_categories()
        if item is None:
            categories = self._load_from_json()
            expected_version = None
        else:
            categories = list(item.get("Data", []))
            expected_version = int(item.get("Version", 0))

        # Case-insensitive uniqueness check
        lower_names = {c.lower() for c in categories}
        if name.lower() in lower_names:
            raise ValueError(f"Category '{name}' already exists")

        categories.append(name)
        categories.sort(key=str.lower)
        return self._put_all(categories, expected_version)

    def rename_category(self, old_name: str, new_name: str) -> int:
        """Rename a category in-place. Returns new version.

        Raises ValueError if old_name is protected, not found, or new_name already exists.
        """
        if old_name.lower() == PROTECTED_CATEGORY.lower():
            raise ValueError(f"'{PROTECTED_CATEGORY}' cannot be renamed")

        item = self.get_categories()
        if item is None:
            categories = self._load_from_json()
            expected_version = None
        else:
            categories = list(item.get("Data", []))
            expected_version = int(item.get("Version", 0))

        # Find the old name (case-insensitive)
        found_idx = None
        for i, c in enumerate(categories):
            if c.lower() == old_name.lower():
                found_idx = i
                break
        if found_idx is None:
            raise ValueError(f"Category '{old_name}' not found")

        # Check new name doesn't already exist (case-insensitive, excluding old)
        lower_names = {c.lower() for j, c in enumerate(categories) if j != found_idx}
        if new_name.lower() in lower_names:
            raise ValueError(f"Category '{new_name}' already exists")

        categories[found_idx] = new_name
        categories.sort(key=str.lower)
        return self._put_all(categories, expected_version)

    def delete_category(self, name: str) -> int:
        """Remove a category. Returns new version.

        Raises ValueError if name is protected or not found.
        """
        if name.lower() == PROTECTED_CATEGORY.lower():
            raise ValueError(f"'{PROTECTED_CATEGORY}' cannot be deleted")

        item = self.get_categories()
        if item is None:
            categories = self._load_from_json()
            expected_version = None
        else:
            categories = list(item.get("Data", []))
            expected_version = int(item.get("Version", 0))

        # Case-insensitive find and remove
        found_idx = None
        for i, c in enumerate(categories):
            if c.lower() == name.lower():
                found_idx = i
                break
        if found_idx is None:
            raise ValueError(f"Category '{name}' not found")

        del categories[found_idx]
        return self._put_all(categories, expected_version)

    def _load_from_json(self) -> list[str]:
        """Load categories from JSON — personal backup first, tracked seed as fallback."""
        path = _PERSONAL_DIR / "categories.json"
        if not path.exists():
            path = _CONFIG_DIR / "categories.json"
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            logger.warning("Failed to load categories from JSON", exc_info=True)
            return []

    def _write_backup(self, categories: list[str]) -> None:
        """Write categories to data/config/categories.json (gitignored)."""
        try:
            _PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
            with open(_PERSONAL_DIR / "categories.json", "w") as f:
                json.dump(categories, f, indent=2)
                f.write("\n")
        except Exception:
            logger.exception("Failed to write categories backup")


class CategoryService(CategoryServiceBase):
    """CRUD operations for the master category list in DynamoDB."""

    TABLE_NAME = "CategoryConfig"

    def __init__(self, dyn_resource: "DynamoDBServiceResource | None" = None, user_id: str = "default"):
        if dyn_resource is None:
            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    def get_categories(self) -> dict[str, Any] | None:
        """Return the full categories item or None if not yet seeded.

        Returns dict with keys: Data (sorted category list), Version, UpdatedAt.
        Returns None if the table doesn't exist or the item is missing.
        """
        try:
            response = self.table.get_item(Key={"PK": self.USER_PK, "SK": self.CATEGORIES_SK})
        except Exception:
            logger.debug("Failed to read categories from DynamoDB", exc_info=True)
            return None
        item = response.get("Item")
        if not item:
            return None
        return item

    def _put_all(self, categories: list[str], expected_version: int | None) -> int:
        """Write the full category list with optimistic locking + JSON backup."""
        new_version = (expected_version or 0) + 1

        item = {
            "PK": self.USER_PK,
            "SK": self.CATEGORIES_SK,
            "Data": categories,
            "Version": new_version,
            "UpdatedAt": app_today().isoformat(),
        }
        dynamo_put_versioned(self.table, item, expected_version)
        self._write_backup(categories)
        return new_version
