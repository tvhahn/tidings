"""Tests for /api/v1/parse-failures/* — the dead-letter quarantine API.

Two flavors:

- Router shape tests use the ``mock_run_sync`` indirect fixture (patches
  ``parse_failures.run_sync``) + a Mock store, so list/detail/404/dismiss and
  the status-filter validation error are exercised without real storage.
- One retry happy-path test wires real SQLite stores via ``dependency_overrides``
  (no run_sync mocking) and asserts a parseable RBC email lands as a transaction
  and the row flips to ``retried``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from src.api.dependencies import (
    get_override_service,
    get_parse_failure_store,
    get_transactions_db,
)
from src.api.main import app
from src.finance.override_service_local import OverrideServiceLocal
from src.finance.parse_failure_store_local import ParseFailureStoreLocal
from src.finance.transaction_db_local import TransactionsDBLocal

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi.testclient import TestClient

from tests.asserts import assert_ok, assert_problem
from tests.conftest import read_file


def _summary_row(**overrides: Any) -> dict[str, Any]:
    """A store summary dict (as list_failures returns) with sane defaults."""
    row = {
        "id": "pf_abc123",
        "received_at": "2026-06-09T10:00:00-07:00",
        "from_email": "alerts@rbc.com",
        "subject": "A purchase was made",
        "file_name": "msg.eml",
        "detected_institution": "RBC",
        "failure_stage": "extraction_empty",
        "status": "quarantined",
        "recovered_date_file_name": None,
        "alert_classifier_result": None,
        "created_at": "2026-06-09T10:00:00-07:00",
        "updated_at": "2026-06-09T10:00:00-07:00",
    }
    row.update(overrides)
    return row


def _full_row(**overrides: Any) -> dict[str, Any]:
    row = _summary_row()
    row["email_json"] = json.dumps({"body": "the original email body", "from_email": "alerts@rbc.com"})
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Router shape tests (mocked store + run_sync)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mock_run_sync", ["parse_failures"], indirect=True)
class TestListParseFailures:
    def test_returns_summaries(self, mock_run_sync, api_client) -> None:
        store = MagicMock()
        app.dependency_overrides[get_parse_failure_store] = lambda: store
        mock_run_sync.return_value = [_summary_row(), _summary_row(id="pf_def456")]

        resp = api_client.get("/api/v1/parse-failures")
        assert_ok(resp)
        data = resp.json()
        assert data["count"] == 2
        assert len(data["failures"]) == 2
        first = data["failures"][0]
        assert first["id"] == "pf_abc123"
        assert first["detected_institution"] == "RBC"
        # Summary must not leak the body / email_json.
        assert "body" not in first
        assert "email_json" not in first

    def test_empty_list(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        mock_run_sync.return_value = []
        resp = api_client.get("/api/v1/parse-failures")
        assert_ok(resp)
        assert resp.json() == {"count": 0, "failures": []}

    def test_status_filter_passed_through(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        mock_run_sync.return_value = []
        resp = api_client.get("/api/v1/parse-failures?status=dismissed&limit=5")
        assert_ok(resp)
        # run_sync receives store.list_failures, status, limit
        args = mock_run_sync.call_args.args
        assert args[1] == "dismissed"
        assert args[2] == 5

    def test_invalid_status_is_422(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        resp = api_client.get("/api/v1/parse-failures?status=bogus")
        assert_problem(resp, 422)
        # The enum is validated before run_sync ever runs.
        mock_run_sync.assert_not_called()


@pytest.mark.parametrize("mock_run_sync", ["parse_failures"], indirect=True)
class TestGetParseFailure:
    def test_detail_includes_body(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        mock_run_sync.return_value = _full_row()
        resp = api_client.get("/api/v1/parse-failures/pf_abc123")
        assert_ok(resp)
        data = resp.json()
        assert data["id"] == "pf_abc123"
        assert data["body"] == "the original email body"
        # email_json itself is not part of the response surface.
        assert "email_json" not in data

    def test_missing_is_404(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        mock_run_sync.return_value = None
        resp = api_client.get("/api/v1/parse-failures/pf_nope")
        assert_problem(resp, 404)
        assert resp.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize("mock_run_sync", ["parse_failures"], indirect=True)
class TestDismissParseFailure:
    def test_dismiss_ok(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        mock_run_sync.return_value = True
        resp = api_client.delete("/api/v1/parse-failures/pf_abc123")
        assert_ok(resp)
        assert resp.json() == {"failure_id": "pf_abc123", "status": "dismissed"}

    def test_dismiss_missing_is_404(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        mock_run_sync.return_value = False
        resp = api_client.delete("/api/v1/parse-failures/pf_nope")
        assert_problem(resp, 404)


@pytest.mark.parametrize("mock_run_sync", ["parse_failures"], indirect=True)
class TestRetryParseFailureShapes:
    def test_retry_missing_is_404(self, mock_run_sync, api_client) -> None:
        app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
        # First run_sync call is get_failure → None.
        mock_run_sync.return_value = None
        resp = api_client.post("/api/v1/parse-failures/pf_nope/retry")
        assert_problem(resp, 404)


# ---------------------------------------------------------------------------
# Retry happy-path — real SQLite stores, no run_sync mocking
# ---------------------------------------------------------------------------

_RBC_PURCHASE_TXT = "tests/test_data/rbc/2024.10.22_15.45_abc123def456_rbc_purchase.txt"


@pytest.fixture
def retry_env(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Real SQLite parse-failure store + transactions DB wired via overrides."""
    db_path = tmp_path / "retry.db"
    store = ParseFailureStoreLocal(db_path=db_path, user_id="default")
    txn_db = TransactionsDBLocal(db_path=db_path)
    ov_svc = OverrideServiceLocal(db_path=db_path, user_id="default")

    app.dependency_overrides[get_parse_failure_store] = lambda: store
    app.dependency_overrides[get_transactions_db] = lambda: txn_db
    app.dependency_overrides[get_override_service] = lambda: ov_svc

    return {"store": store, "db": txn_db, "ov_svc": ov_svc, "db_path": db_path}
    # conftest auto-clears dependency_overrides.


