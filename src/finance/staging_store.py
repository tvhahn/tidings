"""Staging store: token lifecycle for the import preview → commit flow.

``stage`` persists a parsed upload under ``data/.imports/{token}.json`` with a
15-minute TTL; ``load`` and ``delete`` round-trip the token used by the
preview→commit flow. Expired stages are purged lazily each time ``stage`` runs.

``_STAGE_DIR`` / ``_STAGE_TTL_SECONDS`` are module attributes read at call time
so tests can monkeypatch ``staging_store._STAGE_DIR`` / ``_STAGE_TTL_SECONDS``.

``now_iso`` lives here (its TTL bookkeeping is the stronger owner) and is
imported by ``src.finance.backup_export``.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from src.finance.backup_import import ParsedConfig, ParsedUpload

logger = logging.getLogger(__name__)

_STAGE_DIR = Path("data/.imports")
_STAGE_TTL_SECONDS = 15 * 60


def stage(parsed: ParsedUpload) -> str:
    """Persist a ParsedUpload to disk under a UUID token. Returns the token.

    Expired stages (older than 15 min) are removed lazily on each call.
    """
    _purge_expired()
    _STAGE_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    path = _STAGE_DIR / f"{token}.json"
    data = {
        "filename": parsed.filename,
        "source_kind": parsed.source_kind,
        "transactions": parsed.transactions,
        "invalid_rows": parsed.invalid_rows,
        "duplicate_hashes": parsed.duplicate_hashes,
        "config": asdict(parsed.config) if parsed.config else None,
    }
    path.write_text(json.dumps(data))
    return token


def load(token: str) -> ParsedUpload | None:
    """Load a staged upload by token, or None if missing/expired."""
    if not _valid_token(token):
        return None
    path = _STAGE_DIR / f"{token}.json"
    if not path.exists():
        return None
    if _age_seconds(path) > _STAGE_TTL_SECONDS:
        path.unlink(missing_ok=True)
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("Corrupt staged import file: %s", path)
        return None
    config_dict = data.get("config")
    return ParsedUpload(
        filename=data.get("filename", ""),
        source_kind=data.get("source_kind", "backup_zip"),
        transactions=data.get("transactions", []),
        invalid_rows=data.get("invalid_rows", []),
        duplicate_hashes=data.get("duplicate_hashes", []),
        config=ParsedConfig(**config_dict) if config_dict else None,
    )


def delete(token: str) -> None:
    if not _valid_token(token):
        return
    path = _STAGE_DIR / f"{token}.json"
    path.unlink(missing_ok=True)


_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def _valid_token(token: str) -> bool:
    return bool(_TOKEN_RE.match(token))


def _age_seconds(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def _purge_expired() -> None:
    if not _STAGE_DIR.exists():
        return
    now = time.time()
    for entry in _STAGE_DIR.glob("*.json"):
        try:
            if now - entry.stat().st_mtime > _STAGE_TTL_SECONDS:
                entry.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


def now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
