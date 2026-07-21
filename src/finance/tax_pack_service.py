"""Tax pack service: bucket a calendar year's spending into claim lines.

Reads the mapping seed (``tax_line_mappings.json`` via ``config_loader``,
personal copy wins) and walks the year's transactions month by month, keeping
spending-type rows and bucketing them by lowercased category — stored rows
carry ``"charitable giving"`` while the seed says ``"Charitable Giving"``, so
matching is case-insensitive by construction.

Membership is derived from category by default, then adjusted by per-transaction
overrides (``TaxOverrideStore``): an ``include`` override forces a row into a
chosen line (marked ``manual``), an ``exclude`` override drops a derived row out
of its line into that line's ``excluded_transactions`` (never counted in totals).
A synthetic ``"other"`` line catches manual includes that don't map to a seed
line; it renders only when populated.

Per-transaction evidence status:

- ``"receipt"`` — a ``receipt``-kind attachment links to the composite
  (bulk-probed via ``AttachmentStore.has_receipt``, one query per pack).
- ``"statement"`` — ``StatementSource`` is present; the row was imported from a
  statement PDF, so no source email exists.
- ``"email"`` — everything else; the source bank email rides on the row.

The service never writes anything, and ``tx_id`` is computed from the composite
at response time only — never persisted. ``cra_ref``/``note`` are informational
strings rendered verbatim; the service never interprets them.
"""

import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from src.finance.config_loader import get_tax_line_mappings
from src.finance.protocols import ISpendingSummary
from src.finance.spending_aggregator import SPENDING_TYPES
from src.finance.tx_id import tx_id_from_composite

logger = logging.getLogger(__name__)

# `_OTHER_KEY` / `_OTHER_LINE` describe the synthetic catch-all line; the tax
# router imports them to render/detect that bucket. The underscore keeps them
# out of the module's general interface (only `TaxPackService` is public).
__all__ = ["_OTHER_KEY", "_OTHER_LINE", "TaxPackService"]

# The 12 month queries fan out across a small thread pool (see ``_build_pack``);
# capped modestly so a shared backend connection isn't stampeded.
_MONTH_QUERY_WORKERS = 6

# Synthetic catch-all line for manual includes that don't map to a seed line.
_OTHER_KEY = "other"
_OTHER_LINE: dict[str, Any] = {
    "key": _OTHER_KEY,
    "label": "Other claimable",
    "cra_ref": None,
    "categories": [],
}


class _HasReceiptProbe(Protocol):
    """The one AttachmentStore capability this service needs (bulk evidence probe)."""

    def has_receipt(self, keys: set[tuple[str, str]]) -> set[tuple[str, str]]: ...


class _HasOverrides(Protocol):
    """The one TaxOverrideStore capability this service needs (bulk override read)."""

    def list_all(self) -> dict[tuple[str, str], dict[str, str | None]]: ...


