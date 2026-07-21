"""Dual-backend contract for the parse-failure (dead-letter) store.

Each scenario runs against *both* ``ParseFailureStore`` (DynamoDB via moto) and
``ParseFailureStoreLocal`` (SQLite via tmp_path), asserting identical observable
behavior. The moto store relies on lazy auto-create — the table is NOT
pre-provisioned, so the first ``record_failure`` must self-create it.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import boto3
import pytest
from moto import mock_aws

from src.finance import category_audit
from src.finance.parse_failure_store import ParseFailureStore
from src.finance.parse_failure_store_local import ParseFailureStoreLocal, failure_id_for

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def dyn_resource() -> Iterator[Any]:
    """In-memory moto DynamoDB with NO tables pre-created (lazy auto-create)."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        yield boto3.resource("dynamodb", region_name="us-west-2")


def _email(**overrides: Any) -> dict[str, Any]:
    base = {
        "forwarded_to": "user@example.com",
        "from_email": "alerts@rbc.com",
        "subject": "Transaction alert",
        "date": "02/15/2026 10:30 PST",
        "body": "A purchase of $42.50 at Test Store",
        "file_name": "fixture.eml",
    }
    base.update(overrides)
    return base


def _failure(email: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    email = email or _email()
    base: dict[str, Any] = {
        "email_details": email,
        "from_email": email.get("from_email"),
        "subject": email.get("subject"),
        "file_name": email.get("file_name"),
        "detected_institution": "RBC",
        "failure_stage": "extraction_empty",
        "status": "quarantined",
        "alert_classifier_result": None,
    }
    base.update(overrides)
    return base


class TestParseFailureStoreContract:
    @pytest.fixture(params=["dynamodb", "sqlite"])
    def store(self, request: pytest.FixtureRequest, dyn_resource: Any, tmp_path: Path) -> Any:
        if request.param == "dynamodb":
            # No table pre-created — assert lazy auto-create works.
            return ParseFailureStore(dyn_resource=dyn_resource)
        return ParseFailureStoreLocal(db_path=tmp_path / "failures.db")

    def test_record_then_get_roundtrip(self, store: Any) -> None:
        email = _email()
        failure_id = store.record_failure(_failure(email))
        assert failure_id == failure_id_for(email)

        got = store.get_failure(failure_id)
        assert got is not None
        assert got["id"] == failure_id
        assert got["detected_institution"] == "RBC"
        assert got["failure_stage"] == "extraction_empty"
        assert got["status"] == "quarantined"
        assert got["from_email"] == "alerts@rbc.com"
        # Full row carries the email_json body.
        assert "email_json" in got
        assert "Test Store" in got["email_json"]

    def test_get_missing_returns_none(self, store: Any) -> None:
        assert store.get_failure("pf_doesnotexist") is None

    def test_idempotent_re_record_no_duplicate(self, store: Any) -> None:
        email = _email()
        id1 = store.record_failure(_failure(email))
        id2 = store.record_failure(_failure(email))
        assert id1 == id2
        # Only one row exists.
        rows = store.list_failures()
        matching = [r for r in rows if r["id"] == id1]
        assert len(matching) == 1

    def test_list_excludes_email_json(self, store: Any) -> None:
        store.record_failure(_failure())
        rows = store.list_failures()
        assert len(rows) == 1
        assert "email_json" not in rows[0]

    def test_list_full_includes_email_json(self, store: Any) -> None:
        store.record_failure(_failure())
        rows = store.list_failures_full()
        assert len(rows) == 1
        # Unlike list_failures, the full listing keeps the body blob.
        assert "email_json" in rows[0]
        assert "Test Store" in rows[0]["email_json"]

    def test_list_full_filters_by_status(self, store: Any) -> None:
        a = store.record_failure(_failure(_email(subject="A")))
        store.record_failure(_failure(_email(subject="B")))
        store.set_status(a, "dismissed")

        quarantined = store.list_failures_full(status="quarantined")
        assert {r["status"] for r in quarantined} == {"quarantined"}
        assert a not in {r["id"] for r in quarantined}

        dismissed = store.list_failures_full(status="dismissed")
        assert [r["id"] for r in dismissed] == [a]

    def test_list_filters_by_status(self, store: Any) -> None:
        a = store.record_failure(_failure(_email(subject="A")))
        store.record_failure(_failure(_email(subject="B")))
        store.set_status(a, "dismissed")

        quarantined = store.list_failures(status="quarantined")
        assert {r["status"] for r in quarantined} == {"quarantined"}
        assert a not in {r["id"] for r in quarantined}

        dismissed = store.list_failures(status="dismissed")
        assert [r["id"] for r in dismissed] == [a]

    def test_set_status_transitions(self, store: Any) -> None:
        fid = store.record_failure(_failure())
        assert store.set_status(fid, "recovered", "2026.02.15_10.30_fixture.eml") is True
        got = store.get_failure(fid)
        assert got is not None
        assert got["status"] == "recovered"
        assert got["recovered_date_file_name"] == "2026.02.15_10.30_fixture.eml"

    def test_set_status_missing_returns_false(self, store: Any) -> None:
        assert store.set_status("pf_nope", "dismissed") is False

    def test_set_status_omitting_dfn_preserves_recovery_link(self, store: Any) -> None:
        # A failure recovered by a transaction (link set), then later dismissed
        # or re-touched without a dfn, must keep its link: set_status writes
        # recovered_date_file_name only when a non-None value is passed, so the
        # trail back to the recovering transaction is never silently erased.
        fid = store.record_failure(_failure())
        assert store.set_status(fid, "recovered", "2026.02.15_10.30_fixture.eml") is True

        # Dismiss with no dfn → status flips, link is preserved (not nulled).
        assert store.set_status(fid, "dismissed") is True
        got = store.get_failure(fid)
        assert got is not None
        assert got["status"] == "dismissed"
        assert got["recovered_date_file_name"] == "2026.02.15_10.30_fixture.eml"

        # An explicit non-None dfn still updates the link.
        assert store.set_status(fid, "recovered", "2026.03.01_09.00_other.eml") is True
        got = store.get_failure(fid)
        assert got is not None
        assert got["recovered_date_file_name"] == "2026.03.01_09.00_other.eml"

    def test_count_recent_quarantined(self, store: Any) -> None:
        assert store.count_recent_quarantined(days=7) == 0
        a = store.record_failure(_failure(_email(subject="A")))
        store.record_failure(_failure(_email(subject="B")))
        assert store.count_recent_quarantined(days=7) == 2
        # Dismissing a row drops it from the quarantined count.
        store.set_status(a, "dismissed")
        assert store.count_recent_quarantined(days=7) == 1

    def test_alert_classifier_result_roundtrip(self, store: Any) -> None:
        fid = store.record_failure(_failure(alert_classifier_result=True))
        got = store.get_failure(fid)
        assert got is not None
        assert got["alert_classifier_result"] is True

        rows = store.list_failures()
        assert rows[0]["alert_classifier_result"] is True

    def test_has_other_recent_failure_window_semantics(self, store: Any) -> None:
        # First quarantine for RBC: the just-written row is the only one →
        # no OTHER recent failure.
        store.record_failure(_failure(_email(subject="first")))
        assert store.has_other_recent_failure("RBC", hours=24) is False

        # Second quarantine for RBC within the window → there is now another.
        store.record_failure(_failure(_email(subject="second")))
        assert store.has_other_recent_failure("RBC", hours=24) is True

        # A different institution is unaffected.
        assert store.has_other_recent_failure("CIBC", hours=24) is False

    def test_latest_received_empty_store(self, store: Any) -> None:
        assert store.latest_received_by_institution() == {}

    def test_latest_received_max_per_institution(self, store: Any) -> None:
        # Two RBC arrivals and one CIBC arrival, with explicit received_at.
        store.record_failure(
            _failure(_email(subject="rbc-old"), detected_institution="RBC", received_at="2026-01-01T08:00:00-08:00")
        )
        store.record_failure(
            _failure(_email(subject="rbc-new"), detected_institution="RBC", received_at="2026-03-15T09:30:00-08:00")
        )
        store.record_failure(
            _failure(_email(subject="cibc"), detected_institution="CIBC", received_at="2026-02-10T12:00:00-08:00")
        )

        latest = store.latest_received_by_institution()
        assert latest == {
            "RBC": "2026-03-15T09:30:00-08:00",
            "CIBC": "2026-02-10T12:00:00-08:00",
        }

    def test_latest_received_counts_any_status(self, store: Any) -> None:
        # An arrival is evidence regardless of status: dismiss it and it still
        # counts (the bank still spoke).
        fid = store.record_failure(
            _failure(
                _email(subject="dismissed"), detected_institution="Simplii", received_at="2026-04-01T00:00:00-07:00"
            )
        )
        store.set_status(fid, "dismissed")
        latest = store.latest_received_by_institution()
        assert latest == {"Simplii": "2026-04-01T00:00:00-07:00"}

    def test_latest_received_excludes_null_institution(self, store: Any) -> None:
        # A quarantine row with no detected institution contributes nothing.
        store.record_failure(
            _failure(_email(subject="unknown"), detected_institution=None, received_at="2026-05-01T00:00:00-07:00")
        )
        store.record_failure(
            _failure(_email(subject="rbc"), detected_institution="RBC", received_at="2026-05-02T00:00:00-07:00")
        )
        assert store.latest_received_by_institution() == {"RBC": "2026-05-02T00:00:00-07:00"}

    def test_idempotent_re_record_dateless_email(self, store: Any) -> None:
        # No date header: the SK token must still be stable so a redelivered
        # email upserts instead of duplicating (regression: wall-clock fallback
        # gave the same email a new SK per recording).
        email = _email(date=None)
        id1 = store.record_failure(_failure(email))
        id2 = store.record_failure(_failure(email))
        assert id1 == id2
        rows = store.list_failures()
        assert [r["id"] for r in rows] == [id1]


class TestParseFailureStoreLegacyDuplicates:
    """DynamoDB-only: items written before the date-less SK token was stable
    can share a FailureId across different SKs; reads must collapse them."""

    def test_reads_dedupe_legacy_duplicate_ids(self, dyn_resource: Any) -> None:
        store = ParseFailureStore(dyn_resource=dyn_resource)
        email = _email(date=None)
        fid = store.record_failure(_failure(email))

        # Simulate the legacy second item: same FailureId, different SK,
        # newer UpdatedAt and a diverged status.
        newer = "2099-01-01T00:00:00"
        store.table.put_item(
            Item={
                "PK": store.USER_PK,
                "SK": f"FAIL#{newer}#{fid}",
                "FailureId": fid,
                "ReceivedAt": newer,
                "FromEmail": email["from_email"],
                "Subject": email["subject"],
                "FailureStage": "no_parser_match",
                "Status": "dismissed",
                "EmailJson": "{}",
                "CreatedAt": newer,
                "UpdatedAt": newer,
            }
        )

        rows = store.list_failures()
        assert [r["id"] for r in rows] == [fid]
        # The most recently updated item wins everywhere.
        assert rows[0]["status"] == "dismissed"
        got = store.get_failure(fid)
        assert got is not None
        assert got["status"] == "dismissed"


class TestParseFailureStoreLocalPrune:
    """SQLite-only: prune-on-write removes old terminal-status rows."""

    def test_prune_on_write_removes_old_dismissed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = ParseFailureStoreLocal(db_path=tmp_path / "failures.db")

        # Record an old failure, then mark it dismissed, then back-date its
        # received_at to >90 days ago directly so prune-on-write will catch it.
        old_id = store.record_failure(_failure(_email(subject="old")))
        store.set_status(old_id, "dismissed")
        old_received = (datetime.fromisoformat(category_audit.now_local_iso()) - timedelta(days=120)).isoformat()
        conn = store._connect()
        try:
            conn.execute(
                "UPDATE parse_failures SET received_at = ? WHERE id = ?",
                (old_received, old_id),
            )
            conn.commit()
        finally:
            conn.close()

        # A fresh record triggers the opportunistic prune.
        store.record_failure(_failure(_email(subject="new")))

        assert store.get_failure(old_id) is None
        ids = {r["id"] for r in store.list_failures()}
        assert old_id not in ids

    def test_prune_keeps_quarantined_even_if_old(self, tmp_path: Path) -> None:
        store = ParseFailureStoreLocal(db_path=tmp_path / "failures.db")
        old_id = store.record_failure(_failure(_email(subject="old-quarantined")))
        old_received = (datetime.fromisoformat(category_audit.now_local_iso()) - timedelta(days=200)).isoformat()
        conn = store._connect()
        try:
            conn.execute(
                "UPDATE parse_failures SET received_at = ? WHERE id = ?",
                (old_received, old_id),
            )
            conn.commit()
        finally:
            conn.close()

        store.record_failure(_failure(_email(subject="new")))
        # Quarantined rows are never pruned regardless of age.
        assert store.get_failure(old_id) is not None
