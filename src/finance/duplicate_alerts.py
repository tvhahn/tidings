"""Duplicate bank-alert detection — the storage-agnostic half of issue #86.

Two ways one purchase used to land as two email transactions:

* **Same message, written twice.** One email reaches ingestion twice (two S3
  objects for one message, or the IMAP poller and the Lambda both reading it).
  Both copies hash identically, but each writer's pre-write hash check can run
  before the other's write lands, so both rows are stored.
* **The bank re-sends the alert.** The re-send carries a later ``Date:``
  header. The transaction hash includes that minute, so the copy hashes
  differently and the pre-write check never matches it.

Neither copy is dropped. After every write the storage layer re-reads the
neighbouring rows and this module decides which copies are duplicates; those
are stored Ignored with ``DuplicateOf`` naming the row they repeat, so totals
stay right and the existing restore control brings a copy back when two
identical purchases really did happen.

Decision rules (``find_duplicate_marks``):

* **Same hash** — rows sharing a ``TransactionHash`` are one email. The lowest
  ``DateFileName`` is the original and every other copy is marked, including a
  row another writer stored moments earlier: whichever writer reads last sees
  both rows, so a race always resolves.
* **Same alert text** — a row whose fingerprint (normalized body plus the parsed
  fields) matches an earlier row within ``RESEND_WINDOW`` is a re-send. Only
  the newly written row is ever marked by this rule, so an earlier copy the
  user restored is never re-hidden.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "RESEND_WINDOW",
    "AlertRow",
    "alert_fingerprint",
    "alert_row",
    "find_duplicate_marks",
    "window_bounds",
]

# Alert bodies carry no date or time, so the same purchase repeated on another
# day (a daily coffee) produces identical text. Measured over 2.5 years of real
# alerts, re-sends cluster within 4 hours of the original, nothing at all falls
# between 4 and 12 hours, and repeat purchases start at 12 hours. Six hours
# sits in that gap: a genuine identical purchase inside it is stored Ignored
# and can be restored, never lost.
RESEND_WINDOW = timedelta(hours=6)

# DateFileName starts with the alert minute: "YYYY.MM.DD_HH.MM_<file>".
_KEY_MINUTE_FORMAT = "%Y.%m.%d_%H.%M"
_KEY_MINUTE_LENGTH = 16


@dataclass(frozen=True)
class AlertRow:
    """The fields duplicate detection reads from one stored transaction."""

    date_file_name: str
    transaction_hash: str | None
    fingerprint: str | None
    deleted: bool
    duplicate_of: str | None


def alert_fingerprint(item: Mapping[str, Any]) -> str | None:
    """Identify an alert by its text and parsed fields, ignoring when it was sent.

    ``item`` is a PascalCase transaction item. Whitespace in the body is
    collapsed so line-wrapping differences between delivery paths don't split
    one alert in two. Returns ``None`` for rows with no body (statement imports,
    manual entries) — they never take part in re-send detection.
    """
    body = item.get("Body")
    if not body:
        return None
    amount = item.get("Amount")
    fields = [
        " ".join(str(body).split()),
        str(item.get("Institution") or ""),
        f"{float(amount):.2f}" if amount is not None else "",
        str(item.get("Company") or ""),
        str(item.get("TransactionType") or ""),
    ]
    return hashlib.sha256("\x1f".join(fields).encode("utf-8")).hexdigest()


def alert_row(item: Mapping[str, Any]) -> AlertRow:
    """Project a PascalCase transaction item onto the fields detection needs."""
    return AlertRow(
        date_file_name=str(item["DateFileName"]),
        transaction_hash=item.get("TransactionHash") or None,
        fingerprint=None if item.get("StatementSource") else alert_fingerprint(item),
        deleted=bool(item.get("DeletedAt")),
        duplicate_of=item.get("DuplicateOf") or None,
    )


def window_bounds(date_file_name: str) -> tuple[str, str] | None:
    """``DateFileName`` range holding every row detection may compare against.

    From ``RESEND_WINDOW`` before the row's minute through the end of that
    minute. ``None`` when the key doesn't start with a minute stamp.
    """
    minute = _key_minute(date_file_name)
    if minute is None:
        return None
    low = (minute - RESEND_WINDOW).strftime(_KEY_MINUTE_FORMAT)
    # "~" sorts after every character a DateFileName tail uses after the minute.
    return low, f"{date_file_name[:_KEY_MINUTE_LENGTH]}~"


def find_duplicate_marks(new_key: str, rows: Sequence[AlertRow]) -> dict[str, str]:
    """Decide which rows to mark after ``new_key`` was written.

    ``rows`` must include the new row plus every stored row of the same
    partition inside ``window_bounds(new_key)``. Returns
    ``{duplicate DateFileName: original DateFileName}``; empty when nothing is
    a duplicate. Deleted rows are never an original nor marked.
    """
    live = {row.date_file_name: row for row in rows if not row.deleted}
    new = live.get(new_key)
    if new is None:
        return {}

    marks: dict[str, str] = {}

    if new.transaction_hash:
        same_hash = sorted(
            (row for row in live.values() if row.transaction_hash == new.transaction_hash),
            key=lambda row: row.date_file_name,
        )
        original = same_hash[0]
        root = original.duplicate_of or original.date_file_name
        for row in same_hash[1:]:
            if row.duplicate_of is None:
                marks[row.date_file_name] = root
        if new_key in marks or new.duplicate_of is not None:
            return marks

    if new.fingerprint:
        new_minute = _key_minute(new_key)
        for row in sorted(live.values(), key=lambda r: r.date_file_name):
            if row.date_file_name >= new_key:
                break
            if row.fingerprint != new.fingerprint:
                continue
            row_minute = _key_minute(row.date_file_name)
            if new_minute is None or row_minute is None or new_minute - row_minute > RESEND_WINDOW:
                continue
            marks[new_key] = row.duplicate_of or row.date_file_name
            break

    return marks


def _key_minute(date_file_name: str) -> datetime | None:
    try:
        # Key minutes are local wall-clock stamps, only ever subtracted from each other.
        return datetime.strptime(date_file_name[:_KEY_MINUTE_LENGTH], _KEY_MINUTE_FORMAT)  # noqa: DTZ007
    except ValueError:
        return None
