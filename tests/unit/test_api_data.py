"""End-to-end tests for /api/v1/data/{export,import/preview,import/commit}.

Uses a fresh SQLite backend per test (temp db path) so the export → wipe →
import round-trip exercises the real storage code path.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.api.dependencies import (
    get_budget_service,
    get_category_service,
    get_merchant_alias_service,
    get_override_service,
    get_parse_failure_store,
    get_transactions_db,
)
from src.api.main import app
from src.finance import demo_clock, staging_store
from src.finance.budget_service_local import BudgetServiceLocal
from src.finance.category_service_local import CategoryServiceLocal
from src.finance.merchant_alias_service_local import MerchantAliasServiceLocal
from src.finance.override_service_local import OverrideServiceLocal
from src.finance.parse_failure_store_local import ParseFailureStoreLocal
from src.finance.transaction_db_local import TransactionsDBLocal
from tests.asserts import assert_ok, assert_problem

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi.testclient import TestClient

FORWARDED_TO = "user@example.com"


@pytest.fixture
def isolated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Point every data dependency at a fresh SQLite DB + fresh stage dir."""
    db_path = tmp_path / "isolated.db"
    txn_db = TransactionsDBLocal(db_path=db_path)
    cat_svc = CategoryServiceLocal(db_path=db_path, user_id="default")
    ov_svc = OverrideServiceLocal(db_path=db_path, user_id="default")
    alias_svc = MerchantAliasServiceLocal(db_path=db_path, user_id="default")
    bud_svc = BudgetServiceLocal(db_path=db_path, user_id="default")
    pf_store = ParseFailureStoreLocal(db_path=db_path, user_id="default")

    app.dependency_overrides[get_transactions_db] = lambda: txn_db
    app.dependency_overrides[get_category_service] = lambda: cat_svc
    app.dependency_overrides[get_override_service] = lambda: ov_svc
    app.dependency_overrides[get_merchant_alias_service] = lambda: alias_svc
    app.dependency_overrides[get_budget_service] = lambda: bud_svc
    app.dependency_overrides[get_parse_failure_store] = lambda: pf_store

    monkeypatch.setattr(staging_store, "_STAGE_DIR", tmp_path / "imports")

    # Redirect every service's JSON-backup write target away from the real
    # bundled config/ dir and personal data/config/ dir so tests can't pollute
    # committed files.
    import src.finance.budget_service_base as budget_base
    import src.finance.category_service as category_svc_module
    import src.finance.merchant_alias_service as alias_svc_module
    import src.finance.override_service as override_svc_module

    fake_config_dir = tmp_path / "bundled_config"
    fake_personal_dir = tmp_path / "personal_config"
    monkeypatch.setattr(category_svc_module, "_CONFIG_DIR", fake_config_dir)
    monkeypatch.setattr(category_svc_module, "_PERSONAL_DIR", fake_personal_dir)
    monkeypatch.setattr(override_svc_module, "_CONFIG_DIR", fake_config_dir)
    monkeypatch.setattr(override_svc_module, "_PERSONAL_DIR", fake_personal_dir)
    monkeypatch.setattr(alias_svc_module, "_CONFIG_DIR", fake_config_dir)
    monkeypatch.setattr(alias_svc_module, "_PERSONAL_DIR", fake_personal_dir)
    monkeypatch.setattr(budget_base, "_CONFIG_DIR", fake_config_dir)
    monkeypatch.setattr(budget_base, "_PERSONAL_DIR", fake_personal_dir)

    # Neutralize demo mode for the duration of the test.
    import src.finance.app_config as app_config

    monkeypatch.setattr(
        app_config,
        "get_config",
        lambda: {"user_id": "default", "storage": "sqlite", "demo_mode": False},
    )

    return {
        "db": txn_db,
        "cat": cat_svc,
        "ov": ov_svc,
        "alias": alias_svc,
        "bud": bud_svc,
        "pf": pf_store,
    }

    # conftest auto-clears dependency_overrides between tests.


