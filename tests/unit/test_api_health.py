"""Tests for the /api/v1/health liveness probe."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from src.api.routers import health as health_router
from src.finance.local_db import ensure_schema
from tests.asserts import assert_ok

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_heartbeat(db_path: Path, *, age_seconds: int) -> None:
    """Seed a config_store heartbeat row N seconds in the past."""
    from src.finance.local_db import get_connection

    ts = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO config_store (pk, sk, data_json, version, updated_at) VALUES (?, ?, ?, 1, ?)",
            ("SYSTEM#imap_poller", "last_poll_at", json.dumps({"ts": ts}), ts),
        )
        conn.commit()
    finally:
        conn.close()


class _StubTxDb:
    def __init__(self, latest_dfn: str | None, audits: list[dict] | None = None):
        self._latest = latest_dfn
        self._audits = audits or []

    def get_latest_date_file_name(self, year_month: str | None = None) -> str | None:
        _ = year_month  # unused — probe only ever asks for "global latest"
        return self._latest

    def get_recent_audits(self, limit: int = 25) -> list[dict]:
        return self._audits[:limit]


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point get_imap_last_poll at an empty tmp SQLite DB for each test."""
    db_path = tmp_path / "health_test.db"
    ensure_schema(db_path)

    from src.finance import poller_state

    # get_imap_last_poll() lives in poller_state and resolves its default path
    # from poller_state.DEFAULT_DB_PATH at call time (health.py re-exports it
    # via imap_poller). Patch it there so the freshness probe hits the tmp DB.
    original_default = poller_state.DEFAULT_DB_PATH
    monkeypatch.setattr(poller_state, "DEFAULT_DB_PATH", db_path)
    yield db_path
    monkeypatch.setattr(poller_state, "DEFAULT_DB_PATH", original_default)


