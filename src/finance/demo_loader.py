"""Demo data loader — seeds SQLite from data/demo/seed.json.

Dates in the seed are anchored to a fixed month (the most-recent month present
in ``seed.json``). On load, transaction dates are shifted forward by a whole
number of months so the anchor lands on ``target_month`` (default: current
calendar month). This keeps the "this month" dashboard populated for anyone
who opens the app after the seed was last refreshed.

The shift is bypass-able for fixture-generation use: set ``freeze_to_month`` in
the Python API or the ``DEMO_FREEZE_MONTH`` env var (``YYYY-MM``) to pin the
anchor to a specific month. The hosted static demo relies on this to keep
fixtures deterministic (see
``docs/specs/00_open-source-migration/2026-04-16-static-demo-deployment/SPEC.md``,
section 2: "anchored to March 2026").
"""

import calendar
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dateutil.relativedelta import relativedelta

from src.finance.demo_clock import app_today
from src.finance.local_db import ensure_schema, get_connection

logger = logging.getLogger(__name__)

SEED_PATH = Path("data/demo/seed.json")
DEMO_DB_PATH = Path("data/demo.db")
DEMO_STATEMENTS_DB_PATH = Path("data/demo-statements.db")
DEMO_ATTACHMENTS_DB_PATH = Path("data/demo-attachments.db")
DEMO_TAX_OVERRIDES_DB_PATH = Path("data/demo-tax-overrides.db")

# Matches the seed's ``date`` field: "MM/DD/YYYY HH:MM TZ"
_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})\s+(\S+)$")
# Matches the seed's ``date_file_name`` field: "YYYY.MM.DD_HH.MM_demo_<hash>.eml"
_FILENAME_DATE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})_(\d{2}\.\d{2})(_.*)$")

_ENV_FREEZE_MONTH = "DEMO_FREEZE_MONTH"


def _env_freeze_month() -> date | None:
    """Parse ``DEMO_FREEZE_MONTH`` env var (``YYYY-MM``) into a first-of-month date.

    Returns None when unset or malformed (malformed values log a warning).
    """
    raw = os.environ.get(_ENV_FREEZE_MONTH)
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m").date().replace(day=1)  # noqa: DTZ007 — YYYY-MM env var, immediately reduced to .date()
    except ValueError:
        logger.warning("Ignoring malformed %s=%r (expected YYYY-MM)", _ENV_FREEZE_MONTH, raw)
        return None


def _compute_month_offset(seed_anchor_month: date, target_month: date) -> relativedelta:
    """Whole-month offset from seed anchor to target month.

    Both inputs should be first-of-month dates. Only the year/month difference
    matters; the day component is ignored.
    """
    months = (target_month.year - seed_anchor_month.year) * 12 + (target_month.month - seed_anchor_month.month)
    return relativedelta(months=months)


def _seed_anchor_month(transactions: list[dict[str, Any]]) -> date | None:
    """Most-recent month present across seed transactions, as a first-of-month date."""
    anchors: list[date] = []
    for txn in transactions:
        m = _DATE_RE.match(txn.get("date", ""))
        if not m:
            continue
        mm, _dd, yyyy, _hhmm, _tz = m.groups()
        anchors.append(date(int(yyyy), int(mm), 1))
    if not anchors:
        return None
    return max(anchors)


def _clamp_day(year: int, month: int, day: int) -> int:
    """Clamp ``day`` to the last valid day of ``(year, month)``."""
    last = calendar.monthrange(year, month)[1]
    return min(day, last)


def _shift_date_field(value: str, offset: relativedelta) -> str:
    """Shift a ``MM/DD/YYYY HH:MM TZ`` string by ``offset`` months.

    Day is clamped to the target month's last day (e.g. Jan 31 + 1 month → Feb 28/29).
    Time and timezone token are preserved verbatim.
    """
    m = _DATE_RE.match(value)
    if not m:
        return value
    mm, dd, yyyy, hhmm, tz = m.groups()
    shifted_month_first = date(int(yyyy), int(mm), 1) + offset
    clamped_day = _clamp_day(shifted_month_first.year, shifted_month_first.month, int(dd))
    shifted = date(shifted_month_first.year, shifted_month_first.month, clamped_day)
    return f"{shifted.month:02d}/{shifted.day:02d}/{shifted.year:04d} {hhmm} {tz}"


def _shift_filename_date(value: str, offset: relativedelta) -> str:
    """Shift the ``YYYY.MM.DD`` prefix of a ``date_file_name`` entry."""
    m = _FILENAME_DATE_RE.match(value)
    if not m:
        return value
    yyyy, mm, dd, hhmm, tail = m.groups()
    shifted_month_first = date(int(yyyy), int(mm), 1) + offset
    clamped_day = _clamp_day(shifted_month_first.year, shifted_month_first.month, int(dd))
    return f"{shifted_month_first.year:04d}.{shifted_month_first.month:02d}.{clamped_day:02d}_{hhmm}{tail}"


