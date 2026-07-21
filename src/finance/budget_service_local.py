"""SQLite implementation of BudgetService — mirrors the DynamoDB public API."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from src.finance.budget_service_base import BudgetServiceBase
from src.finance.decimal_utils import DecimalEncoder
from src.finance.demo_clock import app_today
from src.finance.exceptions import VersionConflictError
from src.finance.local_db import (
    CONFIG_INSERT_SQL,
    CONFIG_UPDATE_SQL,
    DEFAULT_DB_PATH,
    ensure_schema,
    get_connection,
)

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent / "config"


class BudgetServiceLocal(BudgetServiceBase):
    """CRUD operations for budget configuration in SQLite."""

    def __init__(self, db_path: Path | None = None, user_id: str = "default"):
        super().__init__()
        self._db_path = db_path or DEFAULT_DB_PATH
        self.USER_PK = f"USER#{user_id}"
        ensure_schema(self._db_path)

    def _connect(self):
        return get_connection(self._db_path)

    def _get_item(self, sk: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM config_store WHERE pk = ? AND sk = ?",
                (self.USER_PK, sk),
            ).fetchone()
            if not row:
                return None
            return {
                "PK": row["pk"],
                "SK": row["sk"],
                "Data": json.loads(row["data_json"]),
                "Version": row["version"],
                "UpdatedAt": row["updated_at"],
            }
        finally:
            conn.close()

    def _put_item(self, sk: str, data: dict[str, Any], expected_version: int | None) -> int:
        new_version = (expected_version or 0) + 1
        now = app_today().isoformat()
        conn = self._connect()
        try:
            data_str = json.dumps(data, cls=DecimalEncoder)
            if expected_version is None:
                try:
                    conn.execute(
                        CONFIG_INSERT_SQL,
                        (self.USER_PK, sk, data_str, new_version, now),
                    )
                except sqlite3.IntegrityError as e:
                    raise VersionConflictError("Item already exists") from e
            else:
                cursor = conn.execute(
                    CONFIG_UPDATE_SQL,
                    (data_str, new_version, now, self.USER_PK, sk, expected_version),
                )
                if cursor.rowcount == 0:
                    raise VersionConflictError(f"Expected version {expected_version}")
            conn.commit()
            return new_version
        finally:
            conn.close()

    def get_targets(self, year: int) -> dict[str, Any] | None:
        return self._get_item(f"BUDGET#targets#{year}")

    def get_groups(self, year: int) -> dict[str, Any] | None:
        return self._get_item(f"BUDGET#groups#{year}")

    def _store_targets(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        return self._put_item(f"BUDGET#targets#{year}", data, expected_version)

    def _store_groups(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        return self._put_item(f"BUDGET#groups#{year}", data, expected_version)
