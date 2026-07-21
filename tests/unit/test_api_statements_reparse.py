"""Endpoint-level characterization tests for POST /statements/{id}/reparse.

These pin the reparse handler's observable behavior — edit carry-over, the
404 paths, and the `get_statement` response-shape delegation — before the
parse->reconcile orchestration is extracted into `statement_helpers`. They
drive the real SQLite `StatementStore` (redirected to a tmp db + tmp raw-PDF
dir by the `_isolate_statement_store` autouse fixture in
`tests/unit/conftest.py`), so upload actually writes a PDF to disk and reparse
reads it back.
"""

import io
from unittest.mock import MagicMock, patch

import pytest

from tests.asserts import assert_ok, assert_problem
from tests.factories import make_parse_result as _make_parse_result
from tests.factories import make_pdf_bytes as _make_pdf_bytes
from tests.factories import make_reconcile_result as _make_reconcile_result
from tests.factories import make_run_sync_dispatch

# Every off-thread call the upload -> edit -> reparse flow funnels through
# `run_sync`. The parser's `.parse` yields the canned parse result; `reconcile`
# (and anything else) yields the canned reconcile result via `default`; the
# persistence + read helpers run for real against the tmp SQLite store.
_PASSTHROUGH = frozenset(
    {
        "save_statement",
        "get_statement",
        "get_transactions",
        "update_transaction_action_by_row_id",
    }
)


class TestReparsePreservesEdits:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_reparse_preserves_category_edit(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """A user category edit survives a re-parse, matched on (date, amount, raw_description)."""
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough=_PASSTHROUGH,
            default=reconcile_result,
        )

        # Upload creates the statement + writes the PDF to the tmp raw dir.
        upload = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_ok(upload)
        sid = upload.json()["statement_id"]

        # Edit the category on the "new" Monthlyfee row (tx_index == 1), keyed
        # by its stable row_id.
        detail = api_client.get(f"/api/v1/statements/{sid}")
        assert_ok(detail)
        row_id = next(t["row_id"] for t in detail.json()["transactions"] if t["tx_index"] == 1)

        patched = api_client.patch(
            f"/api/v1/statements/{sid}/transactions/{row_id}",
            json={"action": "import", "category": "groceries"},
        )
        assert_ok(patched)

        # Reparse the same PDF; the edit must carry over.
        reparse = api_client.post(f"/api/v1/statements/{sid}/reparse")
        assert_ok(reparse)

        target = next(t for t in reparse.json()["transactions"] if t["raw_description"] == "Monthlyfee")
        assert target["edited_category"] == "groceries"
        assert target["action"] == "import"


class TestReparseNotFound:
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_reparse_unknown_id_returns_404(self, mock_run_sync: MagicMock, api_client) -> None:
        """Reparse of a statement id with no SQLite row is a 404 before any parse."""
        mock_run_sync.side_effect = make_run_sync_dispatch(passthrough={"get_statement"}, default=None)

        resp = api_client.post("/api/v1/statements/doesnotexist99/reparse")
        assert_problem(resp, 404)


class TestReparseResponseShape:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_reparse_response_matches_get_statement(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """Reparse returns exactly the get_statement detail payload it delegates to."""
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough=_PASSTHROUGH,
            default=reconcile_result,
        )

        upload = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_ok(upload)
        sid = upload.json()["statement_id"]

        reparse = api_client.post(f"/api/v1/statements/{sid}/reparse")
        assert_ok(reparse)

        detail = api_client.get(f"/api/v1/statements/{sid}")
        assert_ok(detail)

        reparse_body = reparse.json()
        assert reparse_body["id"] == sid
        assert reparse_body == detail.json()


class TestReparseUneditedRowsGetDefaults:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_unedited_rows_carry_no_edit_fields(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """Rows never edited by the user stay clean through a reparse.

        The carry-over block only copies `edited_company`/`edited_category` when
        the old row actually held an edit; with no prior edit those keys must
        stay `None` in the reparsed rows.
        """
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough=_PASSTHROUGH,
            default=reconcile_result,
        )

        upload = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_ok(upload)
        sid = upload.json()["statement_id"]

        # No edit is made between upload and reparse.
        reparse = api_client.post(f"/api/v1/statements/{sid}/reparse")
        assert_ok(reparse)

        rows = reparse.json()["transactions"]
        assert rows  # sanity: the reparse produced rows
        for row in rows:
            assert row["edited_company"] is None
            assert row["edited_category"] is None


