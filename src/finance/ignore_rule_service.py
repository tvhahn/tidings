"""Merchant-pattern auto-ignore rule CRUD backed by DynamoDB with JSON backup.

Parallel to :mod:`src.finance.override_service`: a single config item holds the
set of merchant patterns that should pin matching transactions to *ignored* at
write time. Where an override maps ``company -> category``, an ignore rule is
just a membership set, so ``Data`` maps ``pattern -> ""`` (the value is unused;
:func:`src.finance.category_resolver.resolve_ignore` pins its own sentinel).
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3

from src.finance.aws_region import get_aws_region
from src.finance.category_resolver import ResolvedIgnore, resolve_ignore
from src.finance.demo_clock import app_today
from src.finance.dynamodb_utils import dynamo_put_versioned

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

logger = logging.getLogger(__name__)

_PERSONAL_DIR = Path(__file__).resolve().parents[2] / "data" / "config"


class IgnoreRuleServiceBase:
    """Shared business logic for merchant auto-ignore rules (storage-agnostic)."""

    IGNORE_RULES_SK = "CONFIG#ignore_rules"

    def get_rules(self) -> dict[str, Any] | None:
        """Return the full ignore-rules item or None if not yet seeded.

        Returns dict with keys: Data (dict[pattern, ""]), Version (int),
        UpdatedAt (str), Dismissed (optional). The Dismissed map is keyed by the
        lowercased merchant; each value is an object
        ``{"merchant": <original casing>, "dismissed_at": <ISO timestamp>}``.
        Read paths stay tolerant of the legacy shape where the value was a bare
        ISO-timestamp string (see :meth:`list_dismissed`).
        """
        raise NotImplementedError

    def _put_all_with_dismissed(
        self, data: dict[str, Any], dismissed: dict[str, Any], expected_version: int | None
    ) -> int:
        raise NotImplementedError

    def get_patterns(self) -> list[str]:
        """Return the ignore-rule patterns, sorted (original case preserved)."""
        item = self.get_rules()
        if item is None:
            return []
        return sorted(item.get("Data", {}).keys())

    def matches(self, company: str, aliases: dict[str, str] | None = None) -> ResolvedIgnore | None:
        """Return the ignore rule that fires for ``company`` via the tiered resolver, or None.

        Callers that want Tier 2 (alias-resolved) matching pass an ``aliases``
        map; without it only Tier 0/1 run — identical semantics to
        ``OverrideServiceBase.lookup_category``.
        """
        item = self.get_rules()
        if item is None:
            return None
        return resolve_ignore(company, item.get("Data", {}).keys(), aliases=aliases)

    def add_rule(self, pattern: str) -> int:
        """Add a merchant pattern to the ignore set. Returns the new version.

        Case-insensitive dedupe: adding a pattern that already exists (ignoring
        case) keeps the stored casing and simply bumps the version.
        """
        pattern = pattern.strip()
        if not pattern:
            raise ValueError("pattern cannot be empty")

        item = self.get_rules()
        if item is None:
            data: dict[str, Any] = {}
            expected_version = None
        else:
            data = dict(item.get("Data", {}))
            expected_version = int(item.get("Version", 0))

        for key in data:
            if key.lower() == pattern.lower():
                # Already present (case-insensitive) — no-op write to keep the
                # optimistic-locking contract identical to a real change.
                return self._put_all(data, expected_version)

        data[pattern] = ""
        return self._put_all(data, expected_version)

    def delete_rule(self, pattern: str) -> int:
        """Remove a merchant pattern. Returns the new version. Raises KeyError if absent."""
        item = self.get_rules()
        if item is None:
            raise KeyError(pattern)

        data = dict(item.get("Data", {}))
        found_key = None
        for key in data:
            if key.lower() == pattern.lower():
                found_key = key
                break
        if found_key is None:
            raise KeyError(pattern)

        del data[found_key]
        return self._put_all(data, int(item.get("Version", 0)))

    def put_all_rules(self, patterns: list[str], expected_version: int | None) -> int:
        """Replace the entire ignore set at once with optimistic locking. Returns new version."""
        data = {p.strip(): "" for p in patterns if p.strip()}
        return self._put_all(data, expected_version)

    def get_dismissed(self) -> dict[str, Any]:
        """Return the raw Dismissed map (merchant_lower -> value), empty if unset.

        The value is normally an object ``{"merchant", "dismissed_at"}`` but may
        be a legacy bare ISO-timestamp string. Suggestion filtering only reads
        the (lowercased) keys, so it is agnostic to the value shape; callers that
        need to *display* dismissals should use :meth:`list_dismissed`, which
        normalizes both shapes.
        """
        item = self.get_rules()
        if item is None:
            return {}
        return dict(item.get("Dismissed", {}))

    def list_dismissed(self) -> list[dict[str, str]]:
        """Return dismissed suggestions as ``[{merchant, dismissed_at}]``, newest first.

        Normalizes both stored value shapes:

        - **Current**: ``{"merchant": <original casing>, "dismissed_at": <ISO>}``
          — used directly.
        - **Legacy** (pre-upgrade backups/tests): a bare ISO-timestamp string —
          the map key becomes the display merchant (lowercased, casing lost) and
          the string becomes ``dismissed_at``.
        """
        out: list[dict[str, str]] = []
        for key, value in self.get_dismissed().items():
            if isinstance(value, dict):
                merchant = str(value.get("merchant") or key)
                dismissed_at = str(value.get("dismissed_at") or "")
            else:
                merchant = key
                dismissed_at = str(value or "")
            out.append({"merchant": merchant, "dismissed_at": dismissed_at})
        out.sort(key=lambda d: d["dismissed_at"], reverse=True)
        return out

    def dismiss_suggestion(self, merchant: str) -> None:
        """Record a dismissed suggestion so ``merchant`` stops being suggested.

        Keyed by the lowercased merchant on the ``Dismissed`` map of the
        ignore-rules config item — parallel to
        :meth:`OverrideServiceBase.dismiss_suggestion`. The stored value is an
        object ``{"merchant": <original casing>, "dismissed_at": <ISO>}`` so a
        management view can show the merchant's real casing (the key stays
        lowercased for case-insensitive filtering). The dismissal persists until
        :meth:`undismiss_suggestion` reverses it; there is no timestamp-driven
        resurfacing (an ignore suggestion has no "newer correction" signal the
        way a category override does).
        """
        item = self.get_rules()
        if item is None:
            data: dict[str, Any] = {}
            dismissed: dict[str, Any] = {}
            expected_version = None
        else:
            data = dict(item.get("Data", {}))
            dismissed = dict(item.get("Dismissed", {}))
            expected_version = int(item.get("Version", 0))

        merchant = merchant.strip()
        dismissed[merchant.lower()] = {
            "merchant": merchant,
            "dismissed_at": datetime.now(UTC).isoformat(),
        }
        self._put_all_with_dismissed(data, dismissed, expected_version)

    def undismiss_suggestion(self, merchant: str) -> None:
        """Reverse a dismissal so ``merchant`` may be suggested again. No-op if absent."""
        item = self.get_rules()
        if item is None:
            return

        dismissed = dict(item.get("Dismissed", {}))
        key = merchant.strip().lower()
        if key not in dismissed:
            return

        del dismissed[key]
        data = dict(item.get("Data", {}))
        expected_version = int(item.get("Version", 0))
        self._put_all_with_dismissed(data, dismissed, expected_version)

    def _put_all(self, data: dict[str, Any], expected_version: int | None) -> int:
        """Write the full ignore-rules map, preserving any existing Dismissed map."""
        item = self.get_rules()
        dismissed = dict(item.get("Dismissed", {})) if item else {}
        return self._put_all_with_dismissed(data, dismissed, expected_version)

    def _write_backup(self, data: dict[str, Any], dismissed: dict[str, Any] | None = None) -> None:
        """Write patterns to data/config/ignore_rules.json (gitignored) as a sorted list.

        The dismissed-suggestions map, when present, is backed up alongside in
        data/config/ignore_rules_dismissed.json.
        """
        try:
            _PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
            with open(_PERSONAL_DIR / "ignore_rules.json", "w") as f:
                json.dump(sorted(data.keys()), f, indent=2)
                f.write("\n")
            if dismissed:
                with open(_PERSONAL_DIR / "ignore_rules_dismissed.json", "w") as f:
                    json.dump(dismissed, f, indent=2, sort_keys=True)
                    f.write("\n")
        except Exception:
            logger.exception("Failed to write ignore-rules backup")


class IgnoreRuleService(IgnoreRuleServiceBase):
    """CRUD operations for merchant auto-ignore rules in DynamoDB."""

    TABLE_NAME = "CategoryConfig"

    def __init__(self, dyn_resource: "DynamoDBServiceResource | None" = None, user_id: str = "default"):
        if dyn_resource is None:
            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    def get_rules(self) -> dict[str, Any] | None:
        try:
            response = self.table.get_item(Key={"PK": self.USER_PK, "SK": self.IGNORE_RULES_SK})
        except Exception:
            logger.debug("Failed to read ignore rules from DynamoDB", exc_info=True)
            return None
        item = response.get("Item")
        if not item:
            return None
        return item

    def _put_all_with_dismissed(
        self, data: dict[str, Any], dismissed: dict[str, Any], expected_version: int | None
    ) -> int:
        """Write ignore-rules + dismissed map with optimistic locking + JSON backup."""
        new_version = (expected_version or 0) + 1
        item_to_put = {
            "PK": self.USER_PK,
            "SK": self.IGNORE_RULES_SK,
            "Data": data,
            "Version": new_version,
            "UpdatedAt": app_today().isoformat(),
        }
        if dismissed:
            item_to_put["Dismissed"] = dismissed
        dynamo_put_versioned(self.table, item_to_put, expected_version)
        self._write_backup(data, dismissed)
        return new_version
