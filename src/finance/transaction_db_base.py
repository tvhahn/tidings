"""Abstract base class for TransactionsDB — defines the public contract.

Both TransactionsDB (DynamoDB) and TransactionsDBLocal (SQLite) implement
this interface. Adding a method here enforces it on all backends at import
time; a missing implementation raises TypeError when the class is instantiated.
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from src.finance.app_timezone import get_app_timezone
from src.finance.transaction_hash import bump_hash_occurrence, generate_transaction_hash

if TYPE_CHECKING:
    from src.finance.protocols import TransactionItem

logger = logging.getLogger(__name__)

ImportStrategy = Literal["skip", "overwrite", "keep_both"]


class TransactionsDBBase(ABC):
    """Storage-agnostic contract for transaction persistence."""

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    @abstractmethod
    def add_transaction(self, transaction_data: dict[str, Any]) -> str | bool | None:
        """Add a new transaction.

        Returns DateFileName if written, False if duplicate, None if invalid.
        """

    @abstractmethod
    def add_statement_transaction(
        self, txn_data: dict[str, Any], audit_source: str = "statement_import"
    ) -> str | bool | None:
        """Add a statement-imported transaction.

        Returns DateFileName if written, False if duplicate, None if invalid.
        """

    # ------------------------------------------------------------------
    # Update operations
    # ------------------------------------------------------------------

    @abstractmethod
    def update_category(
        self, forwarded_to: str, date_file_name: str, new_category: str, source: str = "manual"
    ) -> str | None:
        """Update category and write audit metadata. Returns old category or None."""

    @abstractmethod
    def mark_category_reviewed(self, forwarded_to: str, date_file_name: str, source: str = "audit") -> None:
        """Mark category as reviewed without changing it."""

    @abstractmethod
    def enrich_transaction(
        self,
        forwarded_to: str,
        date_file_name: str,
        new_company: str,
        new_category: str,
        source: str = "statement_enrich",
        statement_source: str | None = None,
    ) -> dict[str, Any] | None:
        """Enrich transaction from statement data. Returns old values dict or None.

        Company (and StatementSource, when given) always update. The category
        is preserved — Category and CategoryAudit left untouched — when the
        existing row was manually categorized or when the incoming category is
        the ``miscellaneous`` fallback and the existing one is real (see
        ``_resolve_enrich_category``). The returned dict carries
        ``category_preserved`` to signal which path ran.
        """

    @abstractmethod
    def update_fields(
        self,
        forwarded_to: str,
        date_file_name: str,
        fields: dict[str, Any],
        category: str | None = None,
    ) -> dict[str, Any] | None:
        """Update transaction fields dynamically. Returns old values dict or None."""

    @abstractmethod
    def update_context(self, forwarded_to: str, date_file_name: str, context: dict[str, Any]) -> None:
        """Store enrichment context. Fails silently on error."""

    @abstractmethod
    def set_ignored(self, forwarded_to: str, date_file_name: str, ignored: bool) -> bool | None:
        """Set or clear the Ignored flag. Returns previous value."""

    @abstractmethod
    def set_deleted(self, forwarded_to: str, date_file_name: str, deleted: bool) -> bool | str | None:
        """Set or clear the DeletedAt timestamp. Returns previous value."""

    @abstractmethod
    def permanently_delete(self, forwarded_to: str, date_file_name: str) -> "TransactionItem | None":
        """Permanently delete a transaction. Returns deleted item or None."""

    @abstractmethod
    def set_comment(self, forwarded_to: str, date_file_name: str, comment: str | None) -> str | None:
        """Set or clear a comment. Returns previous value."""

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    @abstractmethod
    def get_item(self, forwarded_to: str, date_file_name: str) -> "TransactionItem | None":
        """Fetch a single transaction by composite key. Returns dict or None."""

    @abstractmethod
    def scan_by_category(self, category: str) -> "list[TransactionItem]":
        """Return list of {ForwardedTo, DateFileName} for all matching transactions."""

    @abstractmethod
    def count_by_category(self, category: str) -> int:
        """Count non-deleted transactions with the given category."""

    @abstractmethod
    def query_month_partition(self, forwarded_to: str, year_month: str) -> "list[TransactionItem]":
        """Return transactions for one user/month as PascalCase dicts.

        year_month format: "YYYY-MM" (e.g. "2026-04"). Internally converts to
        the "YYYY.MM" prefix used in date_file_name / DateFileName sort keys.

        Items must have keys: Amount (Decimal), Category, Company,
        TransactionType, DeletedAt, Ignored — the same shape produced by
        row_to_item() and returned by DynamoDB ProjectionExpression.
        """

    @abstractmethod
    def scan_all_transactions(self) -> "list[TransactionItem]":
        """Return every row in the table as a PascalCase dict.

        Used exclusively by the full-data backup export. Callers should not
        use this for interactive queries — on DynamoDB it issues a full scan.
        """

    @abstractmethod
    def get_latest_date_file_name(self, year_month: str | None = None) -> str | None:
        """Return the largest DateFileName value, optionally restricted to a month.

        Used by the frontend freshness probe: a cheap "has anything changed?"
        signal. Callers compare the returned string against the last seen value
        — DateFileName sorts lexicographically by time ("YYYY.MM.DD_HH.MM_..."),
        so a larger value means at least one newer row exists.

        Returns None when the table (or partition) has no matching rows.
        """

    @abstractmethod
    def get_recent_audits(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return the ``limit`` most recent rows projected to category provenance.

        Each item carries at least ``CategoryAudit`` (and ``Category``) — the
        same shape produced by row_to_item() / a DynamoDB ProjectionExpression.
        Cheap, bounded, and newest-first: powers the /health probe's
        AI-categorization signal without scanning the table. Excludes
        soft-deleted rows. Returns ``[]`` when there are no rows.
        """

    # ------------------------------------------------------------------
    # Shared business logic
    # ------------------------------------------------------------------

    def batch_update_category(
        self, items: list[dict[str, Any]], new_category: str, source: str = "category_rename"
    ) -> int:
        """Bulk update category for a list of {ForwardedTo, DateFileName} items.

        Delegates to update_category() — works for any storage backend.
        Returns the number of items updated.
        """
        count = 0
        for item in items:
            self.update_category(item["ForwardedTo"], item["DateFileName"], new_category, source=source)
            count += 1
        return count

    def bulk_add_transactions(
        self,
        rows: list[dict[str, Any]],
        strategy: ImportStrategy = "skip",
    ) -> dict[str, int]:
        """Import a batch of transactions with duplicate handling.

        Each row is a snake_case dict shaped like ``add_transaction``'s input.
        An optional ``_category_audit`` key carries round-trip CategoryAudit
        metadata to preserve on insert; ``comment``, ``ignored``, and
        ``deleted_at`` are set when present.

        Strategies:

        - ``skip`` — leave existing rows untouched; only insert new rows.
        - ``overwrite`` — when a duplicate (by hash) exists, permanently delete
          the existing row and insert the imported one in its place.
        - ``keep_both`` — insert regardless of existing duplicates by bumping
          the stored hash with an occurrence suffix (reuses the statement
          import pattern), producing a distinct row.

        Returns counts:
        ``{"inserted": N, "updated": N, "skipped": N, "invalid": N, "errors": N}``.

        ``invalid`` counts rows rejected for bad data (missing required fields);
        ``errors`` counts rows that failed on an infrastructure exception (a
        write or dedup lookup raised) — the batch keeps going either way.
        """
        counts = {"inserted": 0, "updated": 0, "skipped": 0, "invalid": 0, "errors": 0}
        for row in rows:
            try:
                # Synthesize a file_name when the source CSV omitted it (plain
                # Search-tab CSV has no ForwardedTo/FileName columns).
                if not row.get("file_name"):
                    h8 = generate_transaction_hash(row)[:8]
                    row["file_name"] = f"imported_{h8}.eml"

                if self._validate_required_fields(row, ["forwarded_to", "file_name", "date"]):
                    counts["invalid"] += 1
                    continue
                if row.get("amount") is None or not row.get("company"):
                    counts["invalid"] += 1
                    continue

                base_hash = generate_transaction_hash(row)
                existing_dfn = self.find_date_file_name_by_hash(row["forwarded_to"], base_hash)
                audit = row.get("_category_audit")

                if existing_dfn:
                    if strategy == "skip":
                        counts["skipped"] += 1
                        continue
                    if strategy == "overwrite":
                        self.permanently_delete(row["forwarded_to"], existing_dfn)
                        # _insert_imported now raises on infrastructure failure,
                        # so a returned value here always means a successful write.
                        self._insert_imported(row, audit, occurrence=0)
                        counts["updated"] += 1
                        continue
                    if strategy == "keep_both":
                        occurrence = 1
                        # Walk up until we find an unused occurrence slot.
                        while self.find_date_file_name_by_hash(
                            row["forwarded_to"], bump_hash_occurrence(base_hash, occurrence)
                        ):
                            occurrence += 1
                        self._insert_imported(row, audit, occurrence=occurrence)
                        counts["inserted"] += 1
                        continue

                self._insert_imported(row, audit, occurrence=0)
                counts["inserted"] += 1
            except Exception:
                logger.exception("Import row failed (infrastructure error, not row data)")
                counts["errors"] += 1

        return counts

    @abstractmethod
    def find_date_file_name_by_hash(self, forwarded_to: str, transaction_hash: str) -> str | None:
        """Return DateFileName of a row with the given TransactionHash, or None."""

    @abstractmethod
    def _insert_imported(
        self,
        row: dict[str, Any],
        category_audit: dict[str, Any] | None,
        occurrence: int = 0,
    ) -> str | None:
        """Force-insert a row without the dedup check. Used by bulk_add_transactions."""

    @staticmethod
    def _validate_required_fields(data: dict[str, Any], fields: list[str]) -> str | None:
        """Return the first missing field name, or None if all present."""
        for field in fields:
            if data.get(field) is None:
                return field
        return None

    @staticmethod
    def _normalize_category(data: dict[str, Any]) -> str:
        """Extract and normalize category from transaction data."""
        return (data.get("category") or "miscellaneous").lower()

    @staticmethod
    def _resolve_enrich_category(
        existing_category: str | None,
        existing_source: str | None,
        incoming_category: str,
        incoming_source: str,
    ) -> bool:
        """Return True when the existing category must be preserved (not overwritten).

        Precedence: a fresh explicit user edit in the import preview always
        wins; otherwise manual categorization survives statement enrichment,
        and a ``miscellaneous`` fallback never overwrites real information.
        """
        from src.finance.category_audit import MANUAL_SOURCES

        if incoming_source in MANUAL_SOURCES:
            return False
        if not existing_category:
            return False
        if existing_category.lower() == incoming_category.lower():
            return False
        if existing_source in MANUAL_SOURCES:
            return True
        # The statement-side default must never overwrite real information —
        # this also protects rows with no audit at all.
        return incoming_category.lower() == "miscellaneous"

    @staticmethod
    def _resolve_ignored(transaction_data: dict[str, Any]) -> bool:
        """Decide whether a NEW transaction should arrive Ignored.

        True when the row carries an explicit ``ignored`` flag (e.g. a caller
        that already decided) OR its Company matches a merchant auto-ignore
        rule via the shared tiered resolver — the write-time parallel to how
        category overrides pin a merchant to a category. Applied by both
        backends inside ``add_transaction`` so the self-hosted (process_message)
        and Lambda write paths behave identically. Manual ignores via
        ``set_ignored`` are unaffected. Fail-open: any lookup error leaves the
        row un-ignored rather than blocking the write.
        """
        if transaction_data.get("ignored"):
            return True
        company = transaction_data.get("company")
        if not company:
            return False
        try:
            from src.finance.category_resolver import resolve_ignore
            from src.finance.config_loader import get_ignore_context

            patterns, aliases = get_ignore_context()
            if not patterns:
                return False
            return resolve_ignore(company, patterns, aliases=aliases) is not None
        except Exception:
            logger.debug("ignore-rule lookup failed; leaving transaction un-ignored", exc_info=True)
            return False

    @staticmethod
    def _compute_statement_hash(txn_data: dict[str, Any]) -> str:
        """Compute the transaction hash for a statement import, with occurrence disambiguation.

        Uses raw_description (if present) for hash stability. When occurrence > 0,
        appends a counter suffix and re-hashes to produce a distinct hash.
        """
        hash_data = {
            "forwarded_to": txn_data["forwarded_to"],
            "institution": txn_data["institution"],
            "amount": txn_data["amount"],
            "company": txn_data.get("raw_description", txn_data["company"]),
            "date": txn_data["date"],
            "transaction_type": txn_data["transaction_type"],
        }
        transaction_hash = generate_transaction_hash(hash_data)

        occurrence = txn_data.get("occurrence", 0)
        if occurrence > 0:
            key = transaction_hash + f"|{occurrence}"
            transaction_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()

        return transaction_hash

    @staticmethod
    def _synthesize_statement_keys(txn_data: dict[str, Any], transaction_hash: str) -> tuple[str, str]:
        """Synthesize DateFileName and Date for a statement-imported transaction.

        Returns (date_file_name, synthetic_date).
        """
        date_parts = txn_data["date"].split("-")  # YYYY-MM-DD
        date_prefix = f"{date_parts[0]}.{date_parts[1]}.{date_parts[2]}"
        hash8 = transaction_hash[:8]
        institution = txn_data["institution"]
        date_file_name = f"{date_prefix}_00.00_stmt_{institution}_{hash8}.pdf"
        local_dt = datetime(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]), 0, 0, tzinfo=get_app_timezone())
        synthetic_date = local_dt.strftime("%m/%d/%Y %H:%M %z")
        return date_file_name, synthetic_date
