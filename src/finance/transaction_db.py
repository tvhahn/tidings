import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from dateutil.parser import parse

from src.finance.app_timezone import get_tzinfos
from src.finance.category_audit import build_audit
from src.finance.decimal_utils import decimal_to_float, to_decimal
from src.finance.transaction_db_base import TransactionsDBBase
from src.finance.transaction_hash import bump_hash_occurrence, generate_transaction_hash

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

    from src.finance.protocols import TransactionItem

logger = logging.getLogger(__name__)


class TransactionsDB(TransactionsDBBase):
    def __init__(self, dyn_resource: "DynamoDBServiceResource") -> None:
        self.dyn_resource = dyn_resource
        self.table: Table | None = None

    def _transaction_exists(self, table: "Table", forwarded_to: str, transaction_hash: str) -> bool:
        """Check if a transaction with the same hash already exists. Fails open.

        Must paginate: FilterExpression is applied AFTER the 1MB read limit
        (computed on full item size, and items carry the raw email Body), so a
        single-page query silently stops deduplicating once the partition
        outgrows one page. Early-exits on the first match. A check-then-put
        race between concurrent writers remains possible for the same email
        delivered twice within one round-trip; true Lambda retries reuse the
        same DateFileName so their put_item is an idempotent overwrite.
        """
        try:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("ForwardedTo").eq(forwarded_to),
                "FilterExpression": Attr("TransactionHash").eq(transaction_hash),
                "ProjectionExpression": "ForwardedTo",
            }
            while True:
                response = table.query(**kwargs)
                if response.get("Count", 0) > 0:
                    return True
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    return False
                kwargs["ExclusiveStartKey"] = last_key
        except ClientError as e:
            logger.warning("Duplicate check failed, allowing write: %s", e)
            return False

    def add_transaction(
        self,
        transaction_data: dict[str, Any],
        category_audit: dict[str, Any] | None = None,
        extraction_audit: dict[str, Any] | None = None,
    ) -> str | bool | None:
        """Adds a new transaction record to the DynamoDB table.

        When `category_audit` is provided, its dict is persisted to the
        CategoryAudit attribute on the new row. Typical shape:
        `{"source": "override_normalized", "matched_rule": "...", "confidence": 1.0, "reviewed_at": "..."}`.

        When `extraction_audit` is provided, its dict is persisted to the
        ExtractionAudit attribute (provenance for AI-recovered rows; see
        `build_extraction_audit`). Numeric fields are coerced float→Decimal
        exactly like CategoryAudit.

        Returns the DateFileName string if the transaction was written (truthy),
        False if it was a duplicate, or None if required fields were missing.
        """
        table_name = "Transactions"

        # Validate required fields
        missing = self._validate_required_fields(
            transaction_data,
            ["forwarded_to", "file_name", "date", "amount", "institution", "transaction_type"],
        )
        if missing:
            logger.error("Missing required field: %s in transaction data: %s", missing, transaction_data)
            return None

        # Generate deduplication hash
        transaction_hash = generate_transaction_hash(transaction_data)

        try:
            table = self.dyn_resource.Table(table_name)

            # Check for duplicate transaction
            if self._transaction_exists(table, transaction_data["forwarded_to"], transaction_hash):
                logger.info("Duplicate transaction detected (hash=%s). Skipping write.", transaction_hash)
                return False

            # Parse the date string with dateutil to handle timezone
            date_obj = parse(transaction_data["date"], tzinfos=get_tzinfos())
            # Format date and concatenate with file name
            formatted_date_str = date_obj.strftime("%Y.%m.%d_%H.%M")
            date_file_name = f"{formatted_date_str}_{transaction_data['file_name'].split('/')[-1]}"

            # Handle potential None values for non-key attributes
            transaction_data["user_id"] = transaction_data.get("user_id")
            transaction_data["from_name"] = transaction_data.get("from_name")
            transaction_data["from_email"] = (
                str.lower(transaction_data["from_email"]) if "from_email" in transaction_data else None
            )
            transaction_data["to_name"] = transaction_data.get("to_name")
            transaction_data["to_email"] = (
                str.lower(transaction_data["to_email"]) if "to_email" in transaction_data else None
            )
            transaction_data["institution"] = transaction_data.get("institution")
            transaction_data["subject"] = transaction_data.get("subject")
            transaction_data["body"] = transaction_data.get("body")
            transaction_data["name"] = transaction_data.get("name")
            transaction_data["company"] = transaction_data.get("company")
            transaction_data["amount"] = (
                Decimal(str(transaction_data["amount"])) if transaction_data.get("amount") is not None else None
            )
            transaction_data["transaction_type"] = transaction_data.get("transaction_type")

            transaction_data["category"] = self._normalize_category(transaction_data)

            item = {
                "ForwardedTo": transaction_data["forwarded_to"],
                "DateFileName": date_file_name,
                "FileName": transaction_data["file_name"],
                "Date": transaction_data["date"],
                "UserId": transaction_data["user_id"],
                "FromName": transaction_data["from_name"],
                "FromEmail": transaction_data["from_email"],
                "ToName": transaction_data["to_name"],
                "ToEmail": transaction_data["to_email"],
                "Institution": transaction_data["institution"],
                "Subject": transaction_data["subject"],
                "Body": transaction_data["body"],
                "Name": transaction_data["name"],
                "Amount": transaction_data["amount"],
                "Company": transaction_data["company"],
                "TransactionType": transaction_data["transaction_type"],
                "Category": transaction_data["category"],
                "TransactionHash": transaction_hash,
            }
            if self._resolve_ignored(transaction_data):
                # A merchant auto-ignore rule matched (or the row was flagged
                # ignored upstream) — arrive Ignored so it never distorts totals.
                item["Ignored"] = True
            if category_audit is not None:
                # DynamoDB rejects Python float; numeric audit fields (confidence) must be Decimal.
                item["CategoryAudit"] = {k: to_decimal(v) for k, v in category_audit.items()}
            if extraction_audit is not None:
                # Same float→Decimal coercion as CategoryAudit above.
                item["ExtractionAudit"] = {k: to_decimal(v) for k, v in extraction_audit.items()}
            response = table.put_item(Item=item)
            logger.info("Transaction added to %s: %s", table_name, response)
            return date_file_name
        except ClientError:
            logger.exception("Failed to add transaction to %s.", table_name)
            raise

    def _audit_dynamo_safe(self, audit: dict[str, Any]) -> dict[str, Any]:
        """DynamoDB rejects Python float — coerce numeric audit fields to Decimal."""
        return {k: to_decimal(v) for k, v in audit.items()}

    def _read_previous_category_state(self, forwarded_to: str, date_file_name: str) -> tuple[str | None, str | None]:
        """Return (previous_category, previous_source) for the row, or (None, None) if absent."""
        existing = self.get_item(forwarded_to, date_file_name)
        if not existing:
            return None, None
        prev_audit = existing.get("CategoryAudit") or {}
        return existing.get("Category"), prev_audit.get("source")

    def update_category(
        self, forwarded_to: str, date_file_name: str, new_category: str, source: str = "manual"
    ) -> str | None:
        """Update a transaction's category and write audit metadata.

        Returns the old category value, or None if the item was not found.
        """
        table = self.dyn_resource.Table("Transactions")
        prev_category, prev_source = self._read_previous_category_state(forwarded_to, date_file_name)
        audit = build_audit(source, previous_category=prev_category, previous_source=prev_source)
        response = table.update_item(
            Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
            UpdateExpression="SET Category = :cat, CategoryAudit = :audit",
            ExpressionAttributeValues={
                ":cat": new_category.lower(),
                ":audit": self._audit_dynamo_safe(audit),
            },
            ReturnValues="UPDATED_OLD",
        )
        # boto3-stubs types Attributes values as the full DynamoDB scalar union; this
        # column is a lowercased category string. Narrow at the boto3 boundary.
        return cast("str | None", response.get("Attributes", {}).get("Category"))

    def mark_category_reviewed(self, forwarded_to: str, date_file_name: str, source: str = "audit") -> None:
        """Mark a transaction's category as reviewed without changing it."""
        table = self.dyn_resource.Table("Transactions")
        table.update_item(
            Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
            UpdateExpression="SET CategoryAudit = :audit",
            ExpressionAttributeValues={
                ":audit": self._audit_dynamo_safe(build_audit(source)),
            },
        )

    def enrich_transaction(
        self,
        forwarded_to: str,
        date_file_name: str,
        new_company: str,
        new_category: str,
        source: str = "statement_enrich",
        statement_source: str | None = None,
    ) -> dict[str, Any] | None:
        """Enrich an existing transaction's company and category from statement data.

        Company (and StatementSource, when provided) always update. The category
        is preserved — Category and CategoryAudit left untouched — when the
        existing row was manually categorized or when the incoming category is
        the ``miscellaneous`` fallback and the existing one is real (see
        ``_resolve_enrich_category``). Otherwise Category and CategoryAudit are
        rewritten. Returns {"old_company", "old_category", "category_preserved"},
        or None if item not found.
        """
        table = self.dyn_resource.Table("Transactions")
        prev_category, prev_source = self._read_previous_category_state(forwarded_to, date_file_name)
        preserve = self._resolve_enrich_category(prev_category, prev_source, new_category.lower(), source)

        if preserve:
            logger.info(
                "enrich_transaction: preserving category %r (source=%r) over incoming %r (source=%r) for %s",
                prev_category,
                prev_source,
                new_category.lower(),
                source,
                date_file_name,
            )
            expr = "SET Company = :comp"
            values: dict[str, Any] = {":comp": new_company}
            if statement_source is not None:
                expr += ", StatementSource = :src"
                values[":src"] = statement_source
            response = table.update_item(
                Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
                UpdateExpression=expr,
                ExpressionAttributeValues=values,
                ReturnValues="UPDATED_OLD",
            )
            attrs = response.get("Attributes", {})
            # Category isn't in UPDATED_OLD here (not written) — use the value we already read.
            return {"old_company": attrs.get("Company"), "old_category": prev_category, "category_preserved": True}

        audit = build_audit(source, previous_category=prev_category, previous_source=prev_source)
        expr = "SET Company = :comp, Category = :cat, CategoryAudit = :audit"
        values = {
            ":comp": new_company,
            ":cat": new_category.lower(),
            ":audit": self._audit_dynamo_safe(audit),
        }
        if statement_source is not None:
            expr += ", StatementSource = :src"
            values[":src"] = statement_source
        response = table.update_item(
            Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
            UpdateExpression=expr,
            ExpressionAttributeValues=values,
            ReturnValues="UPDATED_OLD",
        )
        attrs = response.get("Attributes", {})
        return {
            "old_company": attrs.get("Company"),
            "old_category": attrs.get("Category"),
            "category_preserved": False,
        }

    def update_fields(
        self,
        forwarded_to: str,
        date_file_name: str,
        fields: dict[str, Any],
        category: str | None = None,
    ) -> dict[str, Any] | None:
        """Update transaction fields (company, amount, transaction_type) and audit metadata.

        Dynamically builds UpdateExpression from provided fields.
        Returns old values via ReturnValues="UPDATED_OLD", or None if no fields provided.
        """
        if not fields:
            return None

        table = self.dyn_resource.Table("Transactions")

        expr_parts = []
        attr_values: dict[str, Any] = {}
        attr_names: dict[str, str] = {}

        if "company" in fields:
            expr_parts.append("Company = :comp")
            attr_values[":comp"] = fields["company"]

        if "amount" in fields:
            expr_parts.append("Amount = :amt")
            attr_values[":amt"] = Decimal(str(fields["amount"]))

        if "transaction_type" in fields:
            expr_parts.append("TransactionType = :tt")
            attr_values[":tt"] = fields["transaction_type"]

        prev_category: str | None = None
        prev_source: str | None = None
        if category is not None:
            expr_parts.append("Category = :cat")
            attr_values[":cat"] = category.lower()
            prev_category, prev_source = self._read_previous_category_state(forwarded_to, date_file_name)

        expr_parts.append("CategoryAudit = :audit")
        attr_values[":audit"] = self._audit_dynamo_safe(
            build_audit(
                "manual_edit",
                previous_category=prev_category,
                previous_source=prev_source,
            )
        )

        update_expr = "SET " + ", ".join(expr_parts)

        kwargs = {
            "Key": {"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
            "UpdateExpression": update_expr,
            "ExpressionAttributeValues": attr_values,
            "ReturnValues": "UPDATED_OLD",
        }
        if attr_names:
            kwargs["ExpressionAttributeNames"] = attr_names

        response = table.update_item(**kwargs)
        attrs = response.get("Attributes", {})
        old_amount = decimal_to_float(attrs.get("Amount"))
        return {
            "old_company": attrs.get("Company"),
            "old_amount": old_amount,
            "old_transaction_type": attrs.get("TransactionType"),
            "old_category": attrs.get("Category"),
        }

    def get_item(self, forwarded_to: str, date_file_name: str) -> "TransactionItem | None":
        """Fetch a single transaction by its composite key."""
        table = self.dyn_resource.Table("Transactions")
        response = table.get_item(Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name})
        # boto3 boundary: the raw item is the stored TransactionItem shape.
        return cast("TransactionItem | None", response.get("Item"))

    def update_context(self, forwarded_to: str, date_file_name: str, context: dict[str, Any]) -> None:
        """Store enrichment context on a transaction. Fails silently (fail-open)."""
        try:
            table = self.dyn_resource.Table("Transactions")
            # Convert Python types to DynamoDB-compatible types
            dynamo_ctx = {}
            for k, v in context.items():
                if isinstance(v, bool):
                    dynamo_ctx[k] = v
                elif isinstance(v, (int, float)):
                    dynamo_ctx[k] = Decimal(str(v))
                else:
                    dynamo_ctx[k] = v
            table.update_item(
                Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
                UpdateExpression="SET TransactionContext = :ctx",
                ExpressionAttributeValues={":ctx": dynamo_ctx},
            )
        except Exception:
            logger.exception("Failed to update transaction context — continuing")

    def set_ignored(self, forwarded_to: str, date_file_name: str, ignored: bool) -> bool | None:
        """Set or clear the Ignored flag on a transaction.

        Returns the previous Ignored value (or None if not previously set).
        """
        table = self.dyn_resource.Table("Transactions")
        response = table.update_item(
            Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
            UpdateExpression="SET Ignored = :val",
            ExpressionAttributeValues={":val": ignored},
            ReturnValues="UPDATED_OLD",
        )
        # Narrow the boto3 scalar-value union to this attribute's actual type.
        return cast("bool | None", response.get("Attributes", {}).get("Ignored"))

    def set_deleted(self, forwarded_to: str, date_file_name: str, deleted: bool) -> bool | str | None:
        """Set or clear the DeletedAt timestamp on a transaction.

        Returns the previous DeletedAt value (or None if not previously set).
        """
        table = self.dyn_resource.Table("Transactions")
        if deleted:
            now = datetime.now(UTC).isoformat()
            response = table.update_item(
                Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
                UpdateExpression="SET DeletedAt = :val",
                ExpressionAttributeValues={":val": now},
                ReturnValues="UPDATED_OLD",
            )
        else:
            response = table.update_item(
                Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
                UpdateExpression="REMOVE DeletedAt",
                ReturnValues="UPDATED_OLD",
            )
        # Narrow the boto3 scalar-value union to this attribute's actual type.
        return cast("bool | str | None", response.get("Attributes", {}).get("DeletedAt"))

    def permanently_delete(self, forwarded_to: str, date_file_name: str) -> "TransactionItem | None":
        """Permanently delete a transaction from DynamoDB.

        Returns the deleted item, or None if not found.
        """
        table = self.dyn_resource.Table("Transactions")
        response = table.delete_item(
            Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
            ReturnValues="ALL_OLD",
        )
        # boto3 boundary: ALL_OLD returns the deleted item in its stored shape.
        return cast("TransactionItem | None", response.get("Attributes"))

    def set_comment(self, forwarded_to: str, date_file_name: str, comment: str | None) -> str | None:
        """Set or clear a comment on a transaction.

        Returns the previous Comment value (or None if not previously set).
        """
        table = self.dyn_resource.Table("Transactions")
        # "Comment" is a DynamoDB reserved word — must use ExpressionAttributeNames
        if comment:
            response = table.update_item(
                Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
                UpdateExpression="SET #C = :val",
                ExpressionAttributeNames={"#C": "Comment"},
                ExpressionAttributeValues={":val": comment},
                ReturnValues="UPDATED_OLD",
            )
        else:
            response = table.update_item(
                Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name},
                UpdateExpression="REMOVE #C",
                ExpressionAttributeNames={"#C": "Comment"},
                ReturnValues="UPDATED_OLD",
            )
        # Narrow the boto3 scalar-value union to this attribute's actual type.
        return cast("str | None", response.get("Attributes", {}).get("Comment"))

    def scan_by_category(self, category: str) -> "list[TransactionItem]":
        """Scan all partitions for transactions with the given category.

        Returns list of {ForwardedTo, DateFileName} keys only.
        """
        from src.finance.user_mapping import get_forwarded_to_addresses

        table = self.dyn_resource.Table("Transactions")
        results: list[dict[str, Any]] = []
        for addr in get_forwarded_to_addresses():
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("ForwardedTo").eq(addr),
                "FilterExpression": Attr("Category").eq(category.lower()) & Attr("DeletedAt").not_exists(),
                "ProjectionExpression": "ForwardedTo, DateFileName",
            }
            while True:
                response = table.query(**kwargs)
                results.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                kwargs["ExclusiveStartKey"] = last_key
        # boto3 boundary: projected {ForwardedTo, DateFileName} rows.
        return cast("list[TransactionItem]", results)

    def count_by_category(self, category: str) -> int:
        """Count non-deleted transactions with the given category."""
        return len(self.scan_by_category(category))

    def scan_all_transactions(self) -> "list[TransactionItem]":
        """Return every row in the Transactions table. Used by the full-data backup.

        Scans the whole table in pages; memory-bounded by the dataset size
        (single-user backups are typically a few thousand rows).
        """
        table = self.dyn_resource.Table("Transactions")
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {}
        while True:
            response = table.scan(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        items.sort(key=lambda x: x.get("DateFileName") or "")
        # boto3 boundary: full-table rows in their stored shape.
        return cast("list[TransactionItem]", items)

    def get_latest_date_file_name(self, year_month: str | None = None) -> str | None:
        """Return the largest DateFileName across all partitions, optionally scoped to a month.

        For each ForwardedTo partition, issues one query with ScanIndexForward=False
        and Limit=1 (optionally with a begins_with prefix) — returns the maximum
        DateFileName observed. Intended for the frontend freshness probe; each
        partition query is O(1) DynamoDB reads.
        """
        from src.finance.user_mapping import get_forwarded_to_addresses

        table = self.dyn_resource.Table("Transactions")
        prefix = year_month.replace("-", ".") if year_month else None

        latest: str | None = None
        for addr in get_forwarded_to_addresses():
            key_cond = Key("ForwardedTo").eq(addr)
            if prefix:
                key_cond = key_cond & Key("DateFileName").begins_with(prefix)
            response = table.query(
                KeyConditionExpression=key_cond,
                ScanIndexForward=False,
                Limit=1,
                ProjectionExpression="DateFileName",
            )
            items = response.get("Items", [])
            if not items:
                continue
            # DateFileName is a String sort key; narrow the boto3 scalar union.
            dfn = cast("str | None", items[0].get("DateFileName"))
            if dfn and (latest is None or dfn > latest):
                latest = dfn
        return latest

    def get_recent_audits(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return the most recent rows' category provenance, newest-first.

        One bounded query per ForwardedTo partition (ScanIndexForward=False,
        Limit=`limit`), projecting only the provenance fields, then merge and
        keep the newest `limit` overall. Soft-deleted rows are filtered out.
        Fail-open: a partition that errors is skipped rather than raising.
        """
        from src.finance.user_mapping import get_forwarded_to_addresses

        table = self.dyn_resource.Table("Transactions")
        rows: list[dict[str, Any]] = []
        for addr in get_forwarded_to_addresses():
            try:
                response = table.query(
                    KeyConditionExpression=Key("ForwardedTo").eq(addr),
                    ScanIndexForward=False,
                    Limit=limit,
                    ProjectionExpression="DateFileName, Category, CategoryAudit, DeletedAt",
                )
            except ClientError as e:
                logger.warning("get_recent_audits: query failed for %s: %s", addr, e)
                continue
            rows.extend(item for item in response.get("Items", []) if not item.get("DeletedAt"))
        rows.sort(key=lambda x: x.get("DateFileName") or "", reverse=True)
        return rows[:limit]

    def query_month_partition(self, forwarded_to: str, year_month: str) -> "list[TransactionItem]":
        """Query a single ForwardedTo partition for one YYYY-MM month.

        Returns items with projected fields: Amount, Category, Company,
        TransactionType, DeletedAt, Ignored.
        """
        prefix = year_month.replace("-", ".")
        table = self.dyn_resource.Table("Transactions")
        items = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": (Key("ForwardedTo").eq(forwarded_to) & Key("DateFileName").begins_with(prefix)),
            "ProjectionExpression": (
                "ForwardedTo, DateFileName, Amount, Category, Company, TransactionType, DeletedAt, Ignored"
            ),
        }
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        # boto3 boundary: projected month-partition rows in their stored shape.
        return cast("list[TransactionItem]", items)

    def find_date_file_name_by_hash(self, forwarded_to: str, transaction_hash: str) -> str | None:
        """Look up the DateFileName of a transaction with the given hash. None if absent.

        Paginated for the same reason as `_transaction_exists`: the filter runs
        after the 1MB page limit, so a single-page query misses matches in
        partitions larger than one page.
        """
        try:
            table = self.dyn_resource.Table("Transactions")
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("ForwardedTo").eq(forwarded_to),
                "FilterExpression": Attr("TransactionHash").eq(transaction_hash),
                "ProjectionExpression": "DateFileName",
            }
            while True:
                response = table.query(**kwargs)
                items = response.get("Items", [])
                if items:
                    # DateFileName is a String sort key; narrow the boto3 scalar union.
                    return cast("str", items[0]["DateFileName"])
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    return None
                kwargs["ExclusiveStartKey"] = last_key
        except ClientError:
            logger.exception("Hash lookup failed")
            raise

    def _insert_imported(
        self,
        row: dict[str, Any],
        category_audit: dict[str, Any] | None,
        occurrence: int = 0,
    ) -> str | None:
        """Force-insert a transaction bypassing the dedup check.

        Used by bulk_add_transactions for imports. When ``occurrence > 0`` the
        stored TransactionHash is bumped (reusing the statement-import pattern)
        so a row with the same identity fields does not collide on the dedup
        index — enabling the "keep_both" import strategy.
        """
        missing = self._validate_required_fields(row, ["forwarded_to", "file_name", "date"])
        if missing:
            logger.error("Imported row missing required field: %s", missing)
            return None

        base_hash = generate_transaction_hash(row)
        stored_hash = bump_hash_occurrence(base_hash, occurrence)

        try:
            table = self.dyn_resource.Table("Transactions")
            date_obj = parse(row["date"], tzinfos=get_tzinfos())
            formatted = date_obj.strftime("%Y.%m.%d_%H.%M")
            file_name_tail = row["file_name"].split("/")[-1]
            if occurrence > 0:
                # Ensure the composite PK is unique when "keep both" fires on a
                # row whose date + file_name already exist.
                file_name_tail = f"{file_name_tail}.occ{occurrence}"
            date_file_name = f"{formatted}_{file_name_tail}"

            item: dict[str, Any] = {
                "ForwardedTo": row["forwarded_to"],
                "DateFileName": date_file_name,
                "FileName": row["file_name"],
                "Date": row["date"],
                "UserId": row.get("user_id"),
                "FromName": row.get("from_name"),
                "FromEmail": (row["from_email"].lower() if row.get("from_email") else None),
                "ToName": row.get("to_name"),
                "ToEmail": (row["to_email"].lower() if row.get("to_email") else None),
                "Institution": row.get("institution"),
                "Subject": row.get("subject"),
                "Body": row.get("body"),
                "Name": row.get("name"),
                "Amount": Decimal(str(row["amount"])) if row.get("amount") is not None else None,
                "Company": row.get("company"),
                "TransactionType": row.get("transaction_type"),
                "Category": self._normalize_category(row),
                "TransactionHash": stored_hash,
            }
            if row.get("statement_source"):
                item["StatementSource"] = row["statement_source"]
            if category_audit is not None:
                item["CategoryAudit"] = {k: to_decimal(v) for k, v in category_audit.items()}
            if row.get("ignored"):
                item["Ignored"] = True
            if row.get("comment"):
                item["Comment"] = row["comment"]
            if row.get("deleted_at"):
                item["DeletedAt"] = row["deleted_at"]

            table.put_item(Item=item)
            return date_file_name
        except ClientError:
            logger.exception("Failed to insert imported transaction")
            raise

    def add_statement_transaction(
        self, txn_data: dict[str, Any], audit_source: str = "statement_import"
    ) -> str | bool | None:
        """Add a transaction from a statement import.

        Required fields: forwarded_to, date, amount, company, institution,
                         transaction_type, category, statement_source
        Optional: name, user_id

        Returns DateFileName if written, False if duplicate, None if validation fails.
        """
        table_name = "Transactions"

        stmt_required = [
            "forwarded_to",
            "date",
            "amount",
            "company",
            "institution",
            "transaction_type",
            "category",
            "statement_source",
        ]
        missing = self._validate_required_fields(txn_data, stmt_required)
        if missing:
            logger.error("Missing required field: %s in statement transaction: %s", missing, txn_data)
            return None

        transaction_hash = self._compute_statement_hash(txn_data)

        try:
            table = self.dyn_resource.Table(table_name)

            if self._transaction_exists(table, txn_data["forwarded_to"], transaction_hash):
                logger.info("Duplicate statement transaction (hash=%s). Skipping.", transaction_hash)
                return False

            date_file_name, synthetic_date = self._synthesize_statement_keys(txn_data, transaction_hash)

            category = self._normalize_category(txn_data)

            item = {
                "ForwardedTo": txn_data["forwarded_to"],
                "DateFileName": date_file_name,
                "Date": synthetic_date,
                "Amount": Decimal(str(txn_data["amount"])),
                "Company": txn_data["company"],
                "Category": category,
                "Institution": txn_data["institution"],
                "TransactionType": txn_data["transaction_type"],
                "TransactionHash": transaction_hash,
                "StatementSource": txn_data["statement_source"],
                "CategoryAudit": self._audit_dynamo_safe(build_audit(audit_source)),
            }

            if txn_data.get("name"):
                item["Name"] = txn_data["name"]
            if txn_data.get("user_id"):
                item["UserId"] = txn_data["user_id"]

            table.put_item(Item=item)
            logger.info("Statement transaction added: %s", date_file_name)
            return date_file_name
        except ClientError:
            logger.exception("Failed to add statement transaction.")
            raise