def _apply_date_shift(transactions: list[dict[str, Any]], target_month: date) -> list[dict[str, Any]]:
    """Return a new list of transactions with their date fields shifted.

    ``target_month`` should be a first-of-month date. No-ops (copies through) when
    the seed has no parseable dates or the computed offset is zero.
    """
    if not transactions:
        return transactions

    anchor = _seed_anchor_month(transactions)
    if anchor is None:
        return transactions

    offset = _compute_month_offset(anchor, target_month)
    if offset.years == 0 and offset.months == 0:
        return transactions

    shifted: list[dict[str, Any]] = []
    for txn in transactions:
        new_txn = dict(txn)
        if "date" in new_txn:
            new_txn["date"] = _shift_date_field(new_txn["date"], offset)
        if "date_file_name" in new_txn:
            new_txn["date_file_name"] = _shift_filename_date(new_txn["date_file_name"], offset)
        shifted.append(new_txn)
    return shifted


_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
# YYYY-MM or YYYY_MM tokens inside statement ids/filenames ("rbc-avion-visa-2026-02.pdf")
_YM_TOKEN_RE = re.compile(r"(\d{4})([-_])(\d{2})(?!\d)")

_STATEMENT_DATE_FIELDS = ("uploaded_at", "updated_at", "completed_at", "period_start", "period_end")
_STATEMENT_NAME_FIELDS = ("id", "filename")

# action_result values whose row counts the statements list endpoint derives
# from statement_transactions (everything else is a statements-table column).
_OUTCOME_FIELDS = {
    "imported_count": ("imported", "new"),
    "enriched_count": ("enriched", "matched"),
    "updated_count": ("updated", "matched"),
    "skipped_count": ("skipped", "new"),
    "duplicate_count": ("duplicate", "new"),
}


def _shift_iso_prefix(value: str, offset: relativedelta) -> str:
    """Shift the leading ``YYYY-MM-DD`` of an ISO date/datetime string."""
    m = _ISO_DATE_RE.match(value)
    if not m:
        return value
    yyyy, mm, dd = m.groups()
    shifted_first = date(int(yyyy), int(mm), 1) + offset
    clamped = _clamp_day(shifted_first.year, shifted_first.month, int(dd))
    return f"{shifted_first.year:04d}-{shifted_first.month:02d}-{clamped:02d}{value[10:]}"


def _shift_ym_tokens(value: str, offset: relativedelta) -> str:
    """Shift ``YYYY-MM`` / ``YYYY_MM`` tokens inside statement ids and filenames."""

    def repl(m: re.Match[str]) -> str:
        shifted = date(int(m.group(1)), int(m.group(3)), 1) + offset
        return f"{shifted.year:04d}{m.group(2)}{shifted.month:02d}"

    return _YM_TOKEN_RE.sub(repl, value)