@pytest.fixture
def retry_client(api_client: TestClient) -> TestClient:
    """Shared-app TestClient — delegates to the conftest ``api_client`` fixture.

    Real SQLite stores are wired via ``dependency_overrides`` on the same shared
    ``app`` this module imports, so the process-wide client is exactly right; no
    fresh app is needed. ``api_client`` skips the ``with``-context startup events
    and clears overrides on teardown.
    """
    return api_client


def test_retry_parses_and_records_transaction(retry_env: dict[str, Any], retry_client: TestClient) -> None:
    store = retry_env["store"]
    body = read_file(_RBC_PURCHASE_TXT)
    # The body contains "RBC" so parse_email_body resolves it by body text even
    # without a recognized sender domain.
    email_details = {
        "from_email": "noreply@example.com",
        "to_email": "user@example.com",
        "forwarded_to": "user@example.com",
        "subject": "A purchase was made",
        "date": "October 22, 2024 15:45 PST",
        "body": body,
        "file_name": "rbc_purchase.eml",
        "user_id": "default",
    }
    failure_id = store.record_failure(
        {
            "email_details": email_details,
            "email_json": json.dumps(email_details),
            "detected_institution": "RBC",
            "failure_stage": "extraction_empty",
            "status": "quarantined",
        }
    )

    resp = retry_client.post(f"/api/v1/parse-failures/{failure_id}/retry")
    assert_ok(resp)
    data = resp.json()
    assert data["status"] == "created"
    assert data["date_file_name"]

    # The transaction actually landed.
    txns = retry_env["db"].scan_all_transactions()
    assert any(t.get("Company") == "Costco Wholesale" for t in txns), txns

    # Row flipped to retried with the recovered date_file_name.
    row = store.get_failure(failure_id)
    assert row is not None
    assert row["status"] == "retried"
    assert row["recovered_date_file_name"] == data["date_file_name"]