class TaxPackService:
    """Compose SpendingSummary + AttachmentStore + TaxOverrideStore into a per-year pack."""

    def __init__(
        self,
        spending_summary: ISpendingSummary,
        attachment_store: _HasReceiptProbe,
        tax_override_store: _HasOverrides,
    ):
        self.spending_summary = spending_summary
        self.attachment_store = attachment_store
        self.tax_override_store = tax_override_store

    def get_tax_pack(self, year: int) -> dict[str, Any]:
        """Build the tax pack for one calendar year.

        Returns ``{year, grand_total, lines}`` where each line carries the seed
        strings verbatim plus ``total``, ``transaction_count``,
        ``evidence_counts``, the active ``transactions`` and any
        ``excluded_transactions``.
        """
        pack, _bodies = self._build_pack(year)
        return pack

    def get_tax_pack_with_evidence(self, year: int) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
        """Build the pack plus the email bodies the zip export needs.

        Returns ``(pack, bodies_by_composite)`` where ``pack`` is exactly what
        :meth:`get_tax_pack` returns (never carrying bodies — they must not leak
        into the API response) and ``bodies_by_composite`` maps
        ``(forwarded_to, date_file_name)`` to the raw source-email ``Body`` for
        every active email-evidence row. The pack build already reads full items
        via ``query_month``, so exposing the bodies here spares the export a
        second per-row round-trip to the transactions store (the N+1 it used to
        pay via ``db.get_item``).
        """
        return self._build_pack(year)

    def _build_pack(self, year: int) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
        """Shared pack build; returns ``(pack, bodies_by_composite)``."""
        mapping = get_tax_line_mappings()
        lines: list[dict[str, Any]] = mapping.get("lines", [])

        # Lowercase category → line key, built once per call (the case trap:
        # stored categories are lowercase, the seed is display case).
        line_key_by_category = {
            str(category).lower(): line["key"] for line in lines for category in line.get("categories", [])
        }
        overrides = self.tax_override_store.list_all()

        # Valid override targets: the seed keys plus the synthetic "other" line.
        valid_line_keys = {line["key"] for line in lines} | {_OTHER_KEY}

        # One pass over the year. Each bucket target may hold active members
        # (counted) and excluded members (rendered but never counted). "other"
        # is a valid target only via an include override.
        active_by_line: dict[str, list[tuple[Mapping[str, Any], bool]]] = {key: [] for key in valid_line_keys}
        excluded_by_line: dict[str, list[Mapping[str, Any]]] = {key: [] for key in valid_line_keys}

        # Fan the 12 month reads out concurrently. On DynamoDB each is a network
        # round-trip; running them sequentially made every Tax page load and
        # export pay 12 serial latencies. ``executor.map`` preserves month order
        # so the January→December bucketing pass below stays deterministic.
        #   Thread-safety: SQLite ``query_month`` opens and closes its own
        # connection per call (``get_connection`` → fresh ``sqlite3.connect``),
        # so each worker is isolated. DynamoDB ``query_month`` issues read-only
        # ``Table.query`` calls that delegate to the underlying botocore client
        # (thread-safe) without mutating the shared Table resource, so concurrent
        # reads are safe; workers are capped to keep the fan-out modest.
        months = [f"{year}-{month:02d}" for month in range(1, 13)]
        with ThreadPoolExecutor(max_workers=min(_MONTH_QUERY_WORKERS, len(months))) as executor:
            items_by_month = list(executor.map(self.spending_summary.query_month, months))

        for month_items in items_by_month:
            for item in month_items:
                if item.get("DeletedAt") or item.get("Ignored"):
                    continue
                if item.get("TransactionType") not in SPENDING_TYPES:
                    continue
                if item.get("Amount") is None:
                    continue
                category = str(item.get("Category") or "")
                derived_line = line_key_by_category.get(category.lower())

                forwarded_to = item.get("ForwardedTo")
                date_file_name = item.get("DateFileName")
                key = (forwarded_to, date_file_name) if forwarded_to and date_file_name else None
                ov = overrides.get(key) if key is not None else None

                if ov is not None and ov["mode"] == "exclude":
                    # Excluded: kept only to show under its derived line; dropped
                    # entirely if it had no derived line to be excluded from.
                    if derived_line is not None:
                        excluded_by_line[derived_line].append(item)
                    continue
                if ov is not None and ov["mode"] == "include":
                    line_key = ov["line_key"]
                    target = line_key if line_key is not None and line_key in valid_line_keys else _OTHER_KEY
                    active_by_line[target].append((item, True))
                    continue
                if derived_line is not None:
                    active_by_line[derived_line].append((item, False))
                # else: unmapped and no override — not part of any line.

        # Bulk evidence probe: one has_receipt call for every rendered row
        # (active + excluded), so excluded rows still classify their evidence.
        all_keys = {
            (item["ForwardedTo"], item["DateFileName"])
            for key in valid_line_keys
            for item in ([item for item, _ in active_by_line[key]] + excluded_by_line[key])
            if item.get("ForwardedTo") and item.get("DateFileName")
        }
        receipt_keys = self.attachment_store.has_receipt(all_keys)

        # Render seed lines always; "other" only when it holds ≥1 member.
        render_lines: list[dict[str, Any]] = list(lines)
        if active_by_line[_OTHER_KEY] or excluded_by_line[_OTHER_KEY]:
            render_lines.append(_OTHER_LINE)

        # Email bodies for active email-evidence rows, captured from the items
        # already in memory so the export never re-reads them (see
        # ``get_tax_pack_with_evidence``). Never merged into the API response.
        bodies_by_composite: dict[tuple[str, str], str] = {}

        response_lines: list[dict[str, Any]] = []
        grand_total = 0.0
        for line in render_lines:
            key = line["key"]
            active = sorted(active_by_line[key], key=lambda pair: str(pair[0].get("DateFileName", "")))
            excluded = sorted(excluded_by_line[key], key=lambda r: str(r.get("DateFileName", "")))

            transactions: list[dict[str, Any]] = []
            total = 0.0
            evidence_counts = {"receipt": 0, "email": 0, "statement": 0}
            for item, manual in active:
                txn = _txn_dict(item, receipt_keys, manual)
                evidence_counts[txn["evidence"]] += 1
                total += txn["amount"]
                transactions.append(txn)
                if txn["evidence"] == "email":
                    body = item.get("Body")
                    if body:
                        bodies_by_composite[(item["ForwardedTo"], item["DateFileName"])] = str(body)

            excluded_transactions = [_txn_dict(item, receipt_keys, False) for item in excluded]

            total = round(total, 2)
            grand_total += total
            response_lines.append(
                {
                    "key": key,
                    "label": line["label"],
                    "cra_ref": line["cra_ref"],
                    "note": line.get("note"),
                    "categories": list(line.get("categories", [])),
                    "total": total,
                    "transaction_count": len(transactions),
                    "evidence_counts": evidence_counts,
                    "transactions": transactions,
                    "excluded_transactions": excluded_transactions,
                }
            )

        pack = {"year": year, "grand_total": round(grand_total, 2), "lines": response_lines}
        return pack, bodies_by_composite


def _txn_dict(item: Mapping[str, Any], receipt_keys: set[tuple[str, str]], manual: bool) -> dict[str, Any]:
    """Shape one transaction for the response (active or excluded)."""
    forwarded_to = item["ForwardedTo"]
    date_file_name = item["DateFileName"]
    evidence = _classify_evidence(item, (forwarded_to, date_file_name) in receipt_keys)
    return {
        # Boundary-only surrogate; the composite is never exposed via tx_id.
        "tx_id": tx_id_from_composite(forwarded_to, date_file_name),
        "date": _normalize_date(date_file_name),
        "company": item.get("Company") or "Unknown",
        "amount": float(item["Amount"]),
        "category": item.get("Category") or "",
        "evidence": evidence,
        "forwarded_to": forwarded_to,
        "date_file_name": date_file_name,
        "manual": manual,
    }


def _classify_evidence(item: Mapping[str, Any], has_receipt: bool) -> str:
    """Evidence status: receipt beats statement beats email."""
    if has_receipt:
        return "receipt"
    if item.get("StatementSource"):
        return "statement"
    return "email"


def _normalize_date(date_file_name: str) -> str:
    """``DateFileName[:10]`` (``YYYY.MM.DD``) normalized to ``YYYY-MM-DD``."""
    return date_file_name[:10].replace(".", "-")
