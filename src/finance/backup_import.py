"""Import parsing for full-data restore: upload → normalized ParsedUpload.

``parse_upload`` accepts either the backup zip or a plain transactions CSV
(Search-tab export subset) and returns a :class:`ParsedUpload` describing
everything we intend to write. The ParsedConfig/ImportPreviewCounts/ParsedUpload
data model crosses the preview → commit boundary as JSON.

Duplicate classification (``classify_duplicates``) runs against
:meth:`TransactionsDBBase.find_date_file_name_by_hash`, and the actual write
path delegates to :meth:`TransactionsDBBase.bulk_add_transactions` for the
three supported strategies (``skip`` / ``overwrite`` / ``keep_both``).

The MANIFEST_* / TRANSACTIONS_FILENAME constants define the shared backup file
format; ``src.finance.backup_export`` imports them from here for writing.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.finance.app_timezone import TZ_SUFFIX_RE
from src.finance.transaction_hash import generate_transaction_hash

if TYPE_CHECKING:
    from src.finance.protocols import ITransactionsDB

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
TRANSACTIONS_FILENAME = "transactions.csv"

# Plain-CSV imports (from the Search-tab export) have no ForwardedTo column —
# we need a stable fallback so dedup against the current user's partition
# works. Matches the `{user_id}@local` convention used by
# src/api/routers/ingestion.py#add_manual_transaction.
DEFAULT_LOCAL_FORWARDED_TO_SUFFIX = "@local"


# ---------------------------------------------------------------------------
# Parsed-upload data model (crosses the preview → commit boundary as JSON)
# ---------------------------------------------------------------------------


@dataclass
class ParsedConfig:
    """Config blobs extracted from a backup zip. Plain-CSV uploads omit this."""

    categories: list[str] | None = None
    overrides: dict[str, str] | None = None
    merchant_aliases: dict[str, str] | None = None
    budgets: dict[str, Any] | None = None  # {year: {"targets": {...}, "groups": {...}}}


@dataclass
class ImportPreviewCounts:
    total: int
    new: int
    duplicates: int
    invalid: int


@dataclass
class ParsedUpload:
    """The sum total of what we plan to write to the database."""

    filename: str
    source_kind: str  # "backup_zip" | "plain_csv"
    transactions: list[dict[str, Any]] = field(default_factory=list)
    invalid_rows: list[dict[str, Any]] = field(default_factory=list)
    duplicate_hashes: list[str] = field(default_factory=list)  # precomputed for preview
    config: ParsedConfig | None = None

    def counts(self) -> ImportPreviewCounts:
        dup = len(self.duplicate_hashes)
        total = len(self.transactions) + len(self.invalid_rows)
        return ImportPreviewCounts(
            total=total,
            new=len(self.transactions) - dup,
            duplicates=dup,
            invalid=len(self.invalid_rows),
        )


# ---------------------------------------------------------------------------
# Import parsing
# ---------------------------------------------------------------------------


def parse_upload(
    filename: str,
    payload: bytes,
    *,
    default_forwarded_to: str,
) -> ParsedUpload:
    """Parse a user-supplied upload into a normalized ParsedUpload.

    Routes by extension:
      - ``.zip`` → full backup (transactions + optional config).
      - ``.csv`` → plain transactions CSV (Search-export subset).

    ``default_forwarded_to`` is used when a row lacks the ``ForwardedTo``
    column (plain CSVs from the Search tab don't carry it). Anything else
    raises ``ValueError`` — the caller should translate to a 400.
    """
    lower = filename.lower()
    if lower.endswith(".zip"):
        return _parse_zip(filename, payload, default_forwarded_to=default_forwarded_to)
    if lower.endswith(".csv"):
        return _parse_csv_only(filename, payload, default_forwarded_to=default_forwarded_to)
    raise ValueError("Unsupported file type — expected .zip or .csv")


_MAX_MEMBER_DECOMPRESSED_BYTES = 256 * 1024 * 1024  # 256 MiB per member


def _read_member_capped(zf: zipfile.ZipFile, name: str) -> bytes:
    """Read a zip member with a decompressed-size ceiling.

    The declared ``ZipInfo.file_size`` is checked first for a fast reject, but
    crafted zips can lie about it, so the read itself is chunked and aborts the
    moment the running total passes the cap. The upload is capped at 50 MB
    compressed (see ``src/api/routers/data.py``); 256 MiB decompressed gives
    legitimate text backups generous headroom while bounding worst-case memory.
    """
    info = zf.getinfo(name)
    if info.file_size > _MAX_MEMBER_DECOMPRESSED_BYTES:
        raise ValueError(f"Backup member {name} is too large to import.")
    chunks: list[bytes] = []
    total = 0
    with zf.open(name) as fh:
        while chunk := fh.read(1024 * 1024):
            total += len(chunk)
            if total > _MAX_MEMBER_DECOMPRESSED_BYTES:
                raise ValueError(f"Backup member {name} is too large to import.")
            chunks.append(chunk)
    return b"".join(chunks)


def _parse_zip(filename: str, payload: bytes, *, default_forwarded_to: str) -> ParsedUpload:
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as e:
        raise ValueError(f"Not a valid zip file: {e}") from e

    names = set(zf.namelist())
    if TRANSACTIONS_FILENAME not in names:
        raise ValueError(f"Missing {TRANSACTIONS_FILENAME} in backup zip")

    # Manifest validation (accept missing — some hand-edited zips might omit it)
    if MANIFEST_FILENAME in names:
        try:
            manifest = json.loads(_read_member_capped(zf, MANIFEST_FILENAME))
            version = manifest.get("version")
            if version != MANIFEST_VERSION:
                raise ValueError(f"Unsupported backup version: {version}")
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Corrupt manifest.json: {e}") from e

    csv_text = _read_member_capped(zf, TRANSACTIONS_FILENAME).decode("utf-8")
    transactions, invalid = _parse_transactions_csv(csv_text, default_forwarded_to=default_forwarded_to)

    config = ParsedConfig()
    if "config/categories.json" in names:
        try:
            config.categories = json.loads(_read_member_capped(zf, "config/categories.json"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupt config/categories.json: {e}") from e
    if "config/overrides.json" in names:
        try:
            config.overrides = json.loads(_read_member_capped(zf, "config/overrides.json"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupt config/overrides.json: {e}") from e
    if "config/merchant_aliases.json" in names:
        try:
            config.merchant_aliases = json.loads(_read_member_capped(zf, "config/merchant_aliases.json"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupt config/merchant_aliases.json: {e}") from e
    if "config/budgets.json" in names:
        try:
            config.budgets = json.loads(_read_member_capped(zf, "config/budgets.json"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupt config/budgets.json: {e}") from e

    # NOTE: parse_failures.json is intentionally NOT parsed/imported here —
    # parse-failure import is deferred; export-only for now.

    has_any_config = any(
        v is not None for v in (config.categories, config.overrides, config.merchant_aliases, config.budgets)
    )

    return ParsedUpload(
        filename=filename,
        source_kind="backup_zip",
        transactions=transactions,
        invalid_rows=invalid,
        config=config if has_any_config else None,
    )


def _parse_csv_only(filename: str, payload: bytes, *, default_forwarded_to: str) -> ParsedUpload:
    try:
        csv_text = payload.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"CSV must be UTF-8 encoded: {e}") from e
    transactions, invalid = _parse_transactions_csv(csv_text, default_forwarded_to=default_forwarded_to)
    return ParsedUpload(
        filename=filename,
        source_kind="plain_csv",
        transactions=transactions,
        invalid_rows=invalid,
        config=None,
    )


_MONTH_DAY_YEAR_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\b")


def _reattach_configured_tz(date_str: str) -> str:
    """Reattach the configured zone to a tz-less exported date string.

    The export is lossy (`_strip_tz` discards the original token), so the
    best reconstruction is the operator's configured zone — for the default
    Pacific config this stamps " PST"/" PDT" exactly as before. Prefers the
    zone's alphabetic abbreviation, which `get_tzinfos()` registers for
    re-parsing; zones without one (e.g. "+05") get the numeric offset, which
    dateutil parses natively.
    """
    from dateutil.parser import parse as parse_date

    from src.finance.app_timezone import get_app_timezone

    try:
        localized = parse_date(date_str).replace(tzinfo=get_app_timezone())
    except (ValueError, OverflowError):
        return date_str
    token = localized.strftime("%Z")
    if token and not token.startswith(("+", "-")):
        return f"{date_str} {token}"
    return f"{date_str} {localized.strftime('%z')}"


def _parse_transactions_csv(
    csv_text: str, *, default_forwarded_to: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a CSV into (valid normalized rows, invalid rows).

    Accepts both the 10-column Search-tab export and the backup superset.
    Missing round-trip columns are synthesized where possible — otherwise the
    row is classified invalid.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    for idx, raw in enumerate(reader, start=2):  # row 1 is the header
        row, reason = _normalize_row(raw, default_forwarded_to=default_forwarded_to)
        if reason:
            invalid.append({"row_number": idx, "reason": reason, "raw": raw})
            continue
        valid.append(row)
    return valid, invalid


def _normalize_row(raw: dict[str, str], *, default_forwarded_to: str) -> tuple[dict[str, Any], str | None]:
    """Map a CSV dict to an add_transaction-style snake_case dict. Returns
    (row, error_reason). ``error_reason`` is None for valid rows.
    """
    date = (raw.get("Date") or "").strip()
    amount_str = (raw.get("Amount") or "").strip()
    company = (raw.get("Company") or "").strip()

    if not date or not company or not amount_str:
        return {}, "Missing required column (Date, Amount, or Company)"

    try:
        amount = float(amount_str)
    except ValueError:
        return {}, f"Invalid Amount: {amount_str!r}"

    # The Search export strips the alphabetic tz abbreviation (_strip_tz uses
    # TZ_ABBREV_SUFFIX_RE); reattach the configured zone so downstream dateutil
    # parsing + DateFileName formatting behave identically to the ingest path.
    # The old hardcoded " PST" stamp shifted a non-Pacific self-hoster's
    # restored rows by the Pacific offset in anything that converts to the
    # configured zone (month bucketing, latest-transaction age). The guard
    # recognizes ANY stamped zone token (TZ_SUFFIX_RE — all-caps abbreviations
    # and numeric offsets alike), which is broader than what export strips: a
    # numeric-offset token like "+04" is left unstripped on export precisely so
    # it survives here unchanged rather than being re-stamped as "+0400" (see
    # the TZ_ABBREV_SUFFIX_RE comment in app_timezone.py). Either way, a date
    # that already carries a token is never double-stamped, regardless of zone.
    if _MONTH_DAY_YEAR_RE.match(date) and not TZ_SUFFIX_RE.search(date):
        date = _reattach_configured_tz(date)

    row: dict[str, Any] = {
        "forwarded_to": (raw.get("ForwardedTo") or "").strip() or default_forwarded_to,
        "date": date,
        "amount": amount,
        "company": company,
        "category": (raw.get("Category") or "miscellaneous").strip(),
        "institution": (raw.get("Institution") or "").strip(),
        "transaction_type": (raw.get("Type") or "").strip(),
        "name": (raw.get("Name") or "").strip() or None,
    }

    # Optional identity / round-trip columns
    file_name = (raw.get("FileName") or "").strip()
    if file_name:
        row["file_name"] = file_name

    # Email provenance
    for src_col, dst_key in [
        ("Subject", "subject"),
        ("FromName", "from_name"),
        ("FromEmail", "from_email"),
        ("ToName", "to_name"),
        ("ToEmail", "to_email"),
        ("Body", "body"),
        ("Comment", "comment"),
    ]:
        value = (raw.get(src_col) or "").strip()
        if value:
            row[dst_key] = value

    # Ignored / deleted flags
    ignored = (raw.get("Ignored") or "").strip().lower()
    if ignored in ("true", "1", "yes"):
        row["ignored"] = True
    deleted_at = (raw.get("DeletedAt") or "").strip()
    if deleted_at:
        row["deleted_at"] = deleted_at

    # Statement source — prefer pre-serialized JSON in "Statement Source" if
    # present; otherwise rebuild from the expanded columns.
    serialized_stmt = (raw.get("Statement Source") or "").strip()
    if serialized_stmt:
        row["statement_source"] = serialized_stmt
    else:
        stmt_blob = _collect_statement_source(raw)
        if stmt_blob:
            row["statement_source"] = json.dumps(stmt_blob)

    # CategoryAudit round-trip
    audit = _collect_audit(raw)
    if audit:
        row["_category_audit"] = audit

    # Normalize a derived file_name (synthesize from hash) *only* if still empty.
    if not row.get("file_name"):
        row["file_name"] = f"imported_{generate_transaction_hash(row)[:8]}.eml"

    return row, None


def _collect_statement_source(raw: dict[str, str]) -> dict[str, str] | None:
    """Assemble the statement-source dict from expanded backup columns."""
    mapping = {
        "StatementInstitution": "institution",
        "StatementAccountType": "account_type",
        "StatementPeriodStart": "period_start",
        "StatementPeriodEnd": "period_end",
        "StatementPdfPath": "pdf_path",
    }
    collected = {dst: (raw.get(src) or "").strip() for src, dst in mapping.items() if (raw.get(src) or "").strip()}
    return collected or None


def _collect_audit(raw: dict[str, str]) -> dict[str, Any] | None:
    source = (raw.get("CategoryAuditSource") or "").strip()
    reviewed_at = (raw.get("CategoryAuditReviewedAt") or "").strip()
    if not source and not reviewed_at:
        return None
    audit: dict[str, Any] = {}
    if source:
        audit["source"] = source
    if reviewed_at:
        audit["reviewed_at"] = reviewed_at
    rule = (raw.get("CategoryAuditMatchedRule") or "").strip()
    if rule:
        audit["matched_rule"] = rule
    confidence = (raw.get("CategoryAuditConfidence") or "").strip()
    if confidence:
        with contextlib.suppress(ValueError):
            audit["confidence"] = float(confidence)

    # v2 fields — all optional. Legacy 4-column backups simply skip these.
    for column, key in (
        ("CategoryAuditTier", "tier"),
        ("CategoryAuditPreviousCategory", "previous_category"),
        ("CategoryAuditPreviousSource", "previous_source"),
        ("CategoryAuditModel", "model"),
        ("CategoryAuditFallbackReason", "fallback_reason"),
    ):
        value = (raw.get(column) or "").strip()
        if value:
            audit[key] = value

    schema_version = (raw.get("CategoryAuditSchemaVersion") or "").strip()
    if schema_version:
        with contextlib.suppress(ValueError):
            audit["schema_version"] = int(schema_version)

    return audit


# ---------------------------------------------------------------------------
# Duplicate classification for the preview step
# ---------------------------------------------------------------------------


def classify_duplicates(db: ITransactionsDB, transactions: list[dict[str, Any]]) -> list[str]:
    """Return the subset of transaction hashes that already exist in storage.

    Uses ``find_date_file_name_by_hash`` (per-backend) so it works against
    both DynamoDB and SQLite.
    """
    duplicates: list[str] = []
    for row in transactions:
        h = generate_transaction_hash(row)
        # Bulk import and this preview share the same duplicate-detection
        # primitive (part of the ITransactionsDB contract).
        if db.find_date_file_name_by_hash(row["forwarded_to"], h):
            duplicates.append(h)
    return duplicates
