"""Tests for CoverageService — per-institution cadence + passive capture rate.

Mirrors the MagicMock-summary pattern of ``test_merchant_intelligence.py``: the
spending summary is a mock whose ``query_month`` returns raw rows with
DateFileName/Institution, keyed (filtered) by the requested year_month. "Today"
is frozen to 2026-05-07 via the shared ``freeze_clock`` seam pointed at
``src.finance.demo_clock`` (the module ``app_today`` lives in), so the trailing
12-month window is 2025-06 … 2026-05 and day-since arithmetic is deterministic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.finance import demo_clock
from src.finance.coverage_service import CoverageService, _event_day, _iso_to_date

if TYPE_CHECKING:
    from collections.abc import Callable

FROZEN = datetime(2026, 5, 7, 20, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
TODAY = FROZEN.date()  # 2026-05-07


@pytest.fixture
def frozen_today(freeze_clock: Callable[..., datetime], monkeypatch: pytest.MonkeyPatch) -> date:
    monkeypatch.delenv("DEMO_TODAY", raising=False)
    freeze_clock(demo_clock, at=FROZEN)
    return TODAY


def _row(institution: str, day: date, time: str = "10.00", suffix: str | None = None) -> dict[str, Any]:
    suffix = suffix or f"{institution.lower()}.eml"
    return {"DateFileName": f"{day:%Y.%m.%d}_{time}_{suffix}", "Institution": institution}


def _series(institution: str, end: date, count: int, step: int = 7) -> list[dict[str, Any]]:
    """`count` distinct event-days spaced `step` days apart, ending at `end`."""
    return [_row(institution, end - timedelta(days=step * i)) for i in range(count)]


def _summary(rows: list[dict[str, Any]]) -> MagicMock:
    ss = MagicMock(name="spending_summary")

    def query_month(
        year_month: str, projection: str | None = None, expression_names: Any = None
    ) -> list[dict[str, Any]]:
        prefix = year_month.replace("-", ".")
        return [r for r in rows if r["DateFileName"].startswith(prefix)]

    ss.query_month.side_effect = query_month
    return ss


def _parse_failures(quarantine: dict[str, str] | None = None, *, raising: bool = False) -> MagicMock:
    pf = MagicMock(name="parse_failure_store")
    if raising:
        pf.latest_received_by_institution.side_effect = RuntimeError("boom")
    else:
        pf.latest_received_by_institution.return_value = quarantine or {}
    return pf


def _service(
    rows: list[dict[str, Any]],
    quarantine: dict[str, str] | None = None,
    statement_store: Any = None,
    *,
    raising_pf: bool = False,
) -> CoverageService:
    return CoverageService(_summary(rows), _parse_failures(quarantine, raising=raising_pf), statement_store)


def _find(result: dict[str, Any], institution: str) -> dict[str, Any] | None:
    return next((r for r in result["institutions"] if r["institution"] == institution), None)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_active_recent_cadence(frozen_today: date) -> None:
    # Weekly alerts, last one 2 days ago → active.
    rows = _series("RBC", date(2026, 5, 5), count=15, step=7)
    result = _service(rows).get_coverage()
    rbc = _find(result, "RBC")
    assert rbc is not None
    assert rbc["status"] == "active"
    assert rbc["last_seen_at"] == "2026-05-05"
    assert rbc["days_since_last_seen"] == 2
    assert rbc["median_gap_days"] == 7.0
    assert rbc["threshold_gap_days"] == 11  # ceil(1.5 * 7)
    assert rbc["dormant_cutoff_days"] == 45  # max(45, 3 * 11) — the floor wins
    assert rbc["event_days"] == 15


def test_quiet_when_past_threshold(frozen_today: date) -> None:
    # Weekly cadence (threshold 11), last alert 20 days ago → quiet.
    rows = _series("CIBC", date(2026, 4, 17), count=12, step=7)
    result = _service(rows).get_coverage()
    cibc = _find(result, "CIBC")
    assert cibc is not None
    assert cibc["status"] == "quiet"
    assert cibc["days_since_last_seen"] == 20


def test_dormant_beyond_cutoff(frozen_today: date) -> None:
    # Weekly cadence, last alert ~112 days ago → beyond the 45-day cutoff.
    rows = _series("Simplii", date(2026, 1, 15), count=12, step=7)
    result = _service(rows).get_coverage()
    simplii = _find(result, "Simplii")
    assert simplii is not None
    assert simplii["status"] == "dormant"
    assert simplii["days_since_last_seen"] > 45


def test_irregular_too_few_events(frozen_today: date) -> None:
    # Only 5 distinct event-days (< 8) → irregular, no stats claimed.
    rows = _series("MBNA", date(2026, 5, 1), count=5, step=10)
    result = _service(rows).get_coverage()
    mbna = _find(result, "MBNA")
    assert mbna is not None
    assert mbna["status"] == "irregular"
    assert mbna["median_gap_days"] is None
    assert mbna["threshold_gap_days"] is None
    assert mbna["dormant_cutoff_days"] is None
    assert mbna["event_days"] == 5
    assert mbna["last_seen_at"] == "2026-05-01"


def test_irregular_span_too_short(frozen_today: date) -> None:
    # 10 distinct days but only a 9-day span (< 60) → irregular.
    rows = _series("PCFinancial", date(2026, 5, 1), count=10, step=1)
    result = _service(rows).get_coverage()
    pc = _find(result, "PCFinancial")
    assert pc is not None
    assert pc["status"] == "irregular"
    assert pc["event_days"] == 10


def test_threshold_floor_of_seven(frozen_today: date) -> None:
    # Daily cadence → p95 gap of 1, ceil(1.5*1)=2, floored up to 7.
    rows = _series("RBC", date(2026, 5, 5), count=61, step=1)
    result = _service(rows).get_coverage()
    rbc = _find(result, "RBC")
    assert rbc is not None
    assert rbc["threshold_gap_days"] == 7
    assert rbc["status"] == "active"


# ---------------------------------------------------------------------------
# Row inclusion / exclusion
# ---------------------------------------------------------------------------


def test_statement_rows_excluded(frozen_today: date) -> None:
    # An institution whose only rows are statement imports has zero parsed
    # events and is not listed at all.
    rows = [
        {"DateFileName": f"2026.0{m}.15_00.00_stmt_Tangerine_abcd1234.pdf", "Institution": "Tangerine"}
        for m in range(1, 6)
    ]
    result = _service(rows).get_coverage()
    assert _find(result, "Tangerine") is None
    assert result["institutions"] == []


def test_manual_rows_excluded(frozen_today: date) -> None:
    rows = [{"DateFileName": f"2026.0{m}.15_00.00_manual_abcd1234.eml", "Institution": "Manual"} for m in range(1, 6)]
    result = _service(rows).get_coverage()
    assert _find(result, "Manual") is None


def test_unparseable_datefilename_skipped(frozen_today: date) -> None:
    # A mix of a real weekly cadence plus junk rows for the same institution;
    # only the real email arrivals count as event-days.
    rows = _series("RBC", date(2026, 5, 5), count=15, step=7)
    rows.append({"DateFileName": "not-a-real-key", "Institution": "RBC"})
    rows.append({"DateFileName": "", "Institution": "RBC"})
    result = _service(rows).get_coverage()
    rbc = _find(result, "RBC")
    assert rbc is not None
    assert rbc["event_days"] == 15


def test_rows_without_institution_skipped(frozen_today: date) -> None:
    rows = _series("RBC", date(2026, 5, 5), count=15, step=7)
    rows.append({"DateFileName": "2026.05.06_09.00_x.eml", "Institution": None})
    rows.append({"DateFileName": "2026.05.06_09.00_y.eml", "Institution": ""})
    result = _service(rows).get_coverage()
    # Only RBC is listed; the institution-less rows produced nothing.
    assert [r["institution"] for r in result["institutions"]] == ["RBC"]


def test_ignored_and_deleted_rows_still_count(frozen_today: date) -> None:
    # The service reads raw rows and never filters on Ignored / DeletedAt — an
    # ignored or soft-deleted alert still proves the bank spoke.
    rows = _series("RBC", date(2026, 5, 5), count=15, step=7)
    for r in rows:
        r["Ignored"] = True
        r["DeletedAt"] = "2026-05-06T00:00:00-07:00"
    result = _service(rows).get_coverage()
    rbc = _find(result, "RBC")
    assert rbc is not None
    assert rbc["event_days"] == 15


def test_same_day_alerts_dedupe_to_one_event_day(frozen_today: date) -> None:
    # Two alerts on the same calendar day collapse to a single event-day.
    rows = _series("RBC", date(2026, 5, 5), count=15, step=7)
    duplicate_day = rows[0]["DateFileName"][:10]  # YYYY.MM.DD of the latest event
    rows.append({"DateFileName": f"{duplicate_day}_18.30_second.eml", "Institution": "RBC"})
    result = _service(rows).get_coverage()
    rbc = _find(result, "RBC")
    assert rbc is not None
    assert rbc["event_days"] == 15  # not 16 — same day deduped


# ---------------------------------------------------------------------------
# Quarantine evidence
# ---------------------------------------------------------------------------


def test_quarantine_extends_last_seen_flips_quiet_to_active(frozen_today: date) -> None:
    # Without quarantine this would be quiet (last parsed alert 20 days ago).
    rows = _series("CIBC", date(2026, 4, 17), count=12, step=7)
    quarantine = {"CIBC": "2026-05-06T08:00:00-07:00"}
    result = _service(rows, quarantine=quarantine).get_coverage()
    cibc = _find(result, "CIBC")
    assert cibc is not None
    assert cibc["status"] == "active"
    assert cibc["last_seen_at"] == "2026-05-06"
    assert cibc["days_since_last_seen"] == 1


def test_quarantine_only_institution_not_listed(frozen_today: date) -> None:
    # Quarantine evidence for an institution with no parsed events introduces
    # no row — quiet detection only extends last_seen for known institutions.
    rows = _series("RBC", date(2026, 5, 5), count=15, step=7)
    quarantine = {"GhostBank": "2026-05-06T08:00:00-07:00"}
    result = _service(rows, quarantine=quarantine).get_coverage()
    assert _find(result, "GhostBank") is None
    assert [r["institution"] for r in result["institutions"]] == ["RBC"]


def test_quarantine_read_failure_is_fail_open(frozen_today: date) -> None:
    rows = _series("RBC", date(2026, 5, 5), count=15, step=7)
    # The parse-failure store raises; coverage still computes (quarantine -> {}).
    result = _service(rows, raising_pf=True).get_coverage()
    rbc = _find(result, "RBC")
    assert rbc is not None
    assert rbc["status"] == "active"


# ---------------------------------------------------------------------------
# Capture passthrough
# ---------------------------------------------------------------------------


def test_capture_passthrough_present(frozen_today: date) -> None:
    payload = {"overall": {"caught": 47, "total": 49, "rate": 47 / 49}, "by_institution": [], "by_type": []}
    store = MagicMock(name="statement_store")
    store.capture_summary.return_value = payload
    result = _service(_series("RBC", date(2026, 5, 5), 15), statement_store=store).get_coverage()
    assert result["capture"] == payload


def test_capture_none_when_no_store(frozen_today: date) -> None:
    result = _service(_series("RBC", date(2026, 5, 5), 15), statement_store=None).get_coverage()
    assert result["capture"] is None


def test_capture_none_when_store_returns_none(frozen_today: date) -> None:
    store = MagicMock(name="statement_store")
    store.capture_summary.return_value = None
    result = _service(_series("RBC", date(2026, 5, 5), 15), statement_store=store).get_coverage()
    assert result["capture"] is None


def test_capture_fail_open_when_store_raises(frozen_today: date) -> None:
    store = MagicMock(name="statement_store")
    store.capture_summary.side_effect = RuntimeError("db locked")
    result = _service(_series("RBC", date(2026, 5, 5), 15), statement_store=store).get_coverage()
    assert result["capture"] is None


# ---------------------------------------------------------------------------
# Envelope, sort order, cache
# ---------------------------------------------------------------------------


def test_envelope_fields(frozen_today: date) -> None:
    result = _service(_series("RBC", date(2026, 5, 5), 15)).get_coverage()
    assert result["window_months"] == 12
    assert isinstance(result["checked_at"], str)


def test_sort_order_quiet_active_dormant_irregular(frozen_today: date) -> None:
    rows: list[dict[str, Any]] = []
    rows += _series("ZBankActive", date(2026, 5, 5), count=15, step=7)  # active
    rows += _series("ABankQuiet", date(2026, 4, 17), count=12, step=7)  # quiet
    rows += _series("MBankDormant", date(2026, 1, 15), count=12, step=7)  # dormant
    rows += _series("QBankIrregular", date(2026, 5, 1), count=5, step=10)  # irregular
    result = _service(rows).get_coverage()
    order = [(r["institution"], r["status"]) for r in result["institutions"]]
    assert order == [
        ("ABankQuiet", "quiet"),
        ("ZBankActive", "active"),
        ("MBankDormant", "dormant"),
        ("QBankIrregular", "irregular"),
    ]


def test_alphabetical_within_status_group(frozen_today: date) -> None:
    rows: list[dict[str, Any]] = []
    rows += _series("Zeta", date(2026, 5, 5), count=15, step=7)
    rows += _series("Alpha", date(2026, 5, 5), count=15, step=7)
    result = _service(rows).get_coverage()
    # Both active → alphabetical.
    assert [r["institution"] for r in result["institutions"]] == ["Alpha", "Zeta"]


def test_cache_hit_avoids_recompute(frozen_today: date) -> None:
    svc = _service(_series("RBC", date(2026, 5, 5), 15))
    svc.get_coverage()
    calls = svc._summary.query_month.call_count
    svc.get_coverage()
    assert svc._summary.query_month.call_count == calls  # served from cache


def test_cache_expiry_recomputes(frozen_today: date) -> None:
    svc = _service(_series("RBC", date(2026, 5, 5), 15))
    svc.get_coverage()
    calls = svc._summary.query_month.call_count
    svc._cache_time = 0.0  # force the 1-hour TTL to have elapsed
    svc.get_coverage()
    assert svc._summary.query_month.call_count > calls


def test_invalidate_cache_forces_recompute(frozen_today: date) -> None:
    svc = _service(_series("RBC", date(2026, 5, 5), 15))
    svc.get_coverage()
    calls = svc._summary.query_month.call_count
    svc.invalidate_cache()
    svc.get_coverage()
    assert svc._summary.query_month.call_count > calls


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_event_day_parses_prefix() -> None:
    assert _event_day("2026.05.05_10.00_rbc.eml") == date(2026, 5, 5)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "not-a-key",
        "2026.05.05_00.00_stmt_RBC_abcd1234.pdf",
        "2026.05.05_00.00_manual_abcd1234.eml",
        "2026.13.45_10.00_bad.eml",  # regex matches but date() raises
    ],
)
def test_event_day_rejects(value: str | None) -> None:
    assert _event_day(value) is None


def test_iso_to_date_variants() -> None:
    assert _iso_to_date("2026-05-06T08:00:00-07:00") == date(2026, 5, 6)
    assert _iso_to_date("2026-05-06 not-a-time") == date(2026, 5, 6)  # fromisoformat fails, date part parses
    assert _iso_to_date("garbage") is None
    assert _iso_to_date(None) is None
