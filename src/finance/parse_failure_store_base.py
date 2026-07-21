"""Abstract base class for the parse-failure (dead-letter) store pair.

Both backends —
:class:`~src.finance.parse_failure_store.ParseFailureStore` (DynamoDB) and
:class:`~src.finance.parse_failure_store_local.ParseFailureStoreLocal`
(SQLite) — inherit this ABC, mirroring the pattern used by the transaction,
summary, and budget store pairs. Adding a method here enforces it on both
backends at import time.

The two implementations store into different namespaces (DynamoDB PascalCase
attributes vs SQLite columns), so the row/item field mapping is *not* shared;
only genuinely storage-agnostic post-processing (the ``alert_classifier_result``
coercion) lives here as a concrete helper.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ParseFailureStoreBase(ABC):
    """Storage-agnostic contract for the parse-failure dead-letter store."""

    @staticmethod
    def coerce_classifier(value: Any) -> bool | None:
        """Normalize a stored ``alert_classifier_result`` to ``bool`` (or None).

        Shared by both backends: SQLite persists the flag as an integer 0/1 and
        coerces on read, while DynamoDB coerces to a native bool on write. Both
        paths use the same ``None``-preserving truthiness rule.
        """
        return None if value is None else bool(value)

    @abstractmethod
    def record_failure(self, failure: dict[str, Any]) -> str:
        """Persist (idempotently) a parse failure and return its deterministic id."""

    @abstractmethod
    def get_failure(self, failure_id: str) -> dict[str, Any] | None:
        """Return the full failure row (including ``email_json``) or None."""

    @abstractmethod
    def list_failures(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List failure summaries (no ``email_json``), newest first."""

    @abstractmethod
    def list_failures_full(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List full failure rows (including ``email_json``), newest first.

        Like :meth:`list_failures` but keeps ``email_json`` so a bulk consumer
        can filter and retry in one pass without a per-id re-query.
        """

    @abstractmethod
    def set_status(self, failure_id: str, status: str, recovered_date_file_name: str | None = None) -> bool:
        """Transition a failure to ``status``. Returns True if a row was updated."""

    @abstractmethod
    def count_recent_quarantined(self, days: int = 7) -> int:
        """Count rows still in ``quarantined`` status within the last ``days``."""

    @abstractmethod
    def has_other_recent_failure(self, institution: str, hours: int = 24) -> bool:
        """Whether another quarantined failure for ``institution`` exists in the window."""

    @abstractmethod
    def latest_received_by_institution(self) -> dict[str, str]:
        """Map each detected institution to its most recent ``received_at``.

        Aggregates over *all* rows with a non-null ``detected_institution``
        regardless of status — any arrival (quarantined, recovered, dismissed …)
        is evidence the pipe delivered an email from that institution. The
        coverage service uses this so a burst of parser drift does not read as
        the institution having gone quiet. Returns ``{institution: ISO string}``.
        """
