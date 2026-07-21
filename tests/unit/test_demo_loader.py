"""Tests for demo_loader — SQLite seed data loader used by open-source demo mode."""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from src.finance import demo_clock, demo_loader
from src.finance.local_db import get_connection

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})\s+(\S+)$")


def _month_key(date_str: str) -> tuple[int, int]:
    m = _DATE_RE.match(date_str)
    assert m, f"unexpected date format: {date_str!r}"
    mm, _dd, yyyy, _hhmm, _tz = m.groups()
    return int(yyyy), int(mm)


def _parse_tx_date(date_str: str) -> date:
    m = _DATE_RE.match(date_str)
    assert m, f"unexpected date format: {date_str!r}"
    mm, dd, yyyy, _hhmm, _tz = m.groups()
    return date(int(yyyy), int(mm), int(dd))


def _load_seed_transactions() -> list[dict[str, Any]]:
    return json.loads(demo_loader.SEED_PATH.read_text()).get("transactions", [])


def _fetch_transaction_dates(db_path: Path) -> list[str]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT date FROM transactions").fetchall()
    finally:
        conn.close()
    return [row["date"] for row in rows]


def _db_row_count(db_path: Path, table: str) -> int:
    conn = get_connection(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()["cnt"]
    finally:
        conn.close()


def _expected_seed_txn_count() -> int:
    """Read the bundled seed file to dynamically derive the expected row count.

    Keeps the test from hardcoding a magic number that drifts when seed data changes.
    """
    seed = json.loads(demo_loader.SEED_PATH.read_text())
    return len(seed.get("transactions", []))


class TestLoadDemoData:
    def test_inserts_expected_transaction_row_count(self, tmp_path: Path) -> None:
        db_path = tmp_path / "demo.db"
        expected = _expected_seed_txn_count()

        count = demo_loader.load_demo_data(db_path)

        assert count == expected
        assert _db_row_count(db_path, "transactions") == expected

    def test_populates_config_store_with_four_rows(self, tmp_path: Path) -> None:
        # targets, groups, category_overrides, categories (from src/finance/config/categories.json)
        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)

        conn = get_connection(db_path)
        try:
            rows = conn.execute("SELECT sk FROM config_store ORDER BY sk").fetchall()
            sks = [row["sk"] for row in rows]
        finally:
            conn.close()

        assert any(sk.startswith("BUDGET#targets#") for sk in sks)
        assert any(sk.startswith("BUDGET#groups#") for sk in sks)
        assert "CONFIG#category_overrides" in sks
        assert "CONFIG#categories" in sks

    def test_creates_schema_on_fresh_db(self, tmp_path: Path) -> None:
        # Verifies the loader calls ensure_schema() — it must not assume a pre-existing DB.
        db_path = tmp_path / "fresh.db"
        assert not db_path.exists()

        demo_loader.load_demo_data(db_path)

        conn = get_connection(db_path)
        try:
            # schema_version table is created by ensure_schema via the migration runner
            row = conn.execute("SELECT version FROM schema_version WHERE version = 1").fetchone()
        finally:
            conn.close()
        assert row is not None

    def test_is_idempotent_on_repeat_call(self, tmp_path: Path) -> None:
        # Second call must not duplicate transactions (INSERT OR IGNORE on primary key).
        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)
        first_count = _db_row_count(db_path, "transactions")

        demo_loader.load_demo_data(db_path)
        second_count = _db_row_count(db_path, "transactions")

        assert first_count == second_count

    def test_returns_zero_when_seed_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(demo_loader, "SEED_PATH", tmp_path / "nonexistent.json")
        db_path = tmp_path / "demo.db"

        count = demo_loader.load_demo_data(db_path)

        assert count == 0


class TestIsDemoLoaded:
    def test_false_when_db_does_not_exist(self, tmp_path: Path) -> None:
        assert demo_loader.is_demo_loaded(tmp_path / "missing.db") is False

    def test_true_after_load(self, tmp_path: Path) -> None:
        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)

        assert demo_loader.is_demo_loaded(db_path) is True

    def test_false_when_db_exists_but_empty(self, tmp_path: Path) -> None:
        # An empty DB (schema only, no rows) should report not loaded.
        db_path = tmp_path / "empty.db"
        from src.finance.local_db import ensure_schema

        ensure_schema(db_path)

        assert demo_loader.is_demo_loaded(db_path) is False


class TestClearDemoData:
    def test_empties_both_tables(self, tmp_path: Path) -> None:
        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)
        assert _db_row_count(db_path, "transactions") > 0

        demo_loader.clear_demo_data(db_path)

        assert _db_row_count(db_path, "transactions") == 0
        assert _db_row_count(db_path, "config_store") == 0

    def test_noop_when_db_missing(self, tmp_path: Path) -> None:
        # Must not raise.
        demo_loader.clear_demo_data(tmp_path / "missing.db")


