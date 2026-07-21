"""Tests for statement import API endpoints."""

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


class TestUploadEndpoint:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_upload_valid_pdf(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            default=reconcile_result,
        )

        pdf_bytes = _make_pdf_bytes()
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        assert "transactions" in data
        assert "metadata" in data
        assert "matched" in data
        assert "ambiguous" in data
        assert "new" in data
        assert "summary" in data
        assert data["summary"]["total_parsed"] == 2

    def test_upload_non_pdf_rejected(self, api_client):
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.txt", io.BytesIO(b"not a pdf"), "text/plain")},
        )
        assert_problem(response, 422)

    def test_upload_invalid_pdf_magic_bytes(self, api_client):
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
        )
        assert_problem(response, 422)


class TestImportEndpoint:
    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_import_actions(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        # add_statement_transaction returns a DateFileName string
        mock_run_sync.return_value = "2026.01.23_00.00_stmt_RBC_abc12345.pdf"

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 0, "action": "import", "category": "service charges/fees", "company": "Monthly fee"},
                    {"index": 1, "action": "skip"},
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
                        "date": "2026-01-23",
                        "description": "Monthlyfee",
                        "amount": 4.0,
                        "type": "withdrawal",
                        "balance": 41789.95,
                        "cleaned_description": "Monthly fee",
                    },
                    {
                        "date": "2026-01-10",
                        "description": "Other",
                        "amount": 10.0,
                        "type": "withdrawal",
                        "balance": 41779.95,
                        "cleaned_description": "Other",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["imported"] == 1
        assert data["skipped"] == 1
        assert data["duplicates"] == 0

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value=None)
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_import_duplicate_counted(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        # Return False for duplicate
        mock_run_sync.return_value = False

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
        data = response.json()
        assert data["duplicates"] == 1
        assert data["imported"] == 0


class TestUploadEnrichmentFields:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_ambiguous_includes_enrichment_fields(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        from src.finance.statement_reconciler import AmbiguousTransaction, ReconcileResult

        parse_result = _make_parse_result()
        reconcile_result = ReconcileResult(
            matched=[],
            ambiguous=[
                AmbiguousTransaction(
                    index=0,
                    statement_txn=parse_result.transactions[0],
                    candidates=[
                        {
                            "ForwardedTo": "test@example.com",
                            "DateFileName": "2026.01.16_12.00_test.eml",
                            "Company": "—",
                            "Amount": 98.75,
                            "Category": "miscellaneous",
                        }
                    ],
                    reason="date off by 1 day",
                    cleaned_description="Westland Utility Co",
                    raw_description="BillPayment WestlandUtilityCo",
                    suggested_category="utilities",
                )
            ],
            new=[],
        )

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            default=reconcile_result,
        )
        pdf_bytes = _make_pdf_bytes()
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        a = data["ambiguous"][0]
        assert a["cleaned_description"] == "Westland Utility Co"
        assert a["raw_description"] == "BillPayment WestlandUtilityCo"
        assert a["suggested_category"] == "utilities"
        assert a["enrichable"] is True
        assert a["candidates"][0]["category"] == "miscellaneous"

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_multi_candidate_not_enrichable(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        from src.finance.statement_reconciler import AmbiguousTransaction, ReconcileResult

        parse_result = _make_parse_result()
        reconcile_result = ReconcileResult(
            matched=[],
            ambiguous=[
                AmbiguousTransaction(
                    index=0,
                    statement_txn=parse_result.transactions[0],
                    candidates=[
                        {
                            "ForwardedTo": "test@example.com",
                            "DateFileName": "2026.01.15_10.00_a.eml",
                            "Company": "A",
                            "Amount": 98.75,
                            "Category": "groceries",
                        },
                        {
                            "ForwardedTo": "test@example.com",
                            "DateFileName": "2026.01.15_14.00_b.eml",
                            "Company": "B",
                            "Amount": 98.75,
                            "Category": "utilities",
                        },
                    ],
                    reason="multiple same-amount matches",
                    cleaned_description="Westland Utility Co",
                    raw_description="BillPayment WestlandUtilityCo",
                    suggested_category="utilities",
                )
            ],
            new=[],
        )

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            default=reconcile_result,
        )
        pdf_bytes = _make_pdf_bytes()
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        assert data["ambiguous"][0]["enrichable"] is False

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_matched_includes_suggested_category(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()
        reconcile_result.matched[0].suggested_category = "utilities"

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            default=reconcile_result,
        )
        pdf_bytes = _make_pdf_bytes()
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        assert data["matched"][0]["suggested_category"] == "utilities"


class TestImportEnrichAction:
    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_enrich_action_calls_enrich_transaction(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        mock_run_sync.return_value = {"old_company": "—", "old_category": "miscellaneous"}

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {
                        "index": 0,
                        "action": "enrich",
                        "company": "North Mobile",
                        "category": "communication/cell",
                        "forwarded_to": "test@example.com",
                        "date_file_name": "2026.01.17_12.00_test.eml",
                    },
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
                        "date": "2026-01-17",
                        "description": "BillPayment NorthMobile",
                        "amount": 33.60,
                        "type": "withdrawal",
                        "balance": 39966.40,
                        "cleaned_description": "North Mobile",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["enriched"] == 1
        assert data["imported"] == 0
        assert data["skipped"] == 0

        # Verify statement_source was passed through to enrich_transaction
        call_args = mock_run_sync.call_args
        assert call_args.kwargs["statement_source"] == "RBC_Chequing_2025-12"

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_enrich_without_keys_skipped(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {
                        "index": 0,
                        "action": "enrich",
                        "company": "North Mobile",
                        "category": "communication/cell",
                        # Missing forwarded_to and date_file_name
                    },
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
                        "date": "2026-01-17",
                        "description": "Test",
                        "amount": 33.60,
                        "type": "withdrawal",
                        "balance": 39966.40,
                        "cleaned_description": "Test",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["enriched"] == 0
        assert data["skipped"] == 1

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_mixed_import_and_enrich(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        # Return DateFileName for import, dict for enrich
        call_count = 0

        async def side_effect(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # enrich call
                return {"old_company": "—", "old_category": "miscellaneous"}
            # on the import call
            return "2026.01.23_00.00_stmt_RBC_abc12345.pdf"

        mock_run_sync.side_effect = side_effect

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {
                        "index": 0,
                        "action": "enrich",
                        "company": "North Mobile",
                        "category": "communication/cell",
                        "forwarded_to": "test@example.com",
                        "date_file_name": "2026.01.17_12.00_test.eml",
                    },
                    {
                        "index": 1,
                        "action": "import",
                        "company": "Monthly fee",
                        "category": "service charges/fees",
                    },
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
                        "date": "2026-01-17",
                        "description": "BillPayment NorthMobile",
                        "amount": 33.60,
                        "type": "withdrawal",
                        "balance": 39966.40,
                        "cleaned_description": "North Mobile",
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
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["enriched"] == 1
        assert data["imported"] == 1


class TestImportUpdateAction:
    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_update_action_calls_enrich_transaction(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        mock_run_sync.return_value = {"old_company": "Monthly fee", "old_category": "service charges/fees"}

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {
                        "index": 0,
                        "action": "update",
                        "company": "Updated Company",
                        "category": "utilities",
                        "forwarded_to": "test@example.com",
                        "date_file_name": "2026.01.15_00.00_stmt_RBC_abc12345.pdf",
                    },
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
                        "description": "Monthlyfee",
                        "amount": 4.0,
                        "type": "withdrawal",
                        "balance": 41789.95,
                        "cleaned_description": "Monthly fee",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["updated"] == 1
        assert data["imported"] == 0
        assert data["enriched"] == 0

        # Verify source was "statement_reimport"
        call_args = mock_run_sync.call_args
        assert call_args.kwargs["source"] == "statement_reimport"

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_update_without_keys_skipped(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {
                        "index": 0,
                        "action": "update",
                        "company": "Updated",
                        "category": "utilities",
                        # Missing forwarded_to and date_file_name
                    },
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
                        "amount": 4.0,
                        "type": "withdrawal",
                        "balance": 40000.0,
                        "cleaned_description": "Test",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["updated"] == 0
        assert data["skipped"] == 1


class TestUploadPreviouslyImported:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_previously_imported_in_response(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        from src.finance.statement_reconciler import PreviouslyImportedTransaction, ReconcileResult

        parse_result = _make_parse_result()
        reconcile_result = ReconcileResult(
            matched=[],
            ambiguous=[],
            new=[],
            previously_imported=[
                PreviouslyImportedTransaction(
                    index=0,
                    statement_txn=parse_result.transactions[0],
                    db_item={
                        "ForwardedTo": "test@example.com",
                        "DateFileName": "2026.01.15_00.00_stmt_RBC_abc12345.pdf",
                        "Company": "Westland Utility Co",
                        "Amount": 98.75,
                        "Category": "utilities",
                        "StatementSource": "RBC_Chequing_2025-12",
                    },
                    cleaned_description="Westland Utility Co",
                    raw_description="BillPayment WestlandUtilityCo",
                    suggested_category="utilities",
                )
            ],
        )

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            default=reconcile_result,
        )
        pdf_bytes = _make_pdf_bytes()
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        assert len(data["previously_imported"]) == 1
        assert data["previously_imported"][0]["db_match"]["company"] == "Westland Utility Co"
        assert data["summary"]["previously_imported_count"] == 1


class TestUploadSuspectedDuplicates:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_suspected_duplicates_in_response(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        from src.finance.statement_reconciler import ReconcileResult, SuspectedDuplicate

        parse_result = _make_parse_result()
        reconcile_result = ReconcileResult(
            matched=[],
            ambiguous=[],
            suspected_duplicates=[
                SuspectedDuplicate(
                    index=0,
                    statement_txn=parse_result.transactions[0],
                    db_item={
                        "ForwardedTo": "test@example.com",
                        "DateFileName": "2026.01.15_12.00_test.eml",
                        "Company": "WESTLANDUTILITYCO",
                        "Amount": 98.75,
                        "Category": "utilities",
                        "TransactionType": "e-transfer",
                    },
                    cleaned_description="Westland Utility Co",
                    raw_description="BillPayment WestlandUtilityCo",
                    suggested_category="utilities",
                    reason="type mismatch: withdrawal ≠ e-transfer",
                )
            ],
            new=[],
        )

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            default=reconcile_result,
        )
        pdf_bytes = _make_pdf_bytes()
        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        assert len(data["suspected_duplicates"]) == 1
        sd = data["suspected_duplicates"][0]
        assert sd["db_match"]["company"] == "WESTLANDUTILITYCO"
        assert sd["db_match"]["transaction_type"] == "e-transfer"
        assert sd["reason"] == "type mismatch: withdrawal ≠ e-transfer"
        assert data["summary"]["suspected_duplicate_count"] == 1


class TestImportSuspectedDuplicateAction:
    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_suspected_duplicate_import_action(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """Suspected duplicate toggled to import should be imported like a new transaction."""
        mock_run_sync.return_value = "2026.01.15_00.00_stmt_RBC_abc12345.pdf"

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 0, "action": "import", "category": "utilities", "company": "Westland Utility Co"},
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
                        "description": "BillPayment WestlandUtilityCo",
                        "amount": 98.75,
                        "type": "withdrawal",
                        "balance": 41685.40,
                        "cleaned_description": "Westland Utility Co",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["imported"] == 1

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_suspected_duplicate_skip_action(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """Suspected duplicate with skip action should be counted as skipped."""
        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 0, "action": "skip"},
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
                        "description": "BillPayment WestlandUtilityCo",
                        "amount": 98.75,
                        "type": "withdrawal",
                        "balance": 41685.40,
                        "cleaned_description": "Westland Utility Co",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["skipped"] == 1
        assert data["imported"] == 0


class TestImportValidation:
    """Pin the current input-validation behavior of POST /statements/import.

    Two of these (unknown action, malformed row) are strict xfails asserting the
    *future* 422 that Phase 3 introduces — until then the handler silently skips
    or 500s.
    """

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_well_formed_import_succeeds(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """One import action + one fully-populated row → 200, imported == 1."""
        # add_statement_transaction returns a DateFileName string on success.
        mock_run_sync.return_value = "2026.01.23_00.00_stmt_RBC_abc12345.pdf"

        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 0, "action": "import", "category": "service charges/fees", "company": "Monthly fee"},
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
                        "date": "2026-01-23",
                        "description": "Monthlyfee",
                        "amount": 4.0,
                        "type": "withdrawal",
                        "balance": 41789.95,
                        "cleaned_description": "Monthly fee",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_ok(response)
        data = response.json()
        assert data["imported"] == 1
        assert data["skipped"] == 0

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_out_of_bounds_index_is_skipped(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """An import action whose index exceeds the transaction list → skipped."""
        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 5, "action": "import", "category": "utilities", "company": "Test"},
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
        data = response.json()
        assert data["skipped"] == 1
        assert data["imported"] == 0

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_unknown_action_is_rejected(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """An unrecognized action string is rejected by the typed enum → 422."""
        response = api_client.post(
            "/api/v1/statements/import",
            json={
                "actions": [
                    {"index": 0, "action": "explode", "category": "utilities", "company": "Test"},
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
        assert_problem(response, 422)

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_malformed_row_is_rejected(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """A row missing the required `amount` field is rejected by the typed model → 422."""
        mock_run_sync.return_value = "2026.01.15_00.00_stmt_RBC_abc12345.pdf"

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
                    {"date": "2026-01-15", "description": "Test", "type": "withdrawal"},
                ],
                "filename": "test.pdf",
            },
        )
        assert_problem(response, 422)

    @patch("src.api.routers.statements._append_import_history")
    @patch("src.api.routers.statements._get_user_id", return_value="default")
    @patch("src.api.routers.statements._get_forwarded_to", return_value="test@example.com")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_non_numeric_amount_is_rejected(
        self, mock_fwd: MagicMock, mock_uid: MagicMock, mock_history: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """A row whose `amount` is not a number is rejected by the typed model → 422."""
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
                        "amount": "not-a-number",
                        "type": "withdrawal",
                        "balance": 40000.0,
                        "cleaned_description": "Test",
                    },
                ],
                "filename": "test.pdf",
            },
        )
        assert_problem(response, 422)


class TestStandardizedPdfName:
    def test_with_period(self):
        from src.api.routers.statements import _standardized_pdf_name

        result = _standardized_pdf_name("RBC", "chequing", "2025-12-24", "2026-01-23", "original.pdf")
        assert result == "RBC_Chequing_2025-12-24_to_2026-01-23.pdf"

    def test_without_period(self):
        from src.api.routers.statements import _standardized_pdf_name

        result = _standardized_pdf_name("RBC", "chequing", None, None, "my_statement.pdf")
        assert result == "RBC_Chequing_my_statement.pdf"

    def test_simplii_variant(self):
        from src.api.routers.statements import _standardized_pdf_name

        result = _standardized_pdf_name("Simplii", "chequing", "2025-11-27", "2025-12-29", "stmt.pdf")
        assert result == "Simplii_Chequing_2025-11-27_to_2025-12-29.pdf"

    def test_partial_period_uses_fallback(self):
        from src.api.routers.statements import _standardized_pdf_name

        # Only start, no end
        result = _standardized_pdf_name("RBC", "chequing", "2025-12-24", None, "file.pdf")
        assert result == "RBC_Chequing_file.pdf"

    def test_safe_component_strips_deep_traversal(self):
        from src.api.routers.statement_helpers import _safe_filename_component

        assert _safe_filename_component("../../../../etc/x.pdf") == "x.pdf"

    def test_safe_component_strips_embedded_traversal(self):
        from src.api.routers.statement_helpers import _safe_filename_component

        assert _safe_filename_component("a/../b.pdf") == "b.pdf"

    def test_safe_component_all_dots_falls_back(self):
        from src.api.routers.statement_helpers import _safe_filename_component

        assert _safe_filename_component("...") == "statement"

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_upload_hostile_filename_stays_under_statements_dir(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        from pathlib import Path

        from src.api.routers.statement_helpers import STATEMENTS_RAW_DIR

        parse_result = _make_parse_result(
            metadata={
                "institution": "RBC",
                "account_type": "chequing",
                "period_start": None,
                "period_end": None,
                "transaction_count": 2,
            }
        )
        reconcile_result = _make_reconcile_result()
        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            default=reconcile_result,
        )

        written: list[Path] = []

        def _capture(self: Path, data: bytes) -> None:
            written.append(self)

        with patch("pathlib.Path.write_bytes", _capture):
            response = api_client.post(
                "/api/v1/statements/upload",
                files={"file": ("evil/../../escape.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
            )

        assert_ok(response)
        # The PDF write never lands outside the statements tree.
        root = STATEMENTS_RAW_DIR.resolve()
        assert written, "write_bytes was never called"
        for path in written:
            assert path.resolve().is_relative_to(root), f"{path} escaped {root}"
        assert written[-1].name == "RBC_Chequing_escape.pdf"


class TestStatementSourceInTransactions:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_statement_source_appears(self, mock_run_sync: MagicMock, api_client) -> None:
        mock_run_sync.return_value = [
            {
                "ForwardedTo": "test@example.com",
                "DateFileName": "2026.01.15_00.00_stmt_RBC_abc12345.pdf",
                "Date": "01/15/2026 00:00 PST",
                "Amount": 4.0,
                "Company": "Monthly fee",
                "Category": "service charges/fees",
                "Institution": "RBC",
                "TransactionType": "withdrawal",
                "StatementSource": "RBC_Chequing_2026-01",
            }
        ]

        response = api_client.get("/api/v1/transactions?month=2026-01")
        assert_ok(response)
        data = response.json()
        assert data["transactions"][0]["statement_source"] == "RBC_Chequing_2026-01"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_email_transaction_no_statement_source(self, mock_run_sync: MagicMock, api_client) -> None:
        mock_run_sync.return_value = [
            {
                "ForwardedTo": "test@example.com",
                "DateFileName": "2026.01.15_12.00_test.eml",
                "Date": "01/15/2026 12:00 PST",
                "Amount": 50.0,
                "Company": "STORE",
                "Category": "groceries",
                "Institution": "RBC",
                "TransactionType": "purchase",
            }
        ]

        response = api_client.get("/api/v1/transactions?month=2026-01")
        assert_ok(response)
        data = response.json()
        assert data["transactions"][0]["statement_source"] is None


class TestAIFallbackUpload:
    """Upload seam: deterministic parse failure falls back to AI when consented."""

    @patch("src.api.routers.statement_helpers.get_config")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_fallback_disabled_returns_422_with_hint(
        self, mock_parser_cls: MagicMock, mock_config: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        mock_config.return_value = {"ai_statement_parsing_enabled": False}

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=ValueError("Could not find transaction table header in PDF"),
            default=AssertionError("nothing past parse should run"),
        )

        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_problem(response, 422)
        assert "Parse statements with AI" in response.json()["error"]

    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.parse_statement_with_ai")
    @patch("src.api.routers.statement_helpers.get_config")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_fallback_enabled_parses_with_ai(
        self,
        mock_parser_cls: MagicMock,
        mock_config: MagicMock,
        mock_ai_parse: MagicMock,
        mock_reconcile: MagicMock,
        mock_run_sync: MagicMock,
        api_client,
    ) -> None:
        mock_config.return_value = {"ai_statement_parsing_enabled": True}
        parse_result = _make_parse_result(
            metadata={
                "institution": "Maple Trust Bank",
                "account_type": "chequing",
                "period_start": "2026-03-01",
                "period_end": "2026-03-31",
                "transaction_count": 2,
                "parsed_with_ai": True,
            }
        )

        async def ai_parse(pdf_bytes: bytes, openai_client: Any = None) -> Any:
            return parse_result

        mock_ai_parse.side_effect = ai_parse
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=ValueError("Could not find transaction table header in PDF"),
            default=reconcile_result,
        )

        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_ok(response)
        data = response.json()
        assert data["metadata"]["parsed_with_ai"] is True
        assert data["metadata"]["institution"] == "Maple Trust Bank"

    @patch("src.api.routers.statement_helpers.parse_statement_with_ai")
    @patch("src.api.routers.statement_helpers.get_config")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_ai_failure_returns_422(
        self,
        mock_parser_cls: MagicMock,
        mock_config: MagicMock,
        mock_ai_parse: MagicMock,
        mock_run_sync: MagicMock,
        api_client,
    ) -> None:
        from src.finance.statement_parser_ai import StatementAIError

        mock_config.return_value = {"ai_statement_parsing_enabled": True}

        async def ai_parse(pdf_bytes: bytes, openai_client: Any = None) -> Any:
            raise StatementAIError("The AI reply was not valid JSON: boom")

        mock_ai_parse.side_effect = ai_parse

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=ValueError("Could not find transaction table header in PDF"),
            default=AssertionError("nothing past parse should run"),
        )

        response = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_problem(response, 422)
        assert "not valid JSON" in response.json()["error"]