@pytest.fixture
def stub_tx_db(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Replace the transactions-DB dependency with a stub.

    ``stub_tx_db(latest_dfn)`` controls the freshness probe;
    ``stub_tx_db(latest_dfn, audits=[...])`` also feeds the AI-categorization signal.
    """

    def _apply(latest_dfn: str | None, audits: list[dict] | None = None) -> None:
        stub = _StubTxDb(latest_dfn, audits)
        monkeypatch.setattr(
            "src.api.routers.health.get_transactions_db",
            lambda: stub,
        )

    return _apply


@pytest.fixture(autouse=True)
def isolate_parse_failure_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Bind the health probe's parse-failure store to a fresh isolated DB.

    The ``_parse_failure_store`` singleton in ``dependencies`` is created at
    import time against the real DB path, so without this it leaks rows across
    tests (and across the whole process) and the count is non-deterministic.
    Pointing it at a fresh per-test SQLite DB makes the default count 0; the
    ``stub_parse_failures`` fixture overrides this when a specific count or a
    raising store is needed.
    """
    from src.finance.parse_failure_store_local import ParseFailureStoreLocal

    store = ParseFailureStoreLocal(db_path=tmp_path / "parse_failures.db")
    monkeypatch.setattr(
        "src.api.routers.health.get_parse_failure_store",
        lambda: store,
    )


@pytest.fixture
def stub_parse_failures(monkeypatch: pytest.MonkeyPatch) -> Callable[[int | None], None]:
    """Replace the parse-failure-store dependency with a stub.

    Pass an ``int`` to fix ``count_recent_quarantined``, or ``None`` to make the
    count call raise (exercising the fail-open path → field ``None``).
    """

    def _apply(count: int | None) -> None:
        class _StubStore:
            def count_recent_quarantined(self, days: int = 7) -> int:
                if count is None:
                    raise RuntimeError("parse-failure store unreadable")
                return count

        monkeypatch.setattr(
            "src.api.routers.health.get_parse_failure_store",
            lambda: _StubStore(),
        )

    return _apply


def _coverage_snapshot(quiet_count: int) -> dict:
    """A coverage snapshot with ``quiet_count`` quiet institutions (plus one active)."""
    institutions = [{"institution": f"Bank{i}", "status": "quiet"} for i in range(quiet_count)]
    institutions.append({"institution": "Active", "status": "active"})
    return {
        "institutions": institutions,
        "capture": None,
        "window_months": 12,
        "checked_at": "2026-07-17T10:00:00-07:00",
    }


@pytest.fixture(autouse=True)
def isolate_coverage_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind the health probe's coverage service to a stub with no quiet institutions.

    The real ``get_coverage_service`` singleton reads live summary data —
    nondeterministic and slow for the probe tests. Default to a snapshot with no
    quiet institutions (count 0); the ``stub_coverage`` fixture overrides this
    when a specific quiet count or a raising read is needed.
    """

    class _StubCoverage:
        def get_coverage(self) -> dict:
            return _coverage_snapshot(0)

    monkeypatch.setattr(
        "src.api.routers.health.get_coverage_service",
        lambda: _StubCoverage(),
    )


@pytest.fixture
def stub_coverage(monkeypatch: pytest.MonkeyPatch) -> Callable[[int | None], None]:
    """Replace the coverage-service dependency with a stub.

    Pass an ``int`` for the quiet-institution count, or ``None`` to make
    ``get_coverage`` raise (exercising the fail-open path → field ``None``).
    """

    def _apply(quiet_count: int | None) -> None:
        class _StubCoverage:
            def get_coverage(self) -> dict:
                if quiet_count is None:
                    raise RuntimeError("coverage read exploded")
                return _coverage_snapshot(quiet_count)

        monkeypatch.setattr(
            "src.api.routers.health.get_coverage_service",
            lambda: _StubCoverage(),
        )

    return _apply


def _dfn_from_age(*, days_ago: int) -> str:
    dt = datetime.now(UTC) - timedelta(days=days_ago)
    return dt.strftime("%Y.%m.%d_%H.%M_") + "example.eml"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_fresh_db_no_txns_no_imap_returns_ok(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        stub_tx_db(None)
        resp = api_client.get("/api/v1/health")
        assert_ok(resp)
        data = resp.json()
        assert data["status"] == "ok"
        assert data["imap_last_poll"] is None
        assert data["imap_poll_age_seconds"] is None
        assert data["last_transaction_at"] is None
        assert data["last_transaction_age_seconds"] is None
        assert data["backend"] in {"sqlite", "dynamodb"}
        assert data["version"]
        assert data["checked_at"]

    def test_recent_imap_poll_returns_ok(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        _write_heartbeat(isolated_db, age_seconds=120)
        stub_tx_db(None)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert data["imap_poll_age_seconds"] is not None
        # Allow a small wiggle for test-execution time.
        assert 100 <= data["imap_poll_age_seconds"] <= 180

    def test_10_minute_old_poll_returns_degraded(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        _write_heartbeat(isolated_db, age_seconds=10 * 60)
        stub_tx_db(None)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "degraded"

    def test_2_hour_old_poll_returns_stale(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        _write_heartbeat(isolated_db, age_seconds=2 * 60 * 60)
        stub_tx_db(None)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "stale"

    def test_old_transaction_forces_stale_even_with_fresh_poll(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        _write_heartbeat(isolated_db, age_seconds=30)
        stub_tx_db(_dfn_from_age(days_ago=30))
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "stale"
        assert data["last_transaction_age_seconds"] is not None
        assert data["last_transaction_age_seconds"] > 14 * 24 * 60 * 60

    def test_recent_transaction_parsed_to_iso(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        stub_tx_db(_dfn_from_age(days_ago=1))
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["last_transaction_at"] is not None
        assert data["last_transaction_at"].endswith("Z")
        assert data["last_transaction_age_seconds"] is not None

    def test_malformed_date_file_name_is_ignored(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        stub_tx_db("garbage-not-a-dfn")
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["last_transaction_at"] is None
        assert data["last_transaction_age_seconds"] is None

    def test_broken_tx_db_does_not_500(self, isolated_db: Path, monkeypatch: pytest.MonkeyPatch, api_client) -> None:
        class _Boom:
            def get_latest_date_file_name(self, year_month: str | None = None) -> str | None:
                _ = year_month
                raise RuntimeError("storage backend exploded")

        monkeypatch.setattr(
            "src.api.routers.health.get_transactions_db",
            lambda: _Boom(),
        )
        resp = api_client.get("/api/v1/health")
        assert_ok(resp)
        assert resp.json()["last_transaction_at"] is None


# ---------------------------------------------------------------------------
# Parse-failure drift signal (§3.1)
# ---------------------------------------------------------------------------


class TestParseFailureSignal:
    def test_field_present_and_zero_on_fresh_db(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        """Fresh boot with no quarantined emails → field present, count 0, ok."""
        stub_tx_db(None)
        resp = api_client.get("/api/v1/health")
        assert_ok(resp)
        data = resp.json()
        assert data["parse_failures_7d"] == 0
        assert data["status"] == "ok"

    def test_count_populates_and_degrades(
        self,
        isolated_db: Path,
        stub_tx_db: Callable[[str | None], None],
        stub_parse_failures: Callable[[int | None], None],
        api_client,
    ) -> None:
        """count > 0 with an otherwise-ok probe → degraded, count surfaced."""
        stub_tx_db(None)
        stub_parse_failures(3)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["parse_failures_7d"] == 3
        assert data["status"] == "degraded"

    def test_store_exception_yields_none_and_no_500(
        self,
        isolated_db: Path,
        stub_tx_db: Callable[[str | None], None],
        stub_parse_failures: Callable[[int | None], None],
        api_client,
    ) -> None:
        """A store that raises → field None, probe still 200 (fail-open)."""
        stub_tx_db(None)
        stub_parse_failures(None)
        resp = api_client.get("/api/v1/health")
        assert_ok(resp)
        data = resp.json()
        assert data["parse_failures_7d"] is None
        assert data["status"] == "ok"

    def test_stale_wins_over_quarantine_degraded(
        self,
        isolated_db: Path,
        stub_tx_db: Callable[[str | None], None],
        stub_parse_failures: Callable[[int | None], None],
        api_client,
    ) -> None:
        """A stale transaction beats the quarantine-driven degraded — stale wins."""
        _write_heartbeat(isolated_db, age_seconds=30)
        stub_tx_db(_dfn_from_age(days_ago=30))
        stub_parse_failures(5)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["parse_failures_7d"] == 5
        assert data["status"] == "stale"


# ---------------------------------------------------------------------------
# Quiet-institution signal (ingestion coverage)
# ---------------------------------------------------------------------------


class TestQuietInstitutionsSignal:
    def test_zero_quiet_leaves_status_unchanged(
        self, isolated_db: Path, stub_tx_db: Callable[[str | None], None], api_client
    ) -> None:
        """No quiet institutions → field present, count 0, status still ok."""
        stub_tx_db(None)
        resp = api_client.get("/api/v1/health")
        assert_ok(resp)
        data = resp.json()
        assert data["quiet_institutions"] == 0
        assert data["status"] == "ok"

    def test_quiet_count_populates_and_degrades(
        self,
        isolated_db: Path,
        stub_tx_db: Callable[[str | None], None],
        stub_coverage: Callable[[int | None], None],
        api_client,
    ) -> None:
        """quiet > 0 with an otherwise-ok probe → degraded, count surfaced."""
        stub_tx_db(None)
        stub_coverage(2)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["quiet_institutions"] == 2
        assert data["status"] == "degraded"

    def test_stale_wins_over_quiet_degraded(
        self,
        isolated_db: Path,
        stub_tx_db: Callable[[str | None], None],
        stub_coverage: Callable[[int | None], None],
        api_client,
    ) -> None:
        """A stale transaction beats the quiet-driven degraded — stale wins, count still surfaced."""
        _write_heartbeat(isolated_db, age_seconds=30)
        stub_tx_db(_dfn_from_age(days_ago=30))
        stub_coverage(3)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["quiet_institutions"] == 3
        assert data["status"] == "stale"

    def test_coverage_read_exception_yields_none_and_no_500(
        self,
        isolated_db: Path,
        stub_tx_db: Callable[[str | None], None],
        stub_coverage: Callable[[int | None], None],
        api_client,
    ) -> None:
        """A coverage read that raises → field None, status computed without it, 200."""
        stub_tx_db(None)
        stub_coverage(None)
        resp = api_client.get("/api/v1/health")
        assert_ok(resp)
        data = resp.json()
        assert data["quiet_institutions"] is None
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# Unit tests for the pure helpers
# ---------------------------------------------------------------------------


class TestComputeStatus:
    def test_ok_when_both_none(self):
        assert health_router._compute_status(None, None) == "ok"

    def test_ok_when_poll_fresh(self):
        assert health_router._compute_status(60, 3600) == "ok"

    def test_degraded_band(self):
        assert health_router._compute_status(10 * 60, 0) == "degraded"

    def test_stale_long_poll(self):
        assert health_router._compute_status(60 * 60, 0) == "stale"

    def test_stale_old_tx_beats_fresh_poll(self):
        assert health_router._compute_status(1, 20 * 24 * 60 * 60) == "stale"

    def test_parse_failures_degrade_otherwise_ok(self):
        assert health_router._compute_status(None, None, 1) == "degraded"

    def test_zero_parse_failures_stays_ok(self):
        assert health_router._compute_status(None, None, 0) == "ok"

    def test_none_parse_failures_stays_ok(self):
        assert health_router._compute_status(60, 3600, None) == "ok"

    def test_parse_failures_never_upgrade_stale(self):
        # stale (old tx) must win even with quarantined failures present.
        assert health_router._compute_status(1, 20 * 24 * 60 * 60, 5) == "stale"

    def test_ai_degraded_degrades_otherwise_ok(self):
        assert health_router._compute_status(None, None, 0, "degraded") == "degraded"

    def test_ai_ok_stays_ok(self):
        assert health_router._compute_status(60, 3600, 0, "ok") == "ok"

    def test_ai_none_stays_ok(self):
        assert health_router._compute_status(60, 3600, 0, None) == "ok"

    def test_ai_degraded_never_upgrades_stale(self):
        assert health_router._compute_status(1, 20 * 24 * 60 * 60, 0, "degraded") == "stale"

    def test_quiet_institutions_degrade_otherwise_ok(self):
        assert health_router._compute_status(None, None, 0, None, 1) == "degraded"

    def test_zero_quiet_institutions_stays_ok(self):
        assert health_router._compute_status(None, None, 0, None, 0) == "ok"

    def test_none_quiet_institutions_stays_ok(self):
        assert health_router._compute_status(60, 3600, 0, None, None) == "ok"

    def test_quiet_institutions_never_upgrade_stale(self):
        assert health_router._compute_status(1, 20 * 24 * 60 * 60, 0, None, 3) == "stale"


def _audit_row(source: str, reason: str | None = None) -> dict:
    """Build a recent-audit row as get_recent_audits would return it."""
    audit: dict = {"source": source, "schema_version": 2}
    if reason is not None:
        audit["fallback_reason"] = reason
    return {"CategoryAudit": audit}


# ---------------------------------------------------------------------------
# AI-categorization signal (recent-audit derived)
# ---------------------------------------------------------------------------


class TestComputeAiCategorization:
    def test_none_audits_is_none(self):
        assert health_router._compute_ai_categorization(None) == (None, None)

    def test_empty_audits_is_ok(self):
        assert health_router._compute_ai_categorization([]) == ("ok", None)

    def test_hard_errors_dominate_is_degraded(self):
        audits = [_audit_row("ai_fallback", "quota_exceeded")] * 4
        status, reason = health_router._compute_ai_categorization(audits)
        assert status == "degraded"
        assert reason == "quota_exceeded"

    def test_most_recent_reason_surfaces(self):
        # Newest-first: auth_error is most recent, then quota.
        audits = [
            _audit_row("ai_fallback", "auth_error"),
            _audit_row("ai_fallback", "quota_exceeded"),
            _audit_row("ai_fallback", "quota_exceeded"),
        ]
        status, reason = health_router._compute_ai_categorization(audits)
        assert status == "degraded"
        assert reason == "auth_error"

    def test_successes_dominate_is_ok(self):
        audits = [_audit_row("ai")] * 10 + [_audit_row("ai_fallback", "quota_exceeded")] * 2
        assert health_router._compute_ai_categorization(audits) == ("ok", None)

    def test_below_min_errors_is_ok(self):
        audits = [_audit_row("ai_fallback", "quota_exceeded")] * 2
        assert health_router._compute_ai_categorization(audits) == ("ok", None)

    def test_intentional_reasons_ignored(self):
        # disabled / no_client are user choices, not outages.
        audits = [_audit_row("ai_fallback", "disabled")] * 5 + [_audit_row("ai_fallback", "no_client")] * 5
        assert health_router._compute_ai_categorization(audits) == ("ok", None)

    def test_soft_hiccups_ignored(self):
        audits = [_audit_row("ai_fallback", "empty_completion")] * 5
        assert health_router._compute_ai_categorization(audits) == ("ok", None)

    def test_override_rows_ignored(self):
        audits = [_audit_row("override")] * 20
        assert health_router._compute_ai_categorization(audits) == ("ok", None)

    def test_codex_errors_degrade(self):
        audits = [_audit_row("ai_fallback", "codex_timeout")] * 3
        status, reason = health_router._compute_ai_categorization(audits)
        assert status == "degraded"
        assert reason == "codex_timeout"


class TestAiCategorizationEndpoint:
    def test_degraded_surfaces_in_status_and_fields(
        self, isolated_db: Path, stub_tx_db: Callable[..., None], api_client
    ) -> None:
        stub_tx_db(_dfn_from_age(days_ago=1), audits=[_audit_row("ai_fallback", "quota_exceeded")] * 4)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["ai_categorization_status"] == "degraded"
        assert data["ai_last_error_reason"] == "quota_exceeded"

    def test_healthy_ai_is_ok(self, isolated_db: Path, stub_tx_db: Callable[..., None], api_client) -> None:
        stub_tx_db(_dfn_from_age(days_ago=1), audits=[_audit_row("ai")] * 5)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["ai_categorization_status"] == "ok"
        assert data["ai_last_error_reason"] is None

    def test_unreadable_audits_yield_none_no_500(
        self, isolated_db: Path, monkeypatch: pytest.MonkeyPatch, api_client
    ) -> None:
        class _Boom:
            def get_latest_date_file_name(self, year_month: str | None = None) -> str | None:
                return None

            def get_recent_audits(self, limit: int = 25) -> list[dict]:
                raise RuntimeError("audit read exploded")

        monkeypatch.setattr("src.api.routers.health.get_transactions_db", lambda: _Boom())
        resp = api_client.get("/api/v1/health")
        assert_ok(resp)
        assert resp.json()["ai_categorization_status"] is None

    def test_ai_degraded_never_beats_stale(
        self, isolated_db: Path, stub_tx_db: Callable[..., None], api_client
    ) -> None:
        _write_heartbeat(isolated_db, age_seconds=30)
        stub_tx_db(_dfn_from_age(days_ago=30), audits=[_audit_row("ai_fallback", "quota_exceeded")] * 4)
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "stale"
        assert data["ai_categorization_status"] == "degraded"


class TestDateFileNameParser:
    def test_parses_valid(self):
        dt = health_router._date_file_name_to_dt("2026.04.22_09.14_foo.eml")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.day == 22

    def test_rejects_garbage(self):
        assert health_router._date_file_name_to_dt("not-a-key") is None
        assert health_router._date_file_name_to_dt(None) is None

    def test_rejects_invalid_month(self):
        assert health_router._date_file_name_to_dt("2026.13.01_00.00_foo.eml") is None

    def test_interprets_fields_as_pacific_time(self):
        # 2026-04-22 17:30 PDT = 2026-04-23 00:30 UTC. If the parser
        # mistakenly treated fields as UTC we'd get 2026-04-22 17:30 UTC,
        # which is 7 hours earlier — see the bug this test prevents.
        dt = health_router._date_file_name_to_dt("2026.04.22_17.30_foo.eml")
        assert dt is not None
        assert dt.tzinfo is UTC
        assert dt == datetime(2026, 4, 23, 0, 30, tzinfo=UTC)

    def test_pst_offset_differs_from_pdt(self):
        # January is PST (UTC-8); April is PDT (UTC-7). Same local 12:00
        # maps to different UTC times — the ZoneInfo conversion handles DST.
        jan_dt = health_router._date_file_name_to_dt("2026.01.15_12.00_foo.eml")
        apr_dt = health_router._date_file_name_to_dt("2026.04.15_12.00_foo.eml")
        assert jan_dt is not None
        assert apr_dt is not None
        assert jan_dt.hour == 20  # 12 PST = 20 UTC
        assert apr_dt.hour == 19  # 12 PDT = 19 UTC


class TestDateFileNameParserNonPacific:
    """Verify `_date_file_name_to_dt` respects the configured app timezone."""

    @pytest.fixture
    def set_app_tz(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
        """Point the app config at a tmp file so we can flip timezones per-test."""
        import src.finance.app_config as app_config

        tmp_config = tmp_path / "config.json"
        monkeypatch.setattr(app_config, "_CONFIG_PATH", tmp_config)

        def _apply(tz_name: str) -> None:
            tmp_config.write_text(json.dumps({"timezone": tz_name}))
            app_config.invalidate_config_cache()

        yield _apply
        app_config.invalidate_config_cache()

    @pytest.mark.parametrize(
        ("tz_name", "date_file_name", "expected_utc"),
        [
            # Berlin CEST (April, UTC+2): local 02:00 → UTC 00:00 same day.
            ("Europe/Berlin", "2026.04.15_02.00_foo.eml", datetime(2026, 4, 15, 0, 0, tzinfo=UTC)),
            # Berlin midnight (April, CEST UTC+2): local 00:00 → UTC 22:00 previous day.
            ("Europe/Berlin", "2026.04.15_00.00_foo.eml", datetime(2026, 4, 14, 22, 0, tzinfo=UTC)),
            # Tokyo JST (no DST, UTC+9): local 09:00 → UTC 00:00 same day.
            ("Asia/Tokyo", "2026.04.15_09.00_foo.eml", datetime(2026, 4, 15, 0, 0, tzinfo=UTC)),
            # Tokyo midnight: local 00:00 → UTC 15:00 previous day.
            ("Asia/Tokyo", "2026.04.15_00.00_foo.eml", datetime(2026, 4, 14, 15, 0, tzinfo=UTC)),
        ],
    )
    def test_respects_configured_tz(
        self,
        set_app_tz: Callable[[str], None],
        tz_name: str,
        date_file_name: str,
        expected_utc: datetime,
    ) -> None:
        set_app_tz(tz_name)
        dt = health_router._date_file_name_to_dt(date_file_name)
        assert dt == expected_utc