class TestEnsureDemoLoaded:
    def test_loads_on_first_call(self, tmp_path: Path) -> None:
        db_path = tmp_path / "demo.db"
        demo_loader.ensure_demo_loaded(db_path)

        assert demo_loader.is_demo_loaded(db_path) is True

    def test_skips_when_already_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)

        # If ensure_demo_loaded fires the loader again, it would call SEED_PATH.read_text().
        # Point SEED_PATH at a nonexistent file — if loader runs, count would be 0 which
        # would still be fine, but we can verify by counting load calls.
        calls = []
        original = demo_loader.load_demo_data

        def _record(p: Path | None = None, freeze_to_month: date | None = None) -> int:
            calls.append((p, freeze_to_month))
            return original(p, freeze_to_month=freeze_to_month)

        monkeypatch.setattr(demo_loader, "load_demo_data", _record)

        demo_loader.ensure_demo_loaded(db_path)

        assert calls == []


class TestDynamicDateShift:
    """Seed dates are shifted forward so the most-recent seed month aligns with the
    current calendar month (or a caller-supplied ``freeze_to_month``).
    """

    def test_freeze_to_month_anchors_output_to_that_month(self, tmp_path: Path) -> None:
        # Picking a clearly-different target month from the seed (anchor: 2026-03).
        db_path = tmp_path / "demo.db"
        target = date(2027, 7, 1)

        demo_loader.load_demo_data(db_path, freeze_to_month=target)

        dates = _fetch_transaction_dates(db_path)
        months = {_month_key(d) for d in dates}
        assert (2027, 7) in months  # anchor landed on the target
        # And no date from before the target's full-span window remains at the old anchor.
        assert (2026, 3) not in months

    def test_default_targets_current_calendar_month(self, tmp_path: Path, freeze_clock) -> None:
        # Freeze demo_clock's ``app_today()`` clock to a deterministic day so the
        # default (no freeze_to_month) anchor is predictable without freezegun.
        freeze_clock(demo_clock, at=datetime(2030, 5, 17, tzinfo=ZoneInfo("America/Los_Angeles")))

        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)

        dates = _fetch_transaction_dates(db_path)
        months = {_month_key(d) for d in dates}
        # Default path anchored the seed's most-recent month to May 2030.
        assert (2030, 5) in months

    def test_env_var_freeze_month_is_honoured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEMO_FREEZE_MONTH", "2026-03")

        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)

        dates = _fetch_transaction_dates(db_path)
        months = {_month_key(d) for d in dates}
        # Seed anchor is already 2026-03 so the static-demo fixture path stays identical.
        assert (2026, 3) in months
        assert (2025, 12) in months  # other seed months untouched

    def test_explicit_freeze_beats_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEMO_FREEZE_MONTH", "2099-01")

        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path, freeze_to_month=date(2026, 3, 1))

        months = {_month_key(d) for d in _fetch_transaction_dates(db_path)}
        assert (2026, 3) in months
        assert all(y != 2099 for (y, _m) in months)

    def test_malformed_env_var_falls_back_to_today(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, freeze_clock
    ) -> None:
        monkeypatch.setenv("DEMO_FREEZE_MONTH", "not-a-month")

        freeze_clock(demo_clock, at=datetime(2028, 9, 1, tzinfo=ZoneInfo("America/Los_Angeles")))

        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path)

        months = {_month_key(d) for d in _fetch_transaction_dates(db_path)}
        assert (2028, 9) in months

    def test_day_31_clamps_when_target_month_has_30_days(self, tmp_path: Path) -> None:
        # Seed anchor is 2026-03; a Jan-31 seed tx shifts by +4 months to land in May
        # (31 days). To force a clamp, we target a month whose offset drops Jan onto
        # a short month: shift so March → April. The seed has a 31-Jan tx, so after
        # +1 month shift the seed Jan 31 would point at Feb — which has at most 29 days.
        db_path = tmp_path / "demo.db"
        # Seed anchor 2026-03; ``freeze_to_month=2026-04`` → offset +1 month.
        # Seed has transactions on Jan 31, 2026; shifted they would be Feb 31, which
        # must clamp to Feb 28, 2026 (non-leap).
        seed_txs = _load_seed_transactions()
        jan_31 = [t for t in seed_txs if _parse_tx_date(t["date"]) == date(2026, 1, 31)]
        assert jan_31, "expected at least one 2026-01-31 tx in the seed"

        demo_loader.load_demo_data(db_path, freeze_to_month=date(2026, 4, 1))

        dates = _fetch_transaction_dates(db_path)
        parsed = [_parse_tx_date(d) for d in dates]
        # The Jan-31 rows land on Feb 28 (2026 is not a leap year).
        clamped = [d for d in parsed if d == date(2026, 2, 28)]
        assert len(clamped) >= len(jan_31)
        # And no impossible Feb 29/30/31 slipped through.
        assert all(not (d.month == 2 and d.day > 28) for d in parsed)

    def test_relative_day_spacing_preserved(self, tmp_path: Path) -> None:
        # Pick a seed tx and one 5 days later; after shift, the delta is still 5 days.
        db_path = tmp_path / "demo.db"
        seed_txs = _load_seed_transactions()

        # Find two transactions in the same seed month with a non-trivial gap we can verify.
        # Rent on 2025-12-01, groceries on 2025-12-05 → 4-day gap.
        rent = next(t for t in seed_txs if t["date"].startswith("12/01/2025"))
        later = next(t for t in seed_txs if t["date"].startswith("12/05/2025"))
        original_delta = (_parse_tx_date(later["date"]) - _parse_tx_date(rent["date"])).days

        demo_loader.load_demo_data(db_path, freeze_to_month=date(2030, 7, 1))

        conn = get_connection(db_path)
        try:
            shifted_rent = conn.execute(
                "SELECT date FROM transactions WHERE transaction_hash = ?",
                (rent["transaction_hash"],),
            ).fetchone()["date"]
            shifted_later = conn.execute(
                "SELECT date FROM transactions WHERE transaction_hash = ?",
                (later["transaction_hash"],),
            ).fetchone()["date"]
        finally:
            conn.close()

        shifted_delta = (_parse_tx_date(shifted_later) - _parse_tx_date(shifted_rent)).days
        assert shifted_delta == original_delta

    def test_time_and_timezone_preserved(self, tmp_path: Path) -> None:
        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path, freeze_to_month=date(2030, 7, 1))

        for date_str in _fetch_transaction_dates(db_path):
            m = _DATE_RE.match(date_str)
            assert m, date_str
            _mm, _dd, _yyyy, _hhmm, tz = m.groups()
            # Seed is uniformly PST — the shift must not change the TZ token or HH:MM format.
            assert tz == "PST"
            # Reject any malformed/missing time component.
            datetime.strptime(_hhmm, "%H:%M")  # noqa: DTZ007 — time-format validity check, result discarded

    def test_date_file_name_matches_shifted_date(self, tmp_path: Path) -> None:
        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path, freeze_to_month=date(2030, 7, 1))

        conn = get_connection(db_path)
        try:
            rows = conn.execute("SELECT date, date_file_name FROM transactions").fetchall()
        finally:
            conn.close()

        for row in rows:
            d = _parse_tx_date(row["date"])
            prefix = f"{d.year:04d}.{d.month:02d}.{d.day:02d}_"
            assert row["date_file_name"].startswith(prefix), (
                f"date_file_name {row['date_file_name']!r} does not match date {row['date']!r}"
            )

    def test_empty_seed_is_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty_seed = tmp_path / "empty_seed.json"
        empty_seed.write_text(json.dumps({"transactions": []}))
        monkeypatch.setattr(demo_loader, "SEED_PATH", empty_seed)

        db_path = tmp_path / "demo.db"
        count = demo_loader.load_demo_data(db_path, freeze_to_month=date(2030, 1, 1))

        assert count == 0

    def test_budget_rows_keyed_under_target_month_year(self, tmp_path: Path, freeze_clock) -> None:
        # Regression guard: budget targets/groups must be keyed under the shifted
        # transactions' year, not app_today().year. Otherwise the dashboard's
        # budget view is empty when freeze_to_month crosses a year boundary
        # (e.g. the static-demo fixture path running DEMO_FREEZE_MONTH=2026-03 in 2027).
        # app_today() is frozen to 2026 so the "not app_today().year" guard is real.
        freeze_clock(demo_clock, at=datetime(2026, 4, 23, tzinfo=ZoneInfo("America/Los_Angeles")))

        db_path = tmp_path / "demo.db"
        demo_loader.load_demo_data(db_path, freeze_to_month=date(2027, 7, 1))

        conn = get_connection(db_path)
        try:
            rows = conn.execute("SELECT sk FROM config_store WHERE sk LIKE 'BUDGET#%'").fetchall()
            sks = {row["sk"] for row in rows}
        finally:
            conn.close()

        assert "BUDGET#targets#2027" in sks
        assert "BUDGET#groups#2027" in sks
        assert "BUDGET#targets#2026" not in sks
        assert "BUDGET#groups#2026" not in sks

    def test_compute_month_offset_basic(self) -> None:
        off = demo_loader._compute_month_offset(date(2026, 3, 1), date(2027, 5, 1))
        assert off.years == 1
        assert off.months == 2

        off_zero = demo_loader._compute_month_offset(date(2026, 3, 1), date(2026, 3, 1))
        assert off_zero.years == 0
        assert off_zero.months == 0

        off_back = demo_loader._compute_month_offset(date(2026, 3, 1), date(2025, 12, 1))
        # relativedelta normalises (-3 months) as years=0 months=-3
        total_months = off_back.years * 12 + off_back.months
        assert total_months == -3


def test_seed_file_is_committed_and_parseable() -> None:
    # Launch-blocker smoke test: the bundled seed file must exist and be valid JSON
    # with the top-level shape demo_loader expects. Without this, a fresh clone + demo
    # mode would silently load zero data.
    seed_path = Path("data/demo/seed.json")
    assert seed_path.exists(), "data/demo/seed.json must be committed for demo mode to work"

    seed = json.loads(seed_path.read_text())
    assert isinstance(seed.get("transactions"), list)
    assert len(seed["transactions"]) > 0
    assert isinstance(seed.get("budget_targets"), dict)
    assert isinstance(seed.get("budget_groups"), list)
    assert isinstance(seed.get("category_overrides"), dict)