def test_retry_duplicate_marks_retried(retry_env: dict[str, Any], retry_client: TestClient) -> None:
    store = retry_env["store"]
    body = read_file(_RBC_PURCHASE_TXT)
    email_details = {
        "from_email": "noreply@example.com",
        "forwarded_to": "user@example.com",
        "subject": "A purchase was made",
        "date": "October 22, 2024 15:45 PST",
        "body": body,
        "file_name": "rbc_purchase.eml",
        "user_id": "default",
    }
    failure_id = store.record_failure(
        {
            "email_details": email_details,
            "email_json": json.dumps(email_details),
            "detected_institution": "RBC",
            "failure_stage": "extraction_empty",
        }
    )

    # First retry creates it.
    first = retry_client.post(f"/api/v1/parse-failures/{failure_id}/retry")
    assert first.json()["status"] == "created"

    # Re-quarantine the same email and retry again → duplicate.
    failure_id2 = store.record_failure(
        {
            "email_details": email_details,
            "email_json": json.dumps(email_details),
            "detected_institution": "RBC",
            "failure_stage": "extraction_empty",
            "status": "quarantined",
        }
    )
    second = retry_client.post(f"/api/v1/parse-failures/{failure_id2}/retry")
    assert_ok(second)
    assert second.json()["status"] == "duplicate"
    assert store.get_failure(failure_id2)["status"] == "retried"


def test_retry_unparseable_stays_quarantined(retry_env: dict[str, Any], retry_client: TestClient) -> None:
    store = retry_env["store"]
    email_details = {
        "from_email": "newsletter@example.com",
        "forwarded_to": "user@example.com",
        "subject": "Weekly digest",
        "date": "October 22, 2024 15:45 PST",
        "body": "Nothing here looks like a bank alert at all.",
        "file_name": "digest.eml",
        "user_id": "default",
    }
    failure_id = store.record_failure(
        {
            "email_details": email_details,
            "email_json": json.dumps(email_details),
            "failure_stage": "no_parser_match",
        }
    )

    resp = retry_client.post(f"/api/v1/parse-failures/{failure_id}/retry")
    assert_ok(resp)
    assert resp.json()["status"] == "still_failing"
    assert store.get_failure(failure_id)["status"] == "quarantined"


# ---------------------------------------------------------------------------
# Manual resolve — record a hand-entered transaction and mark the row resolved
# ---------------------------------------------------------------------------


def _quarantined_failure(store: ParseFailureStoreLocal, **overrides: Any) -> str:
    """Record a minimal quarantined row and return its id."""
    email_details = {
        "from_email": "alerts@cibc.com",
        "forwarded_to": "user@example.com",
        "subject": "A transaction you can't auto-read",
        "body": "Some garbled body the parsers can't read.",
        "file_name": "weird.eml",
        "user_id": "default",
    }
    payload = {
        "email_details": email_details,
        "email_json": json.dumps(email_details),
        "detected_institution": "CIBC",
        "failure_stage": "no_parser_match",
        "status": "quarantined",
    }
    payload.update(overrides)
    return store.record_failure(payload)


def test_resolve_creates_transaction_and_marks_recovered(retry_env: dict[str, Any], retry_client: TestClient) -> None:
    store = retry_env["store"]
    failure_id = _quarantined_failure(store)

    resp = retry_client.post(
        f"/api/v1/parse-failures/{failure_id}/resolve",
        json={
            "date": "2026-06-21",
            "amount": 73.21,
            "company": "Corner Market",
            "category": "groceries",
            "transaction_type": "purchase",
        },
    )
    assert_ok(resp)
    data = resp.json()
    assert data["status"] == "created"
    assert data["date_file_name"]

    # The hand-entered transaction actually landed, with the row's detected
    # institution defaulted in (no institution was supplied in the request).
    txns = retry_env["db"].scan_all_transactions()
    match = next((t for t in txns if t.get("Company") == "Corner Market"), None)
    assert match is not None, txns
    assert match.get("Institution") == "CIBC"

    # Row left the active queue: terminal "recovered" status carrying the dfn.
    row = store.get_failure(failure_id)
    assert row is not None
    assert row["status"] == "recovered"
    assert row["recovered_date_file_name"] == data["date_file_name"]


def test_resolve_preserves_transaction_type(retry_env: dict[str, Any], retry_client: TestClient) -> None:
    # D2 is locked because failed parses skew toward deposits / e-transfers /
    # refunds, so silently defaulting everything to "purchase" would store
    # wrong-sign money. Confirm a non-purchase type survives to storage rather
    # than asserting only Company/Institution (which a default-to-purchase
    # regression would still pass).
    store = retry_env["store"]
    failure_id = _quarantined_failure(store)

    resp = retry_client.post(
        f"/api/v1/parse-failures/{failure_id}/resolve",
        json={
            "date": "2026-06-21",
            "amount": 500.00,
            "company": "Acme Payroll",
            "category": "income",
            "transaction_type": "deposit",
        },
    )
    assert_ok(resp)
    assert resp.json()["status"] == "created"

    txns = retry_env["db"].scan_all_transactions()
    match = next((t for t in txns if t.get("Company") == "Acme Payroll"), None)
    assert match is not None, txns
    assert match.get("TransactionType") == "deposit"


