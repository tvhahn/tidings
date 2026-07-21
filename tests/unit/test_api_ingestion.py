"""Tests for src/api/routers/ingestion.py — manual transaction add and .eml upload."""

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_override_service,
    get_transactions_db,
)
from src.api.main import app
from tests.asserts import assert_ok, assert_problem

# The shared ``api_client`` fixture (tests/conftest.py) wraps this same
# ``src.api.main.app`` and clears ``dependency_overrides`` on teardown — exactly
# what this module needs — so it uses that fixture directly rather than a local
# duplicate.


def _override_services(db: Any, override_svc: Any) -> None:
    app.dependency_overrides[get_transactions_db] = lambda: db
    app.dependency_overrides[get_override_service] = lambda: override_svc


def _run_passthrough(func: Any, *args: Any, **kwargs: Any) -> Any:
    """side_effect for the mocked ``run_sync``: execute the offloaded callable inline.

    The handlers now offload the override/date-building helper, ``parse_email``,
    and ``db.add_transaction`` through ``run_sync``. Running the passed callable
    here keeps those helpers' real logic (override lookups, date parsing) exercised
    while ``db.add_transaction``'s result is controlled via the db mock's
    ``return_value``.
    """
    return func(*args, **kwargs)


# ---------------------------------------------------------------------------
# POST /api/v1/transactions  — manual entry
# ---------------------------------------------------------------------------


class TestAddManualTransaction:
    @patch("src.api.serializers.get_override_context")
    @patch("src.finance.app_config.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_happy_path_with_explicit_category(
        self,
        mock_get_config: MagicMock,
        mock_override_ctx: MagicMock,
        mock_run_sync: AsyncMock,
        api_client: TestClient,
    ) -> None:
        mock_get_config.return_value = {"user_id": "alice"}
        mock_override_ctx.return_value = ({}, {})
        # build + add_transaction both run through run_sync now; execute them
        # inline and pin the DateFileName the DB write returns.
        mock_run_sync.side_effect = _run_passthrough

        db, override_svc = MagicMock(), MagicMock(name="override_svc")
        db.add_transaction.return_value = "2026.04.28_00.00_manual_abc12345.eml"
        _override_services(db, override_svc)

        resp = api_client.post(
            "/api/v1/transactions",
            json={
                "date": "2026-04-28",
                "amount": 42.50,
                "company": "Test Store",
                "category": "groceries",
                "transaction_type": "purchase",
            },
        )
        assert_ok(resp)
        data = resp.json()
        assert data["status"] == "created"
        assert data["forwarded_to"] == "alice@local"
        assert data["category"] == "groceries"
        assert data["date_file_name"] == "2026.04.28_00.00_manual_abc12345.eml"
        # Override lookup must NOT have been consulted when category is supplied.
        override_svc.lookup_category.assert_not_called()

    @patch("src.api.serializers.get_override_context")
    @patch("src.finance.app_config.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_missing_category_uses_override_lookup(
        self,
        mock_get_config: MagicMock,
        mock_override_ctx: MagicMock,
        mock_run_sync: AsyncMock,
        api_client: TestClient,
    ) -> None:
        mock_get_config.return_value = {"user_id": "default"}
        mock_override_ctx.return_value = ({}, {"alias_pattern": "rent"})
        mock_run_sync.side_effect = _run_passthrough

        override_svc = MagicMock(name="override_svc")
        override_svc.lookup_category.return_value = "rent"
        db = MagicMock()
        db.add_transaction.return_value = "ok.eml"
        _override_services(db, override_svc)

        resp = api_client.post(
            "/api/v1/transactions",
            json={"date": "2026-04-28", "amount": 100, "company": "Landlord Inc"},
        )
        assert_ok(resp)
        assert resp.json()["category"] == "rent"
        override_svc.lookup_category.assert_called_once_with("Landlord Inc", aliases={"alias_pattern": "rent"})

    @patch("src.api.serializers.get_override_context")
    @patch("src.finance.app_config.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_no_override_match_falls_back_to_miscellaneous(
        self,
        mock_get_config: MagicMock,
        mock_override_ctx: MagicMock,
        mock_run_sync: AsyncMock,
        api_client: TestClient,
    ) -> None:
        mock_get_config.return_value = {"user_id": "default"}
        mock_override_ctx.return_value = ({}, {})
        mock_run_sync.side_effect = _run_passthrough

        override_svc = MagicMock()
        override_svc.lookup_category.return_value = None
        db = MagicMock()
        db.add_transaction.return_value = "ok.eml"
        _override_services(db, override_svc)

        resp = api_client.post(
            "/api/v1/transactions",
            json={"date": "2026-04-28", "amount": 5.0, "company": "Random"},
        )
        assert_ok(resp)
        assert resp.json()["category"] == "miscellaneous"

    @patch("src.finance.app_config.get_config")
    def test_bad_date_format_returns_422(self, mock_get_config: MagicMock, api_client: TestClient) -> None:
        mock_get_config.return_value = {"user_id": "default"}
        _override_services(MagicMock(), MagicMock())

        resp = api_client.post(
            "/api/v1/transactions",
            json={
                "date": "Apr 28, 2026",  # not YYYY-MM-DD
                "amount": 1.0,
                "company": "X",
                "category": "groceries",
            },
        )
        assert_problem(resp, 422)
        assert resp.json()["error"] == "Date must be YYYY-MM-DD format"

    @patch("src.finance.app_config.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_db_returns_none_yields_422(
        self, mock_get_config: MagicMock, mock_run_sync: AsyncMock, api_client: TestClient
    ) -> None:
        mock_get_config.return_value = {"user_id": "default"}
        mock_run_sync.side_effect = _run_passthrough

        db = MagicMock()
        db.add_transaction.return_value = None  # missing required fields
        _override_services(db, MagicMock())

        resp = api_client.post(
            "/api/v1/transactions",
            json={
                "date": "2026-04-28",
                "amount": 1.0,
                "company": "X",
                "category": "groceries",
            },
        )
        assert_problem(resp, 422)
        assert "Missing required fields" in resp.json()["error"]

    @patch("src.finance.app_config.get_config")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_db_returns_false_yields_409(
        self, mock_get_config: MagicMock, mock_run_sync: AsyncMock, api_client: TestClient
    ) -> None:
        mock_get_config.return_value = {"user_id": "default"}
        mock_run_sync.side_effect = _run_passthrough

        db = MagicMock()
        db.add_transaction.return_value = False  # duplicate
        _override_services(db, MagicMock())

        resp = api_client.post(
            "/api/v1/transactions",
            json={
                "date": "2026-04-28",
                "amount": 1.0,
                "company": "X",
                "category": "groceries",
            },
        )
        assert_problem(resp, 409)
        assert resp.json()["error"] == "Duplicate transaction"

    def test_invalid_payload_returns_422(self, api_client: TestClient) -> None:
        # amount must be > 0
        resp = api_client.post(
            "/api/v1/transactions",
            json={"date": "2026-04-28", "amount": -5, "company": "X"},
        )
        assert_problem(resp, 422)


