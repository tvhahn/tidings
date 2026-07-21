"""Tests for statement persistence API endpoints."""

import io
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_parse_result as _make_parse_result
from tests.factories import make_pdf_bytes as _make_pdf_bytes
from tests.factories import make_reconcile_result as _make_reconcile_result
from tests.factories import make_run_sync_dispatch


class TestUploadReturnsStatementId:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_upload_returns_statement_id(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={"save_statement"},
            default=reconcile_result,
        )

        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        assert "statement_id" in data
        assert len(data["statement_id"]) == 16

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_same_pdf_produces_same_statement_id(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={"save_statement"},
            default=reconcile_result,
        )

        r1 = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        r2 = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )

        assert r1.json()["statement_id"] == r2.json()["statement_id"]


class TestListEndpoint:
    def test_list_empty(self, api_client):
        response = api_client.get("/api/v1/statements")
        assert_ok(response)
        data = response.json()
        assert "statements" in data

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_list_after_upload(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={"save_statement", "list_statements"},
            default=reconcile_result,
        )

        # Upload
        api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )

        # List
        response = api_client.get("/api/v1/statements")
        assert_ok(response)
        stmts = response.json()["statements"]
        assert len(stmts) >= 1
        found = [s for s in stmts if s["filename"] == "RBC_Chequing_2025-12-24_to_2026-01-23.pdf"]
        assert len(found) >= 1
        assert found[0]["institution"] == "RBC"


class TestDetailEndpoint:
    def test_get_nonexistent_404(self, api_client):
        response = api_client.get("/api/v1/statements/nonexistent12345")
        assert_problem(response, 404)

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_get_detail_after_upload(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={"save_statement", "get_statement", "get_transactions", "list_statements"},
            default=reconcile_result,
        )

        upload_resp = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        sid = upload_resp.json()["statement_id"]

        response = api_client.get(f"/api/v1/statements/{sid}")
        assert_ok(response)
        data = response.json()
        assert data["id"] == sid
        assert data["institution"] == "RBC"
        assert "transactions" in data
        assert len(data["transactions"]) == 2


class TestDeleteEndpoint:
    def test_delete_nonexistent_404(self, api_client):
        response = api_client.delete("/api/v1/statements/nonexistent12345")
        assert_problem(response, 404)

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_delete_existing(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={"save_statement", "delete_statement", "get_statement", "get_transactions"},
            default=reconcile_result,
        )

        upload_resp = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        sid = upload_resp.json()["statement_id"]

        # Delete
        del_resp = api_client.delete(f"/api/v1/statements/{sid}")
        assert_ok(del_resp)
        assert del_resp.json()["ok"] is True

        # Verify it's gone
        get_resp = api_client.get(f"/api/v1/statements/{sid}")
        assert_problem(get_resp, 404)


class TestPatchTransaction:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_patch_single_transaction(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={
                "save_statement",
                "update_transaction_action_by_row_id",
                "get_statement",
                "get_transactions",
            },
            default=reconcile_result,
        )

        upload_resp = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        sid = upload_resp.json()["statement_id"]

        # Read the canonical row_id (PATCH no longer accepts the legacy index).
        get_resp = api_client.get(f"/api/v1/statements/{sid}")
        row_id = get_resp.json()["transactions"][0]["row_id"]

        # Patch by stable row_id
        patch_resp = api_client.patch(
            f"/api/v1/statements/{sid}/transactions/{row_id}",
            json={"action": "skip", "company": "Edited Co", "category": "utilities"},
        )
        assert_ok(patch_resp)
        data = patch_resp.json()
        assert data["ok"] is True
        assert data["action"] == "skip"
        assert data["row_id"] == row_id

    def test_patch_legacy_int_returns_410(self, api_client):
        resp = api_client.patch(
            "/api/v1/statements/missing123/transactions/0",
            json={"action": "skip"},
        )
        assert_problem(resp, 410, "STATEMENT_ROW_INDEX_DEPRECATED")

    def test_patch_unknown_row_id_returns_404(self, api_client):
        resp = api_client.patch(
            "/api/v1/statements/missing123/transactions/r0123456789abcdef",
            json={"action": "skip"},
        )
        assert_problem(resp, 404)


