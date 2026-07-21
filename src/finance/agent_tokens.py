"""Agent-token records — load/save/rotate/revoke helpers.

Tokens are persisted under `agent_tokens` in `data/config.json` as
`AgentTokenRecord` rows. Raw token strings are NEVER persisted; only the
sha256 hash is stored. The raw string is shown to the operator once at
creation time.

Pure module — no FastAPI imports — also called from the `agent_token`
CLI and from tests. The middleware (lands in Tier 1 Phase 1 alongside
this module) calls `find_token_by_raw` to authenticate inbound requests.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Literal, TypedDict, cast

from src.finance.app_config import AppConfig, get_config, update_config

TokenScope = Literal["read", "read+write"]
TOKEN_PREFIX = "fin_"  # noqa: S105 — token *prefix* literal, not a secret; entropy comes from secrets.token_urlsafe
DEFAULT_SCOPE: TokenScope = "read+write"
_VALID_SCOPES: frozenset[str] = frozenset({"read", "read+write"})


class AgentTokenRecord(TypedDict):
    """Single agent-token row.

    Stored in `data/config.json` under `agent_tokens`. Times are ISO-8601
    UTC strings so the record round-trips through JSON cleanly.
    """

    id: str
    token_hash: str
    scope: str  # one of TokenScope; widened to str for JSON round-trip
    label: str
    created_at: str
    last_used_at: str | None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def hash_token(raw: str) -> str:
    """sha256 of the raw token string. Stable across processes."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_raw_token() -> str:
    """`fin_` + 32 url-safe random bytes — see RFC 6750 token format."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def list_tokens() -> list[AgentTokenRecord]:
    cfg = get_config()
    raw = cfg.get("agent_tokens") or []
    return [cast("AgentTokenRecord", dict(t)) for t in raw]


def _save_tokens(tokens: list[AgentTokenRecord]) -> None:
    update_config(cast("AppConfig", {"agent_tokens": tokens}))


def add_token(*, label: str, scope: TokenScope = DEFAULT_SCOPE) -> tuple[AgentTokenRecord, str]:
    """Generate a fresh token, persist its hash, return (record, raw_token).

    The raw token string is shown to the operator once and never recoverable
    afterwards — only the hash is persisted.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(f"unknown scope: {scope!r}")
    if not label.strip():
        raise ValueError("label must not be empty")
    raw = generate_raw_token()
    record: AgentTokenRecord = {
        "id": secrets.token_hex(8),
        "token_hash": hash_token(raw),
        "scope": scope,
        "label": label.strip(),
        "created_at": _now_iso(),
        "last_used_at": None,
    }
    tokens = list_tokens()
    tokens.append(record)
    _save_tokens(tokens)
    return record, raw


def revoke_token(token_id: str) -> bool:
    """Delete a token by id. Returns True if a row was removed."""
    tokens = list_tokens()
    remaining = [t for t in tokens if t["id"] != token_id]
    if len(remaining) == len(tokens):
        return False
    _save_tokens(remaining)
    return True


def find_token_by_raw(raw: str) -> AgentTokenRecord | None:
    """Constant-time hash match against persisted records."""
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    target = hash_token(raw)
    for t in list_tokens():
        if secrets.compare_digest(t["token_hash"], target):
            return t
    return None


def mark_used(token_id: str) -> None:
    """Stamp `last_used_at` for a token. No-op if the id is unknown."""
    tokens = list_tokens()
    for t in tokens:
        if t["id"] == token_id:
            t["last_used_at"] = _now_iso()
            _save_tokens(tokens)
            return