def test_resolve_duplicate_marks_recovered_without_dfn(retry_env: dict[str, Any], retry_client: TestClient) -> None:
    store = retry_env["store"]
    body = {
        "date": "2026-06-21",
        "amount": 12.00,
        "company": "Repeat Co",
        "category": "miscellaneous",
        "transaction_type": "purchase",
    }

    # First resolve creates the transaction.
    first_id = _quarantined_failure(store)
    first = retry_client.post(f"/api/v1/parse-failures/{first_id}/resolve", json=body)
    assert first.json()["status"] == "created"

    # A second quarantined row with the identical hand-entered values dedupes.
    second_id = _quarantined_failure(store)
    second = retry_client.post(f"/api/v1/parse-failures/{second_id}/resolve", json=body)
    assert_ok(second)
    assert second.json()["status"] == "duplicate"
    assert second.json()["date_file_name"] is None

    # Even on a duplicate the row leaves the queue so it can't dead-end. The
    # failure id is content-deterministic, so this is the same row the first
    # resolve already recovered: a duplicate resolve must preserve the existing
    # link to that transaction rather than erasing it (the dfn is only the
    # *response* field that's None — see above).
    row = store.get_failure(second_id)
    assert row is not None
    assert row["status"] == "recovered"
    assert row["recovered_date_file_name"] == first.json()["date_file_name"]


def test_resolve_db_reject_yields_422(retry_env: dict[str, Any], retry_client: TestClient) -> None:
    # A real store provides the row, but a stubbed DB rejects the write — the
    # row must stay quarantined and the caller gets a calm 422.
    store = retry_env["store"]
    failure_id = _quarantined_failure(store)

    rejecting_db = MagicMock()
    rejecting_db.add_transaction.return_value = None
    app.dependency_overrides[get_transactions_db] = lambda: rejecting_db

    resp = retry_client.post(
        f"/api/v1/parse-failures/{failure_id}/resolve",
        json={"date": "2026-06-21", "amount": 5.0, "company": "X", "category": "groceries"},
    )
    assert_problem(resp, 422)
    assert "check the values" in resp.json()["error"]
    assert store.get_failure(failure_id)["status"] == "quarantined"


@pytest.mark.parametrize("mock_run_sync", ["parse_failures"], indirect=True)
def test_resolve_missing_is_404(mock_run_sync, api_client) -> None:
    app.dependency_overrides[get_parse_failure_store] = lambda: MagicMock()
    # First run_sync call is get_failure → None.
    mock_run_sync.return_value = None
    resp = api_client.post(
        "/api/v1/parse-failures/pf_nope/resolve",
        json={"date": "2026-06-21", "amount": 5.0, "company": "X"},
    )
    assert_problem(resp, 404)


# ---------------------------------------------------------------------------
# to-fixture — write a scrubbed .txt + .json pair (dev-checkout gated)
# ---------------------------------------------------------------------------

import src.finance.app_config as app_config  # noqa: E402
from src.api.routers import parse_failures as pf_router  # noqa: E402


def _force_config(monkeypatch: Any, *, demo_mode: bool) -> None:
    """Pin app_config.get_config to a fixed demo_mode for the to-fixture gate."""
    monkeypatch.setattr(app_config, "get_config", lambda: {"demo_mode": demo_mode})