@pytest.fixture
def client(api_client: TestClient) -> TestClient:
    """Shared-app TestClient — delegates to the conftest ``api_client`` fixture.

    The isolated SQLite backend is wired via ``dependency_overrides`` on the same
    shared ``app`` this module imports, so the process-wide client is exactly
    right and no fresh app is needed. ``api_client`` already avoids the
    ``with``-context startup events (which would shut down the run_sync thread
    pool) and clears overrides on teardown.
    """
    return api_client


def _seed(services: dict[str, Any]) -> None:
    """Write one transaction + small config blobs into the isolated DB."""
    services["db"].add_transaction(
        {
            "forwarded_to": FORWARDED_TO,
            "file_name": "fixture.eml",
            "date": "02/15/2026 10:30 PST",
            "amount": 42.50,
            "company": "Test Store",
            "category": "groceries",
            "institution": "RBC",
            "transaction_type": "purchase",
            "subject": "Receipt",
            "body": "You spent $42.50",
        }
    )
    services["cat"].add_category("Backup Test Cat")
    services["ov"].put_override("Starbucks Store #123", "restaurant/dining")
    services["alias"].put_alias("sbux canada", "Starbucks")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    def test_returns_zip_with_expected_files(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        _seed(isolated_sqlite)
        resp = client.post("/api/v1/data/export")
        assert_ok(resp)
        assert resp.headers["content-type"] == "application/zip"
        assert "attachment" in resp.headers["content-disposition"]

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "transactions.csv" in names
        assert "config/categories.json" in names
        assert "config/overrides.json" in names
        assert "config/merchant_aliases.json" in names

    def test_empty_db_still_exports(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        resp = client.post("/api/v1/data/export")
        assert_ok(resp)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        # Transactions CSV is still present (header-only) even with no data.
        csv_text = zf.read("transactions.csv").decode()
        assert csv_text.startswith('"Date"')

    def test_backup_filename_uses_app_timezone_date(
        self, isolated_sqlite: dict[str, Any], client: TestClient, freeze_clock
    ) -> None:
        # The backup filename is stamped with app_today(). Frozen at
        # 2026-12-31 16:30 Pacific (== 2027-01-01 00:30 UTC), it must read the
        # Pacific date — a UTC container would misname the file 2027-01-01.
        freeze_clock(
            demo_clock,  # route reads app_today() → demo_clock
            at=datetime(2026, 12, 31, 16, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
        )
        resp = client.post("/api/v1/data/export")
        assert_ok(resp)
        assert 'filename="finance-backup-2026-12-31.zip"' in resp.headers["content-disposition"]

    def test_no_parse_failures_omits_file(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        _seed(isolated_sqlite)
        resp = client.post("/api/v1/data/export")
        assert_ok(resp)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        # No quarantined rows → no parse_failures.json, and the manifest count is 0.
        assert "parse_failures.json" not in set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["counts"]["parse_failures"] == 0

    def test_parse_failures_included_with_bodies(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        details = {
            "from_email": "alerts@rbc.com",
            "forwarded_to": FORWARDED_TO,
            "subject": "Drifted alert",
            "date": "02/15/2026 10:30 PST",
            "body": "a body the parsers could not read",
            "file_name": "drift.eml",
        }
        isolated_sqlite["pf"].record_failure(
            {
                "email_details": details,
                "email_json": json.dumps(details),
                "detected_institution": "RBC",
                "failure_stage": "extraction_empty",
                "status": "quarantined",
            }
        )

        resp = client.post("/api/v1/data/export")
        assert_ok(resp)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert "parse_failures.json" in set(zf.namelist())

        rows = json.loads(zf.read("parse_failures.json"))
        assert len(rows) == 1
        # Export is the one place the body travels — it must be present.
        assert "email_json" in rows[0]
        assert "a body the parsers could not read" in rows[0]["email_json"]
        assert rows[0]["detected_institution"] == "RBC"

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["counts"]["parse_failures"] == 1


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class TestPreview:
    def test_preview_of_fresh_backup_reports_all_duplicates(
        self, isolated_sqlite: dict[str, Any], client: TestClient
    ) -> None:
        _seed(isolated_sqlite)
        exp = client.post("/api/v1/data/export")
        resp = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("backup.zip", exp.content, "application/zip")},
        )
        data = assert_ok(resp)
        assert data["source_kind"] == "backup_zip"
        # Every row is a duplicate of itself.
        assert data["counts"]["duplicates"] == 1
        assert data["counts"]["new"] == 0
        # The seeded category list starts from the bundled JSON fallback plus
        # one addition, so we only verify it's non-empty.
        assert data["config"]["categories_count"]
        assert data["config"]["categories_count"] > 0
        assert len(data["token"]) == 32

    def test_preview_of_plain_csv(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        csv_body = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored"\n'
            '"03/01/2026 10:00","99.99","Totally New","groceries","RBC","purchase","","","","false"\n'
        )
        resp = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("tx.csv", csv_body.encode(), "text/csv")},
        )
        data = assert_ok(resp)
        assert data["source_kind"] == "plain_csv"
        assert data["counts"]["new"] == 1
        assert data["config"] is None

    def test_preview_rejects_unsupported_file(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        resp = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("bad.tar", b"junk", "application/x-tar")},
        )
        assert_problem(resp, 422)

    def test_preview_rejects_empty_upload(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        resp = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------


class TestCommit:
    def test_round_trip_skip(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        """Export → wipe → import(skip) → row reinserted."""
        _seed(isolated_sqlite)
        exp = client.post("/api/v1/data/export")

        db = isolated_sqlite["db"]
        item = db.scan_all_transactions()[0]
        db.permanently_delete(item["ForwardedTo"], item["DateFileName"])
        assert db.scan_all_transactions() == []

        prev = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("backup.zip", exp.content, "application/zip")},
        )
        token = prev.json()["token"]
        commit = client.post(
            "/api/v1/data/import/commit",
            json={"token": token, "strategy": "skip", "apply_config": True},
        )
        assert_ok(commit)
        result = commit.json()
        assert result["inserted"] == 1
        assert result["skipped"] == 0
        assert db.scan_all_transactions()
        assert result["config_applied"] is True

    def test_expired_token_returns_410(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        resp = client.post(
            "/api/v1/data/import/commit",
            json={"token": "a" * 32, "strategy": "skip"},
        )
        assert_problem(resp, 410)

    def test_invalid_token_returns_410(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        resp = client.post(
            "/api/v1/data/import/commit",
            json={"token": "not-a-valid-token", "strategy": "skip"},
        )
        assert_problem(resp, 410)

    def test_overwrite_strategy_replaces_duplicate(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        _seed(isolated_sqlite)
        # Include the ForwardedTo column so the imported hash matches the
        # seeded row exactly (hash inputs include ForwardedTo).
        csv_body = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored","ForwardedTo"\n'
            f'"02/15/2026 10:30","42.50","Test Store","restaurant/dining","RBC","purchase","","edited via import","","false","{FORWARDED_TO}"\n'
        )
        prev = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("tx.csv", csv_body.encode(), "text/csv")},
        )
        assert_ok(prev)
        token = prev.json()["token"]
        commit = client.post(
            "/api/v1/data/import/commit",
            json={"token": token, "strategy": "overwrite"},
        )
        assert_ok(commit)
        result = commit.json()
        assert result["updated"] == 1
        db = isolated_sqlite["db"]
        items = db.scan_all_transactions()
        assert len(items) == 1
        assert items[0]["Category"] == "restaurant/dining"
        assert items[0]["Comment"] == "edited via import"

    def test_keep_both_strategy_adds_second_row(self, isolated_sqlite: dict[str, Any], client: TestClient) -> None:
        _seed(isolated_sqlite)
        csv_body = (
            '"Date","Amount","Company","Category","Institution","Type","Name","Comment","Statement Source","Ignored","ForwardedTo"\n'
            f'"02/15/2026 10:30","42.50","Test Store","groceries","RBC","purchase","","","","false","{FORWARDED_TO}"\n'
        )
        prev = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("tx.csv", csv_body.encode(), "text/csv")},
        )
        token = prev.json()["token"]
        commit = client.post(
            "/api/v1/data/import/commit",
            json={"token": token, "strategy": "keep_both"},
        )
        assert_ok(commit)
        assert commit.json()["inserted"] == 1
        db = isolated_sqlite["db"]
        assert len(db.scan_all_transactions()) == 2


