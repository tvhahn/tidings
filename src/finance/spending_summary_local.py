"""SQLite implementation of SpendingSummary — mirrors the DynamoDB public API."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from src.finance.local_db import DEFAULT_DB_PATH, ensure_schema, get_connection, row_to_item
from src.finance.spending_summary_base import SpendingSummaryBase

if TYPE_CHECKING:
    from src.finance.protocols import TransactionItem

logger = logging.getLogger(__name__)

# GLOB (case-sensitive) lets SQLite turn the month prefix into an index range on
# idx_transactions_date_file_name; LIKE is case-insensitive and forces a full SCAN.
# The prefix is 'YYYY.MM' — digits and a dot, no GLOB metacharacters.
_QUERY_MONTH_SQL = "SELECT * FROM transactions WHERE date_file_name GLOB ?"


class SpendingSummaryLocal(SpendingSummaryBase):
    """Query and aggregate monthly transaction data from SQLite."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        ensure_schema(self._db_path)

    def query_month(
        self,
        year_month: str,
        projection: str | None = None,
        expression_names: dict[str, str] | None = None,
    ) -> "list[TransactionItem]":
        """Query all transactions for a given YYYY-MM month.

        The projection and expression_names args are accepted for API compatibility
        with the DynamoDB version but are ignored — SQLite always returns all columns.
        """
        prefix = year_month.replace("-", ".")
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(_QUERY_MONTH_SQL, (f"{prefix}*",)).fetchall()
            # sqlite boundary: row_to_item builds the stored PascalCase shape.
            return cast("list[TransactionItem]", [row_to_item(row) for row in rows])
        finally:
            conn.close()

    # aggregate, get_summary, get_summary_with_comparison inherited from SpendingSummaryBase
