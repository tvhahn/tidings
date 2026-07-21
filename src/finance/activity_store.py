"""DynamoDB implementation of the agent-activity ledger.

Mirrors :class:`~src.finance.activity_store_local.ActivityStoreLocal`. Records
one append-only entry per mutating API write so an operator can see who did
what, and revert it.

Item shape (single-table, PK/SK):

* ``PK`` = ``USER#<user_id>``
* ``SK`` = ``ACT#<ts_iso>#<id8>`` — ``ts_iso`` is the entry's timezone-aware UTC
  timestamp (so a ``ScanIndexForward=False`` query yields newest-first), and
  ``id8`` is the first 8 chars of the entry id (a tiebreaker that keeps the SK
  unique when two entries share a millisecond).
* ledger fields as top-level snake_case attributes, plus a numeric ``ttl``
  attribute (``ts + 90 days`` epoch seconds) so DynamoDB expires stale entries
  on the same horizon the SQLite backend prunes.

Append-only: ``record`` puts, ``mark_reverted`` sets the two revert-marker
attributes, and reads never mutate. There is no update/delete beyond the
marker.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.finance.aws_region import get_aws_region

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

logger = logging.getLogger(__name__)

# Retention horizon — DynamoDB TTL expires items this many days after ``ts``.
# Kept identical to the SQLite prune window so the two backends agree on how
# long a revert stays possible.
RETENTION_DAYS = 90

# The ledger fields returned to callers, in item and row order. ``ttl`` is
# deliberately absent: it is a DynamoDB-only storage detail (and a Decimal on
# read), so it never leaks into the normalized entry dict.
_ENTRY_FIELDS = (
    "id",
    "ts",
    "principal_kind",
    "principal_id",
    "principal_label",
    "operation_id",
    "method",
    "path",
    "resource_id",
    "summary",
    "before_json",
    "after_json",
    "reversible",
    "reverted_at",
    "reverted_by",
)


def _utc_now_iso() -> str:
    """Timezone-aware UTC ISO-8601 timestamp."""
    return datetime.now(UTC).isoformat()


class ActivityStore:
    """DynamoDB-backed append-only agent-activity ledger."""

    TABLE_NAME = "Activity"

    def __init__(self, dyn_resource: DynamoDBServiceResource | None = None, user_id: str = "default") -> None:
        if dyn_resource is None:
            import boto3

            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    # ------------------------------------------------------------------
    # Table lifecycle — lazy auto-create (mirrors the ParseFailures table),
    # with TTL enabled after creation.
    # ------------------------------------------------------------------
    def create_table(self) -> None:
        """Create the Activity table (PK + SK, PAY_PER_REQUEST)."""
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

    def _enable_ttl(self) -> None:
        """Enable DynamoDB TTL on the ``ttl`` attribute (idempotent).

        DynamoDB raises a ``ValidationException`` when TTL is already enabled (or
        mid-transition) for the attribute; that is benign, so we swallow it.
        """
        try:
            self.dyn_resource.meta.client.update_time_to_live(
                TableName=self.TABLE_NAME,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ValidationException":
                logger.debug("TTL already enabled on %s", self.TABLE_NAME)
            else:
                raise

    def _ensure_table(self) -> None:
        """Create the table (and enable TTL) on first access if it doesn't exist."""
        try:
            self.table.load()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                self.create_table()
                self.table = self.dyn_resource.Table(self.TABLE_NAME)
                self._enable_ttl()
            else:
                raise

    @staticmethod
    def _compute_ttl(ts: str) -> int:
        """Epoch-second TTL: ``ts`` + retention window. Naive ``ts`` is UTC."""
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int((dt + timedelta(days=RETENTION_DAYS)).timestamp())

    def record(self, entry: dict[str, Any]) -> str:
        """Append a ledger entry and return its id.

        ``id`` defaults to a fresh ``uuid4().hex``; ``ts`` defaults to the
        current timezone-aware UTC time. Append-only — every call is a new item.
        """
        self._ensure_table()
        entry_id = entry.get("id") or uuid.uuid4().hex
        ts = entry.get("ts") or _utc_now_iso()
        id8 = entry_id[:8]
        item: dict[str, Any] = {
            "PK": self.USER_PK,
            "SK": f"ACT#{ts}#{id8}",
            "id": entry_id,
            "ts": ts,
            "principal_kind": entry.get("principal_kind"),
            "principal_id": entry.get("principal_id"),
            "principal_label": entry.get("principal_label"),
            "operation_id": entry.get("operation_id"),
            "method": entry.get("method"),
            "path": entry.get("path"),
            "resource_id": entry.get("resource_id"),
            "summary": entry.get("summary"),
            "before_json": entry.get("before_json"),
            "after_json": entry.get("after_json"),
            "reversible": bool(entry.get("reversible", False)),
            "reverted_at": entry.get("reverted_at"),
            "reverted_by": entry.get("reverted_by"),
            "ttl": self._compute_ttl(ts),
        }
        self.table.put_item(Item=item)
        return entry_id

    def _item_to_entry(self, item: dict[str, Any]) -> dict[str, Any]:
        """Map a DynamoDB item to a normalized entry dict (no ``ttl``/keys)."""
        entry = {field: item.get(field) for field in _ENTRY_FIELDS}
        entry["reversible"] = bool(entry.get("reversible"))
        return entry

    def _query_all(self) -> list[dict[str, Any]]:
        """Query every ledger item for this user, newest ``ts`` first (paginated)."""
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(self.USER_PK) & Key("SK").begins_with("ACT#"),
            "ScanIndexForward": False,  # newest ts first (SK sorts by ts_iso)
        }
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    def list_entries(
        self,
        principal: str | None = None,
        since: str | None = None,
        operation: str | None = None,
        limit: int = 100,
        principal_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """List ledger entries newest-first, filtered then limited.

        ``principal`` exact-matches ``principal_id``; ``principal_kind``
        exact-matches ``principal_kind`` (so a non-token caller's own feed is
        filtered before the limit, never crowded out by token entries); ``since``
        is an inclusive ISO-8601 lower bound on ``ts``; ``operation``
        exact-matches ``operation_id``; ``limit`` is applied after filtering.
        """
        self._ensure_table()
        entries = [self._item_to_entry(i) for i in self._query_all()]
        if principal is not None:
            entries = [e for e in entries if e.get("principal_id") == principal]
        if principal_kind is not None:
            entries = [e for e in entries if e.get("principal_kind") == principal_kind]
        if since is not None:
            entries = [e for e in entries if str(e.get("ts") or "") >= since]
        if operation is not None:
            entries = [e for e in entries if e.get("operation_id") == operation]
        # No re-sort before the slice: _query_all already returns newest-ts-first
        # (ScanIndexForward=False over the ts-ordered SK), and every filter above
        # preserves that order, so entries[:limit] keeps the newest matches.
        return entries[:limit]

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Return a single ledger entry by id, or None.

        An id-only lookup has no index (the SK is keyed by ``ts``, not ``id``), so
        this necessarily scans the user's partition — there is no cheaper path.
        """
        self._ensure_table()
        for item in self._query_all():
            if item.get("id") == entry_id:
                return self._item_to_entry(item)
        return None

    def mark_reverted(self, entry_id: str, reverted_by_entry_id: str, ts: str | None = None) -> None:
        """Stamp ``reverted_at``/``reverted_by`` on an entry (the only mutation).

        When ``ts`` is provided the item key is reconstructed directly
        (``SK = ACT#<ts>#<id8>``) so the update is a single ``update_item`` with
        no partition scan — the revert handler always passes the original entry's
        ``ts`` for exactly this reason. The update is conditioned on the item
        actually existing: a bare ``update_item`` on a mismatched key would
        *create* a phantom row, so a failed condition falls back to the scan
        path instead. When ``ts`` is None (defensive fallback) the partition is
        scanned to find the item by id.
        """
        self._ensure_table()
        if ts is not None:
            try:
                self.table.update_item(
                    Key={"PK": self.USER_PK, "SK": f"ACT#{ts}#{entry_id[:8]}"},
                    UpdateExpression="SET reverted_at = :ra, reverted_by = :rb",
                    ConditionExpression="attribute_exists(id)",
                    ExpressionAttributeValues={
                        ":ra": _utc_now_iso(),
                        ":rb": reverted_by_entry_id,
                    },
                )
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
                ts = None  # key mismatch — fall through to the scan path below
        if ts is not None:
            return
        for item in self._query_all():
            if item.get("id") == entry_id:
                self.table.update_item(
                    Key={"PK": item["PK"], "SK": item["SK"]},
                    UpdateExpression="SET reverted_at = :ra, reverted_by = :rb",
                    ExpressionAttributeValues={
                        ":ra": _utc_now_iso(),
                        ":rb": reverted_by_entry_id,
                    },
                )
                return