def _seed_quarantined(store: ParseFailureStoreLocal, *, body: str, **overrides: Any) -> str:
    subject = overrides.pop("subject", "A purchase was made")
    email_details = {
        "from_email": overrides.pop("from_email", "alerts@somebank.example"),
        "forwarded_to": overrides.pop("forwarded_to", "mira.forward@example.com"),
        "subject": subject,
        "date": "October 22, 2024 15:45 PST",
        "body": body,
        # Distinct file_name per seed so parsed transactions can't collide on the
        # (forwarded_to, date_file_name) primary key when dates coincide.
        "file_name": f"{subject.replace(' ', '_')}.eml",
        "user_id": "default",
    }
    payload: dict[str, Any] = {
        "email_details": email_details,
        "email_json": json.dumps(email_details),
        "detected_institution": overrides.pop("detected_institution", "RBC"),
        "failure_stage": "no_parser_match",
        "status": "quarantined",
    }
    payload.update(overrides)
    return store.record_failure(payload)


def test_to_fixture_missing_is_404(retry_env, retry_client, monkeypatch) -> None:
    _force_config(monkeypatch, demo_mode=False)
    resp = retry_client.post("/api/v1/parse-failures/pf_nope/to-fixture", json={})
    assert_problem(resp, 404)


def test_to_fixture_403_when_not_git_checkout(retry_env, retry_client, monkeypatch) -> None:
    _force_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(pf_router, "_is_git_checkout", lambda: False)
    store = retry_env["store"]
    fid = _seed_quarantined(store, body="A purchase of $10.00 was made.")
    resp = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={})
    assert_problem(resp, 403)


def test_to_fixture_403_in_demo_mode(retry_env, retry_client, monkeypatch) -> None:
    _force_config(monkeypatch, demo_mode=True)
    store = retry_env["store"]
    fid = _seed_quarantined(store, body="A purchase of $10.00 was made.")
    resp = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={})
    assert_problem(resp, 403)


def test_to_fixture_422_when_no_institution(retry_env, retry_client, monkeypatch) -> None:
    _force_config(monkeypatch, demo_mode=False)
    store = retry_env["store"]
    # No detected_institution and no request-body institution → nothing to file under.
    fid = _seed_quarantined(store, body="Some body.", detected_institution=None)
    resp = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={})
    assert_problem(resp, 422)


def test_to_fixture_happy_path_writes_scrubbed_pair(retry_env, retry_client, monkeypatch, tmp_path) -> None:
    _force_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(pf_router, "_test_data_root", lambda: tmp_path)
    store = retry_env["store"]
    body = "From: alerts@personalbank.com\nA purchase of $1,234.56 was charged. Contact john.doe@personalmail.com."
    fid = _seed_quarantined(store, body=body, forwarded_to="mira.forward@example.com", subject="A purchase was made")

    resp = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={"institution": "Maple Trust"})
    assert_ok(resp)
    data = resp.json()
    assert data["txt_path"] == "tests/test_data/maple_trust/a_purchase_was_made.txt"
    assert data["json_path"] == "tests/test_data/maple_trust/a_purchase_was_made.json"

    txt_file = tmp_path / "maple_trust" / "a_purchase_was_made.txt"
    json_file = tmp_path / "maple_trust" / "a_purchase_was_made.json"
    assert txt_file.exists()
    assert json_file.exists()

    scrubbed = txt_file.read_text(encoding="utf-8")
    assert "john.doe@personalmail.com" not in scrubbed
    assert "$1,234.56" in scrubbed  # amount preserved

    skeleton = json.loads(json_file.read_text(encoding="utf-8"))
    assert skeleton["institution"] == "Maple Trust"
    assert skeleton["email_filepath"] == "tests/test_data/maple_trust/a_purchase_was_made.txt"
    assert skeleton["amount"] == "TODO"
    assert skeleton["company"] == "TODO"
    assert skeleton["transaction_type"] == "TODO"
    assert skeleton["name"] == "TODO"


def test_to_fixture_detected_pc_financial_slugs_dir(retry_env, retry_client, monkeypatch, tmp_path) -> None:
    # A detected institution with a space ("PC Financial") must slugify to the
    # canonical dir (pc_financial), never land in a "pc financial" folder.
    _force_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(pf_router, "_test_data_root", lambda: tmp_path)
    store = retry_env["store"]
    fid = _seed_quarantined(
        store,
        body="A purchase of $10.00 was made.",
        subject="Account activity",
        detected_institution="PC Financial",
    )

    # No request-body institution → falls back to the detected one.
    resp = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={})
    assert_ok(resp)
    data = resp.json()
    assert data["txt_path"] == "tests/test_data/pc_financial/account_activity.txt"
    assert data["json_path"] == "tests/test_data/pc_financial/account_activity.json"
    assert (tmp_path / "pc_financial" / "account_activity.txt").exists()

    skeleton = json.loads((tmp_path / "pc_financial" / "account_activity.json").read_text(encoding="utf-8"))
    assert skeleton["institution"] == "PC Financial"
    assert skeleton["email_filepath"] == "tests/test_data/pc_financial/account_activity.txt"


