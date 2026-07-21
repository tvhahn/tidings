"""SQLite cache for embedding vectors.

Embeddings are deterministic for a given text + model, so cached values never
need invalidation. The cache only grows as new company names are encountered.
"""

import logging
import sqlite3
import struct
from datetime import UTC, datetime
from pathlib import Path

from src.finance.local_db import get_connection, run_with_lock_retry

logger = logging.getLogger(__name__)

DB_PATH = Path("data/embeddings.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS embedding_cache (
    text_lower TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    model TEXT NOT NULL DEFAULT 'text-embedding-3-small',
    created_at TEXT NOT NULL
);
"""


def _pack_vector(vector: list[float]) -> bytes:
    """Serialize a float vector to a compact binary blob."""
    return struct.pack(f"{len(vector)}f", *vector)


def _unpack_vector(blob: bytes) -> list[float]:
    """Deserialize a binary blob back to a float vector."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


class EmbeddingCache:
    """SQLite-backed cache for text embedding vectors."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or DB_PATH
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        # Shared connection factory (row_factory, WAL, busy_timeout, foreign_keys).
        # This store's single table declares no FK, so newly-enforced
        # foreign_keys=ON is a no-op; it also gains per-connection WAL.
        return get_connection(self._db_path)

    def _ensure_db(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # Wrap the fresh-file schema setup in the shared lock retry: two
        # processes creating this cache at once race the WAL journal-mode switch,
        # which raises SQLITE_BUSY without honouring busy_timeout. The single
        # CREATE TABLE IF NOT EXISTS is otherwise idempotent, so a plain retry
        # (no BEGIN IMMEDIATE needed) suffices here.
        run_with_lock_retry(self._create_schema_once)

    def _create_schema_once(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def get_many(self, texts: list[str]) -> dict[str, list[float]]:
        """Batch lookup cached embeddings by lowercased text.

        Returns {text_lower: vector} for cache hits only.
        """
        if not texts:
            return {}

        keys = [t.lower() for t in texts]
        result: dict[str, list[float]] = {}
        conn = self._connect()
        try:
            # SQLite has a variable limit (~999), so chunk large batches
            chunk_size = 900
            for i in range(0, len(keys), chunk_size):
                chunk = keys[i : i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT text_lower, embedding FROM embedding_cache WHERE text_lower IN ({placeholders})",  # noqa: S608 — placeholders are ? marks only; values bound positionally
                    chunk,
                ).fetchall()
                for row in rows:
                    result[row["text_lower"]] = _unpack_vector(row["embedding"])
        finally:
            conn.close()

        return result

    def put_many(self, entries: list[tuple[str, list[float]]]) -> None:
        """Batch insert embeddings. Skips duplicates (INSERT OR IGNORE)."""
        if not entries:
            return

        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO embedding_cache (text_lower, embedding, created_at) VALUES (?, ?, ?)",
                [(text.lower(), _pack_vector(vec), now) for text, vec in entries],
            )
            conn.commit()
        finally:
            conn.close()