class TestReparsePdfMissing:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_reparse_missing_pdf_returns_404(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """Statement row exists but its PDF is gone on disk ⇒ 404 before any parse."""
        parse_result = _make_parse_result()
        reconcile_result = _make_reconcile_result()

        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=parse_result,
            passthrough=_PASSTHROUGH,
            default=reconcile_result,
        )

        upload = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_ok(upload)
        sid = upload.json()["statement_id"]

        # The statement row survives, but its PDF path no longer resolves.
        with patch("src.api.routers.statements.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            resp = api_client.post(f"/api/v1/statements/{sid}/reparse")
        assert_problem(resp, 404)


class TestReparseDuplicateRows:
    @patch("src.api.routers.statement_helpers.reconcile")
    @patch("src.api.routers.statement_helpers.select_parser")
    @pytest.mark.parametrize("mock_run_sync", ["statements"], indirect=True)
    def test_duplicate_rows_keep_distinct_identities(
        self, mock_parser_cls: MagicMock, mock_reconcile: MagicMock, mock_run_sync: MagicMock, api_client
    ) -> None:
        """Two identical statement rows must reparse to two distinct persisted rows.

        Regression guard for AUDIT Q3: `build_reconciliation_items` once located
        each reconcile entry with `transactions.index(...)`, which returned the
        *first* equal dict — so two content-identical rows both resolved to index
        0 and collided on the `UNIQUE(statement_id, tx_index)` constraint. The
        reconciler now carries each row's position on `.index`, so the two rows
        keep distinct `row_id`s and `tx_index` values [0, 1].
        """
        from src.finance.statement_reconciler import NewTransaction, ReconcileResult

        # 1. Upload a normal (non-duplicate) statement so the row + PDF exist.
        normal_parse = _make_parse_result()
        normal_reconcile = _make_reconcile_result()
        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=normal_parse,
            passthrough=_PASSTHROUGH,
            default=normal_reconcile,
        )
        upload = api_client.post(
            "/api/v1/statements/upload",
            files={"file": ("test.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
        )
        assert_ok(upload)
        sid = upload.json()["statement_id"]

        # 2. Reparse now yields TWO identical rows (same date/amount/description)
        #    as two `new` entries wrapping two DISTINCT dict objects.
        dup_a = {"date": "2026-03-05", "description": "COFFEE", "amount": 5.0, "type": "withdrawal", "balance": 100.0}
        dup_b = dict(dup_a)
        dup_parse = _make_parse_result(
            transactions=[dup_a, dup_b],
            raw_descriptions=["COFFEE", "COFFEE"],
            cleaned_descriptions=["Coffee", "Coffee"],
        )
        dup_reconcile = ReconcileResult(
            matched=[],
            ambiguous=[],
            new=[
                NewTransaction(
                    index=0,
                    statement_txn=dup_parse.transactions[0],
                    cleaned_description="Coffee",
                    raw_description="COFFEE",
                    suggested_category="restaurant",
                ),
                NewTransaction(
                    index=1,
                    statement_txn=dup_parse.transactions[1],
                    cleaned_description="Coffee",
                    raw_description="COFFEE",
                    suggested_category="restaurant",
                ),
            ],
        )
        mock_run_sync.side_effect = make_run_sync_dispatch(
            parser_parse=mock_parser_cls.return_value.parse,
            parse_result=dup_parse,
            passthrough=_PASSTHROUGH,
            default=dup_reconcile,
        )

        reparse = api_client.post(f"/api/v1/statements/{sid}/reparse")
        assert_ok(reparse)

        rows = reparse.json()["transactions"]
        assert len(rows) == 2
        assert len({r["row_id"] for r in rows}) == 2
        assert sorted(r["tx_index"] for r in rows) == [0, 1]