def test_to_fixture_422_when_institution_slug_is_empty(retry_env, retry_client, monkeypatch, tmp_path) -> None:
    # An institution of only non-Latin/symbol chars passes the truthiness guard
    # but slugifies to "" — that must 422, not write into tests/test_data/ root.
    _force_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(pf_router, "_test_data_root", lambda: tmp_path)
    store = retry_env["store"]
    fid = _seed_quarantined(store, body="A purchase of $10.00 was made.", subject="x")

    resp = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={"institution": "永豐銀行"})
    assert_problem(resp, 422)
    # No fixture files were written anywhere under the root (tmp_path also holds
    # the retry DB, so assert on the absence of .txt/.json fixtures specifically).
    assert list(tmp_path.rglob("*.txt")) == []
    assert list(tmp_path.rglob("*.json")) == []


def test_to_fixture_same_subject_second_email_disambiguates(retry_env, retry_client, monkeypatch, tmp_path) -> None:
    # Bank alerts repeat subjects verbatim. A second, different email with the
    # same subject must get a suffixed filename, not a 409.
    _force_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(pf_router, "_test_data_root", lambda: tmp_path)
    store = retry_env["store"]
    subject = "INTERAC e-Transfer: You received money"
    fid1 = _seed_quarantined(store, body="You received $10.00.", subject=subject, from_email="a@bank.example")
    fid2 = _seed_quarantined(store, body="You received $20.00.", subject=subject, from_email="b@bank.example")

    first = retry_client.post(f"/api/v1/parse-failures/{fid1}/to-fixture", json={"institution": "Maple Trust"})
    assert_ok(first)
    second = retry_client.post(f"/api/v1/parse-failures/{fid2}/to-fixture", json={"institution": "Maple Trust"})
    assert_ok(second)

    base = first.json()["txt_path"]
    suffixed = second.json()["txt_path"]
    assert base == "tests/test_data/maple_trust/interac_etransfer_you_received_money.txt"
    assert suffixed != base
    assert suffixed.startswith("tests/test_data/maple_trust/interac_etransfer_you_received_money_")
    # Both pairs actually exist on disk.
    assert (tmp_path / "maple_trust" / "interac_etransfer_you_received_money.txt").exists()
    assert (tmp_path / base.removeprefix("tests/test_data/")).exists()
    assert (tmp_path / suffixed.removeprefix("tests/test_data/")).exists()


def test_to_fixture_409_when_suffix_also_collides(retry_env, retry_client, monkeypatch, tmp_path) -> None:
    # Same failure id repeatedly: call 1 writes the base slug, call 2 writes the
    # id-suffixed slug, call 3 finds both taken (same id → same suffix) → 409.
    _force_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(pf_router, "_test_data_root", lambda: tmp_path)
    store = retry_env["store"]
    fid = _seed_quarantined(store, body="A purchase of $10.00 was made.", subject="Weekly alert")

    first = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={"institution": "Maple Trust"})
    assert_ok(first)
    second = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={"institution": "Maple Trust"})
    assert_ok(second)
    assert second.json()["txt_path"] != first.json()["txt_path"]
    third = retry_client.post(f"/api/v1/parse-failures/{fid}/to-fixture", json={"institution": "Maple Trust"})
    assert_problem(third, 409)


# ---------------------------------------------------------------------------
# retry-all — bulk retry across a filtered set of quarantined rows
# ---------------------------------------------------------------------------

_RBC_ETRANSFER_TXT = "tests/test_data/rbc/2024.11.13_10.35_rbc020mmm121_rbc_e-transfer.txt"


def test_retry_all_422_without_filter(retry_env, retry_client) -> None:
    resp = retry_client.post("/api/v1/parse-failures/retry-all", json={})
    assert_problem(resp, 422)


