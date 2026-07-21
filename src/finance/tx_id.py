"""Stable URL-safe surrogate id for transactions.

The `transactions` router used to expose the DynamoDB composite key
`{forwarded_to}/{date_file_name}` directly in URL paths across 8
endpoints. That leaks storage internals into agent context — once an
agent caches a URL like
`/api/v1/transactions/forwarded@example.com/2026-04-15-rbc-1234.eml/delete`,
the URL shape becomes load-bearing and any storage rename breaks it.

Solution: a reversible base64url encoding of the composite. The
surrogate is:

- **URL-safe**: only `[A-Za-z0-9_-]`, no slashes or padding.
- **Deterministic**: same composite always yields the same id.
- **Stable across edits**: the composite key never changes (date and
  filename are set at ingest time); category / company / amount edits
  via PUT /fields don't disturb the id.
- **Cheap**: no DB index, no GSI, no migration. Decoding happens at
  the dependency layer — `composite_from_tx_id` is the inverse of
  `tx_id_from_composite`.

The tradeoff documented in the sub-spec
(`docs/specs/01_backend-as-platform/2026-04-30-stable-transaction-ids/`):
the encoding still couples to the storage shape — an agent that
base64-decodes a tx_id can recover the composite. This is fine; the
goal is to *hide* storage internals from URLs, not encrypt them.
Writes pinning the tx_id to a UUID column would buy genuine opacity
but at the cost of a backfill + index. Defer until headless v1
contracts demand it.
"""

from __future__ import annotations

import base64

# Single-byte separator; appears in neither the email-formatted
# `forwarded_to` nor the `YYYY.MM.DD_HH.MM_<file>` `date_file_name`.
_SEP = "|"


def tx_id_from_composite(forwarded_to: str, date_file_name: str) -> str:
    """Encode a (forwarded_to, date_file_name) composite as a URL-safe id."""
    raw = f"{forwarded_to}{_SEP}{date_file_name}".encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def composite_from_tx_id(tx_id: str) -> tuple[str, str]:
    """Decode a tx_id back to (forwarded_to, date_file_name).

    Raises `ValueError` if the input isn't valid base64url, doesn't
    decode to UTF-8, or doesn't contain the separator. Callers should
    surface a 404 when they catch it (an unparseable id is a not-
    found, not a server error).
    """
    pad = "=" * (-len(tx_id) % 4)
    try:
        raw = base64.urlsafe_b64decode(tx_id + pad)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid tx_id: not base64url ({exc})") from exc
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid tx_id: not utf-8 ({exc})") from exc
    forwarded_to, sep, date_file_name = decoded.partition(_SEP)
    if not sep or not forwarded_to or not date_file_name:
        raise ValueError("invalid tx_id: missing separator or empty parts")
    return forwarded_to, date_file_name