# ---------------------------------------------------------------------------
# POST /api/v1/transactions/upload-eml  — raw email upload
# ---------------------------------------------------------------------------


def _eml_file(content: bytes = b"From: a@b.com\nSubject: x\n\nbody", name: str = "msg.eml") -> dict[str, Any]:
    return {"file": (name, io.BytesIO(content), "message/rfc822")}


class TestUploadEml:
    def test_non_eml_filename_rejected(self, api_client: TestClient) -> None:
        _override_services(MagicMock(), MagicMock())
        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files={"file": ("msg.txt", io.BytesIO(b"x"), "text/plain")},
        )
        assert_problem(resp, 422)
        assert resp.json()["error"] == "File must be a .eml file"

    def test_empty_file_rejected(self, api_client: TestClient) -> None:
        _override_services(MagicMock(), MagicMock())
        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files=_eml_file(content=b""),
        )
        assert_problem(resp, 422)
        assert resp.json()["error"] == "Empty file"

    @patch("src.finance.email_pipeline.parse_email")
    def test_parse_email_raising_yields_422(self, mock_parse: MagicMock, api_client: TestClient) -> None:
        mock_parse.side_effect = RuntimeError("bad email")
        _override_services(MagicMock(), MagicMock())

        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files=_eml_file(),
        )
        assert_problem(resp, 422)
        assert resp.json()["error"] == "Failed to parse email"

    @patch("src.finance.ai_client.get_ai_client", return_value=None)
    @patch("src.finance.email_pipeline.parse_email")
    def test_parse_email_returning_no_company_yields_422(
        self, mock_parse: MagicMock, _mock_ai: MagicMock, api_client: TestClient
    ) -> None:
        # Result missing "company" key — the parsers couldn't read it. With no
        # AI client and no institution/keyword signal, the recovery gate treats
        # it as irrelevant and the router returns the original 422.
        mock_parse.return_value = {"category": "x"}
        _override_services(MagicMock(), MagicMock())

        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files=_eml_file(),
        )
        assert_problem(resp, 422)
        assert resp.json()["error"] == "Could not extract transaction from email"

    @patch("src.api.serializers.get_override_context")
    @patch("src.finance.email_pipeline.parse_email")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_happy_path_creates_transaction(
        self,
        mock_parse: MagicMock,
        mock_override_ctx: MagicMock,
        mock_run_sync: AsyncMock,
        api_client: TestClient,
    ) -> None:
        mock_parse.return_value = {
            "company": "Coffee Shop",
            "amount": 4.5,
            "category": "restaurant/dining",
        }
        mock_override_ctx.return_value = ({}, {})
        mock_run_sync.side_effect = _run_passthrough

        db = MagicMock()
        db.add_transaction.return_value = "2026.04.28_00.00_eml_xyz.eml"
        _override_services(db, MagicMock())

        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files=_eml_file(),
        )
        assert_ok(resp)
        data = resp.json()
        assert data["status"] == "created"
        assert data["company"] == "Coffee Shop"
        assert data["amount"] == 4.5
        assert data["category"] == "restaurant/dining"
        assert data["date_file_name"] == "2026.04.28_00.00_eml_xyz.eml"

    @patch("src.api.serializers.get_override_context")
    @patch("src.finance.email_pipeline.parse_email")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_duplicate_returns_duplicate_status(
        self,
        mock_parse: MagicMock,
        mock_override_ctx: MagicMock,
        mock_run_sync: AsyncMock,
        api_client: TestClient,
    ) -> None:
        mock_parse.return_value = {"company": "X", "category": "groceries"}
        mock_override_ctx.return_value = ({}, {})
        mock_run_sync.side_effect = _run_passthrough

        db = MagicMock()
        db.add_transaction.return_value = False  # duplicate
        _override_services(db, MagicMock())

        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files=_eml_file(),
        )
        assert_ok(resp)
        data = resp.json()
        assert data["status"] == "duplicate"
        assert data["detail"] == "Transaction already exists"

    @patch("src.api.serializers.get_override_context")
    @patch("src.finance.email_pipeline.parse_email")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_db_returns_none_yields_422(
        self,
        mock_parse: MagicMock,
        mock_override_ctx: MagicMock,
        mock_run_sync: AsyncMock,
        api_client: TestClient,
    ) -> None:
        mock_parse.return_value = {"company": "X", "category": "groceries"}
        mock_override_ctx.return_value = ({}, {})
        mock_run_sync.side_effect = _run_passthrough

        db = MagicMock()
        db.add_transaction.return_value = None  # missing required fields
        _override_services(db, MagicMock())

        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files=_eml_file(),
        )
        assert_problem(resp, 422)
        assert "missing required fields" in resp.json()["error"].lower()

    @patch("src.api.serializers.get_override_context")
    @patch("src.finance.email_pipeline.parse_email")
    @pytest.mark.parametrize("mock_run_sync", ["ingestion"], indirect=True)
    def test_miscellaneous_category_triggers_override_lookup(
        self,
        mock_parse: MagicMock,
        mock_override_ctx: MagicMock,
        mock_run_sync: AsyncMock,
        api_client: TestClient,
    ) -> None:
        mock_parse.return_value = {
            "company": "Coffee Shop",
            "amount": 4.5,
            "category": "miscellaneous",
        }
        mock_override_ctx.return_value = ({}, {"alias": "x"})
        mock_run_sync.side_effect = _run_passthrough

        override_svc = MagicMock(name="override_svc")
        override_svc.lookup_category.return_value = "restaurant/dining"
        db = MagicMock()
        db.add_transaction.return_value = "x.eml"
        _override_services(db, override_svc)

        resp = api_client.post(
            "/api/v1/transactions/upload-eml",
            files=_eml_file(),
        )
        assert_ok(resp)
        assert resp.json()["category"] == "restaurant/dining"
        override_svc.lookup_category.assert_called_once_with("Coffee Shop", aliases={"alias": "x"})