class TestBulkPatchTransactions:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_bulk_update(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={"save_statement", "bulk_update_actions"},
            default=reconcile_result,
        )

        upload_resp = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        sid = upload_resp.json()["statement_id"]

        resp = api_client.patch(
            f"/api/v1/statements/{sid}/transactions",
            json={
                "updates": [
                    {"tx_index": 0, "action": "skip"},
                    {"tx_index": 1, "action": "import", "company": "Fee"},
                ]
            },
        )
        assert_ok(resp)
        assert resp.json()["ok"] is True
        assert resp.json()["updated"] == 2


class TestImportBackwardCompatibility:
    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_import_without_statement_id_still_works(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        mock_run_sync.return_value = "2026.01.23_00.00_stmt_RBC_abc.pdf"

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 0, "action": "import", "category": "utilities", "company": "Test"},
                ],
                "metadata": {
                    "institution": "RBC",
                    "account_type": "chequing",
                    "period_start": "2025-12-24",
                    "period_end": "2026-01-23",
                    "transaction_count": 1,
                },
                "transactions": [
                    {
                        "date": "2026-01-15",
                        "description": "Test",
                        "amount": 50.0,
                        "type": "withdrawal",
                        "balance": 40000.0,
                        "cleaned_description": "Test",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        assert response.json()["imported"] == 1


class TestCategoryEditDetection:
    """Verify that user-edited categories produce source='manual' in CategoryAudit."""

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_import_with_edited_category_uses_manual_source(
        self,
        mock_parser_cls: MagicMock,
        mock_reconcile: MagicMock,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        api_client,
    ) -> None:
        """When a user edits the category away from suggested, audit_source should be 'manual'."""
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        # Track calls to add_statement_transaction
        import_calls = []

        async def run_sync_upload(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            if func == mock_parser_cls.return_value.parse:
                return parse_result
            fname = getattr(func, "__name__", "")
            if fname in ("save_statement", "get_statement", "get_transactions"):
                return func(*args, **kwargs)
            return reconcile_result

        mock_run_sync.side_effect = run_sync_upload

        # Upload first to create the statement in SQLite
        upload_resp = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        sid = upload_resp.json()["statement_id"]

        # Edit the category on the new transaction (tx_index=1) to something
        # different from suggested. We address it by stable row_id, not the
        # legacy positional index.
        async def run_sync_get_for_row_id(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            fname = getattr(func, "__name__", "")
            if fname == "get_transactions":
                return func(*args, **kwargs)
            return None

        mock_run_sync.side_effect = run_sync_get_for_row_id
        get_resp = api_client.get(f"/api/v1/statements/{sid}")
        target_row_id = next(t["row_id"] for t in get_resp.json()["transactions"] if t["tx_index"] == 1)

        async def run_sync_patch(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            fname = getattr(func, "__name__", "")
            if fname == "update_transaction_action_by_row_id":
                return func(*args, **kwargs)
            return None

        mock_run_sync.side_effect = run_sync_patch
        api_client.patch(
            f"/api/v1/statements/{sid}/transactions/{target_row_id}",
            json={"action": "import", "category": "groceries"},  # suggested was "service charges/fees"
        )

        # Now import — should detect edited category and use "manual" source
        async def run_sync_import(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            fname = getattr(func, "__name__", "")
            if fname == "get_transactions":
                return func(*args, **kwargs)
            if fname == "add_statement_transaction":
                import_calls.append({"args": args, "kwargs": kwargs})
                return "2026.01.23_00.00_stmt_RBC_abc.pdf"
            if fname == "record_import_results":
                return func(*args, **kwargs)
            return None

        mock_run_sync.side_effect = run_sync_import

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 1, "action": "import", "category": "groceries", "company": "Monthly fee"},
                ],
                "metadata": {
                    "institution": "RBC",
                    "account_type": "chequing",
                    "period_start": "2025-12-24",
                    "period_end": "2026-01-23",
                    "transaction_count": 2,
                },
                "transactions": [
                    {
                        "date": "2026-01-15",
                        "description": "BillPayment WestlandUtilityCo",
                        "amount": 98.75,
                        "type": "withdrawal",
                        "balance": 41685.40,
                        "cleaned_description": "Westland Utility Co",
                    },
                    {
                        "date": "2026-01-23",
                        "description": "Monthlyfee",
                        "amount": 4.0,
                        "type": "withdrawal",
                        "balance": 41789.95,
                        "cleaned_description": "Monthly fee",
                    },
                ],
                "filename": "test.pdf",
                "statement_id": sid,
            },
        )
        assert_ok(response)
        assert response.json()["imported"] == 1
        # The call should have passed audit_source="manual"
        assert len(import_calls) == 1
        # audit_source is the second positional arg after txn_data
        assert import_calls[0]["args"][1] == "manual"

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_import_without_edited_category_uses_default_source(
        self,
        mock_parser_cls: MagicMock,
        mock_reconcile: MagicMock,
        mock_fwd: MagicMock,
        mock_uid: MagicMock,
        mock_history: MagicMock,
        mock_run_sync: MagicMock,
        api_client,
    ) -> None:
        """When category is NOT edited, audit_source should remain 'statement_import'."""
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        import_calls = []

        async def run_sync_upload(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            if func == mock_parser_cls.return_value.parse:
                return parse_result
            fname = getattr(func, "__name__", "")
            if fname in ("save_statement", "get_statement", "get_transactions"):
                return func(*args, **kwargs)
            return reconcile_result

        mock_run_sync.side_effect = run_sync_upload

        upload_resp = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        sid = upload_resp.json()["statement_id"]

        # Import without editing category — should use default source
        async def run_sync_import(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            fname = getattr(func, "__name__", "")
            if fname == "get_transactions":
                return func(*args, **kwargs)
            if fname == "add_statement_transaction":
                import_calls.append({"args": args, "kwargs": kwargs})
                return "2026.01.23_00.00_stmt_RBC_abc.pdf"
            if fname == "record_import_results":
                return func(*args, **kwargs)
            return None

        mock_run_sync.side_effect = run_sync_import

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 1, "action": "import", "category": "service charges/fees", "company": "Monthly fee"},
                ],
                "metadata": {
                    "institution": "RBC",
                    "account_type": "chequing",
                    "period_start": "2025-12-24",
                    "period_end": "2026-01-23",
                    "transaction_count": 2,
                },
                "transactions": [
                    {
                        "date": "2026-01-15",
                        "description": "BillPayment WestlandUtilityCo",
                        "amount": 98.75,
                        "type": "withdrawal",
                        "balance": 41685.40,
                        "cleaned_description": "Westland Utility Co",
                    },
                    {
                        "date": "2026-01-23",
                        "description": "Monthlyfee",
                        "amount": 4.0,
                        "type": "withdrawal",
                        "balance": 41789.95,
                        "cleaned_description": "Monthly fee",
                    },
                ],
                "filename": "test.pdf",
                "statement_id": sid,
            },
        )
        assert_ok(response)
        assert response.json()["imported"] == 1
        assert len(import_calls) == 1
        # audit_source should be default "statement_import"
        assert import_calls[0]["args"][1] == "statement_import"