# ---------------------------------------------------------------------------
# Demo mode guard
# ---------------------------------------------------------------------------


class TestDemoModeGuard:
    def _force_demo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.finance.app_config as app_config

        monkeypatch.setattr(
            app_config,
            "get_config",
            lambda: {"user_id": "default", "storage": "sqlite", "demo_mode": True},
        )

    def test_export_blocked_in_demo(
        self, isolated_sqlite: dict[str, Any], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._force_demo(monkeypatch)
        resp = client.post("/api/v1/data/export")
        assert_problem(resp, 403)

    def test_preview_blocked_in_demo(
        self, isolated_sqlite: dict[str, Any], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._force_demo(monkeypatch)
        resp = client.post(
            "/api/v1/data/import/preview",
            files={"file": ("x.csv", b"Date\n", "text/csv")},
        )
        assert_problem(resp, 403)

    def test_commit_blocked_in_demo(
        self, isolated_sqlite: dict[str, Any], client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._force_demo(monkeypatch)
        resp = client.post(
            "/api/v1/data/import/commit",
            json={"token": "a" * 32, "strategy": "skip"},
        )
        assert_problem(resp, 403)


class TestS3BackupStatus:
    """GET /data/s3-backup-status merges config keys with the state file."""

    def _set_config(self, monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
        import src.finance.app_config as app_config

        base = {"user_id": "default", "storage": "sqlite", "demo_mode": False}
        base.update(overrides)
        monkeypatch.setattr(app_config, "get_config", lambda: base)

    def test_merges_config_and_state(self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from src.finance import s3_backup_shared

        state_path = tmp_path / "s3_backup_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "last_attempt_at": "2026-07-18T10:00:00Z",
                    "last_success_at": "2026-07-18T10:00:05Z",
                    "last_error": None,
                    "consecutive_failures": 0,
                    "uploaded_count": 12,
                    "deleted_count": 3,
                    "objects_total": 42,
                }
            )
        )
        monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", state_path)
        self._set_config(
            monkeypatch,
            s3_backup_enabled=True,
            s3_backup_bucket="my-backup",
            s3_backup_prefix="receipts",
        )

        resp = client.get("/api/v1/data/s3-backup-status")
        body = assert_ok(resp)
        assert body["enabled"] is True
        assert body["bucket"] == "my-backup"
        assert body["prefix"] == "receipts"
        assert body["last_attempt_at"] == "2026-07-18T10:00:00Z"
        assert body["last_success_at"] == "2026-07-18T10:00:05Z"
        assert body["last_error"] is None
        assert body["consecutive_failures"] == 0
        assert body["uploaded_count"] == 12
        assert body["deleted_count"] == 3
        assert body["objects_total"] == 42

    def test_missing_state_file_returns_zeroed_defaults(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.finance import s3_backup_shared

        monkeypatch.setattr(s3_backup_shared, "DEFAULT_STATE_PATH", tmp_path / "absent.json")
        self._set_config(monkeypatch)  # no s3 keys → config defaults absent

        resp = client.get("/api/v1/data/s3-backup-status")
        body = assert_ok(resp)
        assert body["enabled"] is False
        assert body["bucket"] is None
        assert body["prefix"] is None
        assert body["last_attempt_at"] is None
        assert body["last_success_at"] is None
        assert body["last_error"] is None
        assert body["consecutive_failures"] == 0
        assert body["uploaded_count"] == 0
        assert body["deleted_count"] == 0
        assert body["objects_total"] == 0

    def test_blocked_in_demo(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_config(monkeypatch, demo_mode=True)
        resp = client.get("/api/v1/data/s3-backup-status")
        assert_problem(resp, 403)


# ---------------------------------------------------------------------------
# Manifest sanity
# ---------------------------------------------------------------------------


def test_manifest_version_is_stable(isolated_sqlite: dict[str, Any], client: TestClient) -> None:
    _seed(isolated_sqlite)
    resp = client.post("/api/v1/data/export")
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["version"] == 1
    assert manifest["counts"]["transactions"] == 1
    assert manifest["counts"]["categories"] > 0


# ---------------------------------------------------------------------------
# _retrying_put — optimistic-lock read-modify-write with one retry
#
# Characterization tests pinning the exact return-dict contract and the
# read-version-fn re-read on retry. These pin behavior *before* the helper is
# reimplemented on the shared versioned_update helper.
# ---------------------------------------------------------------------------


class TestRetryingPut:
    def test_success_on_first_try(self) -> None:
        from src.api.routers.data import _retrying_put

        read_version = MagicMock(name="read_version", return_value=3)
        write = MagicMock(name="write", return_value=4)

        result = _retrying_put(write, read_version)

        assert result == {"status": "applied", "version": 4}
        # Read once, wrote once with the read version.
        read_version.assert_called_once_with()
        write.assert_called_once_with(3)

    def test_conflict_then_success_rereads_version(self) -> None:
        from src.api.routers.data import _retrying_put
        from src.finance.exceptions import VersionConflictError

        # First read yields stale version 2; second read (after conflict) yields 5.
        read_version = MagicMock(name="read_version", side_effect=[2, 5])
        write = MagicMock(name="write", side_effect=[VersionConflictError("stale"), 6])

        result = _retrying_put(write, read_version)

        assert result == {"status": "applied", "version": 6}
        # Version was re-read for the retry.
        assert read_version.call_count == 2
        assert [c.args for c in write.call_args_list] == [(2,), (5,)]

    def test_conflict_twice_returns_conflict_status(self) -> None:
        from src.api.routers.data import _retrying_put
        from src.finance.exceptions import VersionConflictError

        read_version = MagicMock(name="read_version", side_effect=[2, 5])
        write = MagicMock(
            name="write",
            side_effect=[VersionConflictError("stale"), VersionConflictError("still stale")],
        )

        result = _retrying_put(write, read_version)

        assert result == {"status": "conflict", "error": "still stale"}
        assert read_version.call_count == 2
        assert write.call_count == 2


# ---------------------------------------------------------------------------
# _apply_config — per-section config replacement during import commit
# ---------------------------------------------------------------------------


class TestApplyConfigBudgetYearKey:
    def test_invalid_budget_year_key_is_reported_not_raised(self) -> None:
        """A non-integer budget year key is captured as a per-year error, never
        raised, and never touches the budget service."""
        from src.api.routers.data import _apply_config
        from src.finance.backup_import import ParsedConfig

        config = ParsedConfig(budgets={"notayear": {"targets": {"categories": {}}, "groups": {}}})
        budget_svc = MagicMock(name="budget_svc")

        result = _apply_config(
            config,
            category_svc=MagicMock(name="category_svc"),
            override_svc=MagicMock(name="override_svc"),
            alias_svc=MagicMock(name="alias_svc"),
            budget_svc=budget_svc,
        )

        assert result["budgets"] == {"notayear": {"error": "invalid year key 'notayear'"}}
        # The bad year short-circuits before any write/read on the budget service.
        budget_svc.put_targets.assert_not_called()
        budget_svc.put_groups.assert_not_called()
        budget_svc.get_targets.assert_not_called()
        budget_svc.get_groups.assert_not_called()
