"""Shared constants and state-file I/O for the S3 backup feature.

Single small seam imported by both the verification/status API layer and the
backup engine/scheduler so neither owns the other. The scheduler is the only
writer of the state file; the status endpoint only reads it.

State timestamps are ISO-8601 UTC strings — this is operational metadata, not
financial data, so the app timezone rules do not apply.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_STATE_PATH = Path("data/s3_backup_state.json")

# S3 sub-prefixes the backup manages. Reconcile deletions must never touch
# keys outside these two namespaces (plus the manifest).
ATTACHMENTS_S3_PREFIX = "attachments/"
STATEMENTS_S3_PREFIX = "statements/"
MANIFEST_KEY = "manifest.json"

_DEFAULT_STATE: dict[str, Any] = {
    "last_attempt_at": None,
    "last_success_at": None,
    "last_error": None,
    "consecutive_failures": 0,
    "uploaded_count": 0,
    "deleted_count": 0,
    "objects_total": 0,
}


def normalize_prefix(prefix: str | None) -> str:
    """Collapse a user-supplied key prefix to `""` or `"segment/"` form."""
    cleaned = (prefix or "").strip().strip("/")
    return f"{cleaned}/" if cleaned else ""


def default_state() -> dict[str, Any]:
    return dict(_DEFAULT_STATE)


def read_state(path: Path | None = None) -> dict[str, Any]:
    """Read the state file, tolerating absence or corruption (returns defaults)."""
    target = path if path is not None else DEFAULT_STATE_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    state = default_state()
    if isinstance(raw, dict):
        for key in state:
            if key in raw:
                state[key] = raw[key]
    return state


def write_state(state: dict[str, Any], path: Path | None = None) -> None:
    """Atomically replace the state file (tmp file + rename in the same dir)."""
    target = path if path is not None else DEFAULT_STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".s3_backup_state_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
        os.replace(tmp_name, target)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
