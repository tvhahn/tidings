"""SQLite implementation of MerchantAliasService — mirrors the DynamoDB public API."""

import json
import logging
from pathlib import Path
from typing import Any

from src.finance.demo_clock import app_today
from src.finance.exceptions import VersionConflictError
from src.finance.local_db import (
    CONFIG_INSERT_SQL,
    CONFIG_UPDATE_SQL,
    DEFAULT_DB_PATH,
    ensure_schema,
    get_connection,
)
from src.finance.merchant_alias_service import MerchantAliasServiceBase

logger = logging.getLogger(__name__)


class MerchantAliasServiceLocal(MerchantAliasServiceBase):
    """CRUD for merchant aliases in SQLite."""

    def __init__(self, db_path: Path | None = None, user_id: str = "default"):
        self._db_path = db_path or DEFAULT_DB_PATH
        self.USER_PK = f"USER#{user_id}"
        ensure_schema(self._db_path)

    def _connect(self):
        return get_connection(self._db_path)

    def get_aliases(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM config_store WHERE pk = ? AND sk = ?",
                (self.USER_PK, self.ALIASES_SK),
            ).fetchone()
            if not row:
                return None
            return {
                "Data": json.loads(row["data_json"]),
                "Version": row["version"],
                "UpdatedAt": row["updated_at"],
            }
        finally:
            conn.close()

    def _put_all(self, data: dict[str, Any], expected_version: int | None) -> int:
        new_version = (expected_version or 0) + 1
        now = app_today().isoformat()
        conn = self._connect()
        try:
            data_str = json.dumps(data)
            if expected_version is None:
                conn.execute(
                    CONFIG_INSERT_SQL,
                    (self.USER_PK, self.ALIASES_SK, data_str, new_version, now),
                )
            else:
                cursor = conn.execute(
                    CONFIG_UPDATE_SQL,
                    (data_str, new_version, now, self.USER_PK, self.ALIASES_SK, expected_version),
                )
                if cursor.rowcount == 0:
                    raise VersionConflictError(f"Expected version {expected_version}")
            conn.commit()
            self._write_backup(data)
            return new_version
        finally:
            conn.close()