class TestDownloadEndpoint:
    def test_download_nonexistent_404(self, api_client):
        response = api_client.get("/api/v1/statements/nonexistent12345/download")
        assert_problem(response, 404)

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_download_valid_statement(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough={"save_statement", "get_statement", "get_transactions"},
            default=reconcile_result,
        )

        # Upload first
        upload_resp = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        sid = upload_resp.json()["statement_id"]

        # Download
        download_resp = api_client.get(f"/api/v1/statements/{sid}/download")
        assert_ok(download_resp)
        assert download_resp.headers["content-type"] == "application/pdf"
        assert "attachment" in download_resp.headers.get("content-disposition", "") or download_resp.headers.get(
            "content-disposition", ""
        ).endswith('.pdf"')

    @pytest.mark.parametrize("mock_run_sync", ["statements_crud"], indirect=True)
    def test_download_missing_file_404(self, mock_run_sync: MagicMock, api_client) -> None:
        """Statement exists in SQLite but PDF file was deleted from disk."""

        mock_run_sync.side_effect = make_run_sync_dispatch(
            default={
                "id": "test123",
                "pdf_path": "data/raw/statements/RBC/nonexistent.pdf",
                "filename": "nonexistent.pdf",
                "institution": "RBC",
            }
        )

        response = api_client.get("/api/v1/statements/test123/download")
        assert_problem(response, 404)