def _load_statements(statements: list[dict[str, Any]], offset: relativedelta) -> int:
    """Seed the demo statement-history database from the seed's ``statements``.

    Statements land in their own SQLite file (``DEMO_STATEMENTS_DB_PATH``) so
    demo mode never touches a host's real ``data/statements.db``. Outcome
    counts (imported/enriched/…) are derived by the list endpoint from
    ``statement_transactions`` rows, so minimal stub rows are inserted to
    produce them; statement detail is never fetched in the demo.
    """
    from src.finance.statement_store import StatementStore

    StatementStore(DEMO_STATEMENTS_DB_PATH)  # ensures schema exists
    conn = get_connection(DEMO_STATEMENTS_DB_PATH)
    try:
        conn.execute("DELETE FROM statement_transactions")
        conn.execute("DELETE FROM statements")
        for stmt in statements:
            row = dict(stmt)
            for field in _STATEMENT_DATE_FIELDS:
                if row.get(field):
                    row[field] = _shift_iso_prefix(row[field], offset)
            for field in _STATEMENT_NAME_FIELDS:
                if row.get(field):
                    row[field] = _shift_ym_tokens(row[field], offset)
            conn.execute(
                """INSERT INTO statements (
                    id, filename, institution, account_type, period_start, period_end,
                    pdf_path, uploaded_at, updated_at, completed_at, total_parsed,
                    matched_count, ambiguous_count, new_count, previously_imported_count,
                    suspected_duplicate_count, status
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    row["filename"],
                    row["institution"],
                    row["account_type"],
                    row.get("period_start"),
                    row.get("period_end"),
                    row["uploaded_at"],
                    row.get("updated_at", row["uploaded_at"]),
                    row.get("completed_at"),
                    row.get("total_parsed", 0),
                    row.get("matched_count", 0),
                    row.get("ambiguous_count", 0),
                    row.get("new_count", 0),
                    row.get("previously_imported_count", 0),
                    row.get("suspected_duplicate_count", 0),
                    row.get("status", "complete"),
                ),
            )
            tx_index = 0
            for count_field, (action_result, tier) in _OUTCOME_FIELDS.items():
                for _ in range(int(row.get(count_field, 0))):
                    conn.execute(
                        """INSERT INTO statement_transactions (
                            statement_id, tx_index, reconcile_tier, date, amount, action_result
                        ) VALUES (?, ?, ?, ?, 0.0, ?)""",
                        (row["id"], tx_index, tier, row.get("period_end") or "", action_result),
                    )
                    tx_index += 1
        conn.commit()
        return len(statements)
    finally:
        conn.close()


def load_demo_data(db_path: Path | None = None, freeze_to_month: date | None = None) -> int:
    """Load demo seed data into the SQLite database.

    By default, transaction dates are shifted forward so the seed's most-recent
    month lands on the current calendar month. Pass ``freeze_to_month`` (or set
    ``DEMO_FREEZE_MONTH=YYYY-MM``) to pin to a specific month instead; the
    parameter wins when both are provided.

    Returns the number of transactions inserted.
    """
    db_path = db_path or DEMO_DB_PATH
    ensure_schema(db_path)

    if not SEED_PATH.exists():
        logger.warning("Demo seed file not found: %s", SEED_PATH)
        return 0

    with open(SEED_PATH) as f:
        seed = json.load(f)

    target_month = freeze_to_month or _env_freeze_month() or app_today().replace(day=1)
    # Normalise to first-of-month so callers passing mid-month dates still behave.
    target_month = target_month.replace(day=1)

    transactions = _apply_date_shift(seed.get("transactions", []), target_month)
    anchor = _seed_anchor_month(seed.get("transactions", []))
    offset = _compute_month_offset(anchor, target_month) if anchor else relativedelta()

    conn = get_connection(db_path)
    count = 0
    try:
        # Insert transactions
        for txn in transactions:
            conn.execute(
                """INSERT OR IGNORE INTO transactions (
                    forwarded_to, date_file_name, transaction_hash,
                    institution, amount, company, transaction_type, category,
                    name, date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    txn["forwarded_to"],
                    txn["date_file_name"],
                    txn["transaction_hash"],
                    txn.get("institution", "Demo Bank"),
                    txn["amount"],
                    txn["company"],
                    txn["transaction_type"],
                    txn["category"],
                    txn.get("name", "Demo User"),
                    txn["date"],
                ),
            )
            count += 1

        # Insert budget targets
        user_pk = "USER#default"
        today = app_today()
        year = target_month.year

        targets = seed.get("budget_targets")
        if targets:
            conn.execute(
                "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_pk, f"BUDGET#targets#{year}", json.dumps(targets), 1, today.isoformat()),
            )

        groups = seed.get("budget_groups")
        if groups:
            conn.execute(
                "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_pk, f"BUDGET#groups#{year}", json.dumps({"groups": groups}), 1, today.isoformat()),
            )

        # Insert category overrides
        overrides = seed.get("category_overrides")
        if overrides:
            conn.execute(
                "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_pk, "CONFIG#category_overrides", json.dumps(overrides), 1, today.isoformat()),
            )

        # Insert merchant aliases
        aliases = seed.get("merchant_aliases")
        if aliases:
            conn.execute(
                "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_pk, "CONFIG#merchant_aliases", json.dumps(aliases), 1, today.isoformat()),
            )

        # Insert categories list from config file
        categories_path = Path("src/finance/config/categories.json")
        if categories_path.exists():
            with open(categories_path) as f:
                categories = json.load(f)
            conn.execute(
                "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_pk, "CONFIG#categories", json.dumps(categories), 1, today.isoformat()),
            )

        conn.commit()
        logger.info("Loaded %d demo transactions into %s (anchor → %s)", count, db_path, target_month.isoformat())
    finally:
        conn.close()

    statements = seed.get("statements")
    if statements:
        loaded = _load_statements(statements, offset)
        logger.info("Loaded %d demo statements into %s", loaded, DEMO_STATEMENTS_DB_PATH)

    return count


def is_demo_loaded(db_path: Path | None = None) -> bool:
    """Check if demo data already exists in the database."""
    db_path = db_path or DEMO_DB_PATH
    if not db_path.exists():
        return False
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()
            return row["cnt"] > 0
        finally:
            conn.close()
    except Exception:
        return False


def clear_demo_data(db_path: Path | None = None) -> None:
    """Remove all demo data from the database."""
    db_path = db_path or DEMO_DB_PATH
    if not db_path.exists():
        return
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM config_store")
        conn.commit()
        logger.info("Cleared demo data from %s", db_path)
    finally:
        conn.close()
    if DEMO_STATEMENTS_DB_PATH.exists():
        stmt_conn = get_connection(DEMO_STATEMENTS_DB_PATH)
        try:
            stmt_conn.execute("DELETE FROM statement_transactions")
            stmt_conn.execute("DELETE FROM statements")
            stmt_conn.commit()
        finally:
            stmt_conn.close()


def ensure_demo_loaded(db_path: Path | None = None, freeze_to_month: date | None = None) -> None:
    """Load demo data if not already present (called on first run).

    ``freeze_to_month`` is forwarded to :func:`load_demo_data`; see its docstring
    for the precedence rules with ``DEMO_FREEZE_MONTH``.
    """
    db_path = db_path or DEMO_DB_PATH
    if not is_demo_loaded(db_path):
        load_demo_data(db_path, freeze_to_month=freeze_to_month)
