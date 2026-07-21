"""Category override CRUD backed by DynamoDB with JSON file backup."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3

from src.finance.aws_region import get_aws_region
from src.finance.category_resolver import resolve_override
from src.finance.demo_clock import app_today
from src.finance.dynamodb_utils import dynamo_put_versioned

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_PERSONAL_DIR = Path(__file__).resolve().parents[2] / "data" / "config"


class OverrideServiceBase:
    """Shared business logic for category overrides (storage-agnostic)."""

    OVERRIDES_SK = "CONFIG#category_overrides"

    def get_overrides(self) -> dict[str, Any] | None:
        """Return the full overrides item or None if not yet seeded.

        Returns dict with keys: Data (dict[str, str] overrides map),
        Version (int), UpdatedAt (str), Dismissed (dict, optional).
        """
        raise NotImplementedError

    def _put_all_with_dismissed(
        self, data: dict[str, Any], dismissed: dict[str, Any], expected_version: int | None
    ) -> int:
        raise NotImplementedError

    def lookup_category(self, company: str, aliases: dict[str, str] | None = None) -> str | None:
        """Return the override category for a company via the tiered resolver, or None.

        Callers that want Tier 2 (alias-resolved) matching pass an `aliases` map,
        typically obtained from `config_loader.get_override_context()`. Without
        aliases the resolver runs Tier 0/1 only.
        """
        item = self.get_overrides()
        if item is None:
            return None
        match = resolve_override(company, item.get("Data", {}), aliases=aliases)
        return match.category if match else None

    def put_override(self, company: str, category: str) -> int:
        """Add or update a single override. Returns new version."""
        item = self.get_overrides()
        if item is None:
            data = {}
            expected_version = None
        else:
            data = dict(item.get("Data", {}))
            expected_version = int(item.get("Version", 0))

        data[company] = category
        return self._put_all(data, expected_version)

    def delete_override(self, company: str) -> int:
        """Remove a single override. Returns new version. Raises KeyError if not found."""
        item = self.get_overrides()
        if item is None:
            raise KeyError(company)

        data = dict(item.get("Data", {}))
        # Case-insensitive key lookup for deletion
        found_key = None
        for key in data:
            if key.lower() == company.lower():
                found_key = key
                break
        if found_key is None:
            raise KeyError(company)

        del data[found_key]
        expected_version = int(item.get("Version", 0))
        return self._put_all(data, expected_version)

    def put_all_overrides(self, data: dict[str, Any], expected_version: int | None) -> int:
        """Replace all overrides at once with optimistic locking.

        Used by seed script and bulk operations.
        Returns new version. Raises ClientError on conflict.
        """
        return self._put_all(data, expected_version)

    def consolidate_overrides(
        self,
        canonical_company: str,
        canonical_category: str,
        members: list[str],
    ) -> int:
        """Atomically replace the `members` overrides with a single `canonical_company` entry.

        Either every member is deleted and the canonical entry created in the
        same write, or nothing changes. Uses the existing per-item optimistic
        locking (the whole overrides map is a single item, so one write covers
        create + deletes).

        Raises:
            KeyError: when a member isn't present in the current overrides map
                (possibly because it was deleted concurrently).
            FileExistsError: when `canonical_company` already exists in the map
                and isn't itself one of the members being consolidated.
            VersionConflictError: when overrides were modified concurrently.
        """
        if not members:
            raise ValueError("members cannot be empty")

        item = self.get_overrides()
        if item is None:
            raise KeyError("no overrides configured")

        data = dict(item.get("Data", {}))
        expected_version = int(item.get("Version", 0))

        # Case-insensitive member lookup so callers can pass the display name.
        member_lowers = {m.lower() for m in members}
        to_delete = [k for k in data if k.lower() in member_lowers]
        missing = member_lowers - {k.lower() for k in to_delete}
        if missing:
            raise KeyError(", ".join(sorted(missing)))

        canonical_lower = canonical_company.lower()
        collision = [k for k in data if k.lower() == canonical_lower and k not in to_delete]
        if collision:
            raise FileExistsError(f"canonical key already exists: {collision[0]}")

        for key in to_delete:
            del data[key]
        data[canonical_company] = canonical_category

        return self._put_all(data, expected_version)

    def dismiss_suggestion(self, company: str, category: str) -> None:
        """Dismiss a suggestion by adding it to the Dismissed map on the overrides item."""
        item = self.get_overrides()
        if item is None:
            # No overrides item yet — create one with just the dismissal
            data = {}
            dismissed = {}
            expected_version = None
        else:
            data = dict(item.get("Data", {}))
            dismissed = dict(item.get("Dismissed", {}))
            expected_version = int(item.get("Version", 0))

        key = f"{company.lower()}|{category.lower()}"
        dismissed[key] = datetime.now(UTC).isoformat()

        self._put_all_with_dismissed(data, dismissed, expected_version)

    def undismiss_suggestion(self, key: str) -> None:
        """Remove a dismissal by key (company_lower|category_lower)."""
        item = self.get_overrides()
        if item is None:
            return

        dismissed = dict(item.get("Dismissed", {}))
        if key not in dismissed:
            return

        del dismissed[key]
        data = dict(item.get("Data", {}))
        expected_version = int(item.get("Version", 0))
        self._put_all_with_dismissed(data, dismissed, expected_version)

    def _put_all(self, data: dict[str, Any], expected_version: int | None) -> int:
        """Write the full overrides map with optimistic locking + JSON backup.

        Preserves any existing Dismissed map.
        """
        # Preserve existing dismissed map
        item = self.get_overrides()
        dismissed = dict(item.get("Dismissed", {})) if item else {}
        return self._put_all_with_dismissed(data, dismissed, expected_version)

    def _write_backup(self, data: dict[str, Any], dismissed: dict[str, Any] | None = None) -> None:
        """Write overrides to data/config/category_overrides.json (gitignored)."""
        try:
            _PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
            # Sort keys for stable diffs
            with open(_PERSONAL_DIR / "category_overrides.json", "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
            if dismissed:
                with open(_PERSONAL_DIR / "dismissed_suggestions.json", "w") as f:
                    json.dump(dismissed, f, indent=2, sort_keys=True)
                    f.write("\n")
        except Exception:
            logger.exception("Failed to write overrides backup")


class OverrideService(OverrideServiceBase):
    """CRUD operations for category overrides in DynamoDB."""

    TABLE_NAME = "CategoryConfig"

    def __init__(self, dyn_resource: "DynamoDBServiceResource | None" = None, user_id: str = "default"):
        if dyn_resource is None:
            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    def create_table(self) -> None:
        """Create CategoryConfig table (PK + SK, PAY_PER_REQUEST)."""
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

    def get_overrides(self) -> dict[str, Any] | None:
        """Return the full overrides item or None if not yet seeded.

        Returns dict with keys: Data (the overrides map), Version, UpdatedAt.
        Returns None if the table doesn't exist or the item is missing.
        """
        try:
            response = self.table.get_item(Key={"PK": self.USER_PK, "SK": self.OVERRIDES_SK})
        except Exception:
            logger.debug("Failed to read overrides from DynamoDB", exc_info=True)
            return None
        item = response.get("Item")
        if not item:
            return None
        return item

    def _put_all_with_dismissed(
        self, data: dict[str, Any], dismissed: dict[str, Any], expected_version: int | None
    ) -> int:
        """Write overrides + dismissed map with optimistic locking + backup."""
        new_version = (expected_version or 0) + 1

        item_to_put = {
            "PK": self.USER_PK,
            "SK": self.OVERRIDES_SK,
            "Data": data,
            "Version": new_version,
            "UpdatedAt": app_today().isoformat(),
        }
        if dismissed:
            item_to_put["Dismissed"] = dismissed
        dynamo_put_versioned(self.table, item_to_put, expected_version)
        self._write_backup(data, dismissed)
        return new_version