def test_retry_all_counts_outcomes(retry_env, retry_client) -> None:
    store = retry_env["store"]
    purchase = read_file(_RBC_PURCHASE_TXT)
    etransfer = read_file(_RBC_ETRANSFER_TXT)

    # created: parseable, never retried.
    _seed_quarantined(store, body=purchase, subject="rbc purchase")
    # duplicate: parseable, but its transaction already exists — retry it once to
    # create the row, then re-arm the failure to quarantined for the sweep.
    dup_id = _seed_quarantined(store, body=etransfer, subject="rbc etransfer")
    first = retry_client.post(f"/api/v1/parse-failures/{dup_id}/retry")
    assert first.json()["status"] == "created"
    store.set_status(dup_id, "quarantined")
    # still_failing: unparseable.
    _seed_quarantined(store, body="Nothing bank-like here at all.", subject="junk")
    # A non-matching institution must be left untouched by an RBC sweep.
    cibc_id = _seed_quarantined(store, body="Unreadable body.", detected_institution="CIBC", subject="cibc")

    resp = retry_client.post("/api/v1/parse-failures/retry-all", json={"institution": "RBC"})
    assert_ok(resp)
    data = resp.json()
    assert data["retried"] == 3
    assert data["created"] == 1
    assert data["duplicates"] == 1
    assert data["still_failing"] == 1
    # Invariant: retried counts only processed rows, so it must equal the sum.
    assert data["retried"] == data["created"] + data["duplicates"] + data["still_failing"]

    # The CIBC row was never in the sweep — still quarantined.
    assert store.get_failure(cibc_id)["status"] == "quarantined"


def test_retry_all_survives_corrupt_row(retry_env, retry_client) -> None:
    # A row whose stored email_json is corrupt makes _retry_sync raise
    # (json.loads on non-JSON → JSONDecodeError). The sweep must not 500: it logs
    # the row, counts it still_failing, leaves it quarantined, finishes the rest.
    store = retry_env["store"]
    purchase = read_file(_RBC_PURCHASE_TXT)

    # One healthy parseable row → created.
    _seed_quarantined(store, body=purchase, subject="rbc purchase")
    # One row with its email_json corrupted directly in the DB → raises on retry.
    bad_id = _seed_quarantined(store, body="whatever", subject="corrupt")
    conn = store._connect()
    try:
        conn.execute("UPDATE parse_failures SET email_json = ? WHERE id = ?", ("not valid json{", bad_id))
        conn.commit()
    finally:
        conn.close()

    resp = retry_client.post("/api/v1/parse-failures/retry-all", json={"institution": "RBC"})
    assert_ok(resp)
    data = resp.json()
    assert data["created"] == 1
    assert data["still_failing"] == 1
    # Arithmetic holds even with a raising row.
    assert data["retried"] == data["created"] + data["duplicates"] + data["still_failing"]
    # The corrupt row genuinely stays quarantined.
    assert store.get_failure(bad_id)["status"] == "quarantined"


def test_retry_all_from_domain_suffix_match(retry_env, retry_client) -> None:
    store = retry_env["store"]
    purchase = read_file(_RBC_PURCHASE_TXT)
    # Sender on a subdomain of the filter; no detected institution.
    matched = _seed_quarantined(
        store,
        body=purchase,
        from_email="alerts@notify.somebank.com",
        detected_institution=None,
        subject="sub",
    )
    # Sender on an unrelated domain — must not be swept.
    other = _seed_quarantined(
        store,
        body="Unreadable.",
        from_email="alerts@otherbank.com",
        detected_institution=None,
        subject="other",
    )

    resp = retry_client.post("/api/v1/parse-failures/retry-all", json={"from_domain": "somebank.com"})
    assert_ok(resp)
    data = resp.json()
    assert data["retried"] == 1
    assert data["created"] == 1
    assert store.get_failure(matched)["status"] == "retried"
    assert store.get_failure(other)["status"] == "quarantined"


def test_retry_all_cap_respected(retry_env) -> None:
    # The cap is exercised directly (cheaply) rather than by seeding 1,000 rows.
    store = retry_env["store"]
    _seed_quarantined(store, body="Unreadable one.", subject="one")
    _seed_quarantined(store, body="Unreadable two.", subject="two")

    result = pf_router._retry_all_sync("RBC", None, store, retry_env["db"], retry_env["ov_svc"], cap=1)
    assert result.retried == 1
