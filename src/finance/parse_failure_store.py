"""DynamoDB implementation of the parse-failure (dead-letter) store.

Mirrors :class:`~src.finance.parse_failure_store_local.ParseFailureStoreLocal`.
Stores unparseable bank emails so they can be reviewed and retried later.

Item shape (single-table, PK/SK):

* ``PK`` = ``USER#<user_id>``
* ``SK`` = ``FAIL#<received_at>#<id>`` — ``received_at`` is derived from the
  email's own ``date`` header (stable across redeliveries) so a redelivered
  email maps to the same SK and ``put_item`` is a natural upsert.
* row fields as top-level PascalCase attributes (``ReceivedAt``,
  ``FailureStage``, ``EmailJson`` …), plus a ``FailureId`` attribute so
  ``get_failure(id)`` can resolve via a ``Query`` on PK + ``FilterExpression``
  without knowing the SK.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from src.finance.aws_region import get_aws_region
from src.finance.category_audit import now_local_iso
from src.finance.parse_failure_store_base import ParseFailureStoreBase
from src.finance.parse_failure_store_local import failure_id_for

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

logger = logging.getLogger(__name__)


class ParseFailureStore(ParseFailureStoreBase):
    """DynamoDB-backed dead-letter store for unparseable bank emails."""

    TABLE_NAME = "ParseFailures"

    def __init__(self, dyn_resource: DynamoDBServiceResource | None = None, user_id: str = "default") -> None:
        if dyn_resource is None:
            import boto3

            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.dyn_resource: DynamoDBServiceResource = dyn_resource
        self.table: Table = dyn_resource.Table(self.TABLE_NAME)
        self.USER_PK = f"USER#{user_id}"

    # ------------------------------------------------------------------
    # Table lifecycle — lazy auto-create (mirrors the Transactions table).
    # ------------------------------------------------------------------
    def create_table(self) -> None:
        """Create the ParseFailures table (PK + SK, PAY_PER_REQUEST)."""
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

    def _ensure_table(self) -> None:
        """Create the table on first access if it does not yet exist.

        Follows the lazy-create pattern: probe, and on ResourceNotFoundException
        create the table and re-bind ``self.table``.
        """
        try:
            self.table.load()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                self.create_table()
                self.table = self.dyn_resource.Table(self.TABLE_NAME)
            else:
                raise

    @staticmethod
    def _sk_token_for(failure: dict[str, Any], email_details: dict[str, Any]) -> str:
        """Stable SK ordering token — the email's own ``date`` header.

        Using the email's ``date`` (stable across redeliveries) rather than
        wall-clock keeps the SK identical for a redelivered email, so
        ``put_item`` upserts instead of duplicating. ``ReceivedAt`` (the ISO
        wall-clock attribute used for recency windows) is stored separately.
        """
        date_header = email_details.get("date")
        if date_header:
            return str(date_header)
        # No date header: a wall-clock fallback would give the same email a new
        # SK on every redelivery (duplicating the item under one FailureId), so
        # use a constant — recency ordering comes from ``ReceivedAt``, not the SK.
        return "undated"

    def record_failure(self, failure: dict[str, Any]) -> str:
        """Persist (idempotently) a parse failure and return its deterministic id."""
        self._ensure_table()
        email_details = failure.get("email_details") or {}
        failure_id = failure.get("id") or failure_id_for(email_details)
        sk_token = self._sk_token_for(failure, email_details)
        now = now_local_iso()
        # ReceivedAt is an ISO wall-clock timestamp (for recency windows /
        # ordering). The SK uses the email-date token for redelivery idempotency.
        received_at = str(failure.get("received_at") or now)
        email_json = failure.get("email_json")
        if email_json is None:
            email_json = json.dumps(email_details)
        classifier = failure.get("alert_classifier_result")

        item: dict[str, Any] = {
            "PK": self.USER_PK,
            "SK": f"FAIL#{sk_token}#{failure_id}",
            "FailureId": failure_id,
            "ReceivedAt": received_at,
            "FromEmail": failure.get("from_email") or email_details.get("from_email"),
            "Subject": failure.get("subject") or email_details.get("subject"),
            "FileName": failure.get("file_name") or email_details.get("file_name"),
            "DetectedInstitution": failure.get("detected_institution"),
            "FailureStage": failure.get("failure_stage", "no_parser_match"),
            "Status": failure.get("status", "quarantined"),
            "RecoveredDateFileName": failure.get("recovered_date_file_name"),
            "AlertClassifierResult": self.coerce_classifier(classifier),
            "EmailJson": email_json,
            "CreatedAt": received_at,
            "UpdatedAt": now,
        }
        # Pruning: SQLite prunes on write; DynamoDB rows are few and cheap —
        # revisit with TTL if needed.
        self.table.put_item(Item=item)
        return failure_id

    def _item_to_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        """Map a DynamoDB item to a summary dict (no ``email_json``)."""
        return {
            "id": item.get("FailureId"),
            "received_at": item.get("ReceivedAt"),
            "from_email": item.get("FromEmail"),
            "subject": item.get("Subject"),
            "file_name": item.get("FileName"),
            "detected_institution": item.get("DetectedInstitution"),
            "failure_stage": item.get("FailureStage"),
            "status": item.get("Status"),
            "recovered_date_file_name": item.get("RecoveredDateFileName"),
            "alert_classifier_result": item.get("AlertClassifierResult"),
            "created_at": item.get("CreatedAt"),
            "updated_at": item.get("UpdatedAt"),
        }

    def get_failure(self, failure_id: str) -> dict[str, Any] | None:
        """Return the full failure row (including ``email_json``) or None.

        Resolves via the deduplicated ``_query_all`` pass — the same cost as the
        previous filtered full-partition Query (failures are rare), but it can
        never surface a stale legacy duplicate; a GSI would be the move if this
        table ever grows large.
        """
        self._ensure_table()
        for item in self._query_all():
            if item.get("FailureId") == failure_id:
                summary = self._item_to_summary(item)
                summary["email_json"] = item.get("EmailJson")
                return summary
        return None

    def _query_all(self) -> list[dict[str, Any]]:
        """Query every failure item for this user (paginated)."""
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(self.USER_PK) & Key("SK").begins_with("FAIL#"),
            "ScanIndexForward": False,  # newest received_at first
        }
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        # Legacy items written before the SK token was stable for date-less
        # emails can share a FailureId across different SKs; keep only the most
        # recently updated item per id so every read path sees one coherent row.
        by_id: dict[str, dict[str, Any]] = {}
        for item in items:
            fid = str(item.get("FailureId"))
            kept = by_id.get(fid)
            if kept is None or str(item.get("UpdatedAt") or "") > str(kept.get("UpdatedAt") or ""):
                by_id[fid] = item
        return list(by_id.values())

    def list_failures(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List failure summaries (no ``email_json``), newest first."""
        self._ensure_table()
        items = self._query_all()
        summaries = [self._item_to_summary(i) for i in items]
        if status is not None:
            summaries = [s for s in summaries if s.get("status") == status]
        summaries.sort(key=lambda s: str(s.get("received_at") or ""), reverse=True)
        return summaries[:limit]

    def list_failures_full(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List full failure rows (including ``email_json``), newest first.

        Like :meth:`list_failures` but keeps each ``EmailJson`` body, built from
        the single ``_query_all`` pass — the bulk-retry sweep needs the bodies to
        re-run the parsers, so this avoids a per-id ``get_failure`` re-query (each
        of which is another full-partition Query) for every matched row.
        """
        self._ensure_table()
        rows: list[dict[str, Any]] = []
        for item in self._query_all():
            if status is not None and item.get("Status") != status:
                continue
            full = self._item_to_summary(item)
            full["email_json"] = item.get("EmailJson")
            rows.append(full)
        rows.sort(key=lambda r: str(r.get("received_at") or ""), reverse=True)
        return rows[:limit]

    def set_status(self, failure_id: str, status: str, recovered_date_file_name: str | None = None) -> bool:
        """Transition a failure to ``status``. Returns True if a row was updated.

        ``recovered_date_file_name`` is written only when non-None. Passing None
        (a dismiss, or a duplicate retry/resolve where no new row was created)
        leaves any existing ``RecoveredDateFileName`` intact rather than clearing
        the link to the transaction that already recovered this failure.
        """
        self._ensure_table()
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(self.USER_PK),
            "FilterExpression": Attr("FailureId").eq(failure_id),
        }
        target: dict[str, Any] | None = None
        while target is None:
            response = self.table.query(**kwargs)
            for item in response.get("Items", []):
                target = item
                break
            last_key = response.get("LastEvaluatedKey")
            if target is not None or not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        if target is None:
            return False
        set_clauses = ["#s = :s", "UpdatedAt = :u"]
        values: dict[str, Any] = {":s": status, ":u": now_local_iso()}
        if recovered_date_file_name is not None:
            set_clauses.append("RecoveredDateFileName = :r")
            values[":r"] = recovered_date_file_name
        self.table.update_item(
            Key={"PK": target["PK"], "SK": target["SK"]},
            UpdateExpression="SET " + ", ".join(set_clauses),
            ExpressionAttributeNames={"#s": "Status"},
            ExpressionAttributeValues=values,
        )
        return True

    def count_recent_quarantined(self, days: int = 7) -> int:
        """Count rows still in ``quarantined`` status within the last ``days``."""
        self._ensure_table()
        cutoff = (datetime.fromisoformat(now_local_iso()) - timedelta(days=days)).isoformat()
        count = 0
        for item in self._query_all():
            if item.get("Status") == "quarantined" and str(item.get("ReceivedAt", "")) > cutoff:
                count += 1
        return count

    def latest_received_by_institution(self) -> dict[str, str]:
        """Map each detected institution to its most recent ``ReceivedAt``.

        Scans every deduplicated failure item (any status) and keeps the largest
        ``ReceivedAt`` per non-null ``DetectedInstitution``.
        """
        self._ensure_table()
        latest: dict[str, str] = {}
        for item in self._query_all():
            institution = item.get("DetectedInstitution")
            if institution is None:
                continue
            received = str(item.get("ReceivedAt") or "")
            if not received:
                continue
            if received > latest.get(institution, ""):
                latest[institution] = received
        return latest

    def has_other_recent_failure(self, institution: str, hours: int = 24) -> bool:
        """Whether another quarantined failure for ``institution`` exists in the window.

        ``count > 1`` semantics: the just-recorded row is already stored, so
        ``True`` means at least one *other* prior quarantined failure for the
        same institution exists within the last ``hours`` hours.
        """
        self._ensure_table()
        cutoff = (datetime.fromisoformat(now_local_iso()) - timedelta(hours=hours)).isoformat()
        count = 0
        for item in self._query_all():
            if (
                item.get("DetectedInstitution") == institution
                and item.get("Status") == "quarantined"
                and str(item.get("ReceivedAt", "")) > cutoff
            ):
                count += 1
        return count > 1
