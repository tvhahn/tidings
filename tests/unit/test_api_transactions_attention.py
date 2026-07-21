"""Attention-queue endpoint tests (GET /api/v1/transactions/attention).

Split out of test_api_transactions.py so each resource's tests stay under one
roof and the files stay navigable. Uses the shared mock_run_sync fixture.
"""

from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok
from tests.factories import make_transaction_item as _make_item

# ---------------------------------------------------------------------------
# GET /api/v1/transactions/attention
# ---------------------------------------------------------------------------


class TestAttentionQueue:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_filters_miscellaneous_only(self, mock_run_sync: AsyncMock, api_client) -> None:
        items = [
            _make_item(Category="miscellaneous", Company="Unknown Shop"),
            _make_item(Category="groceries", Company="Supermarket"),
            _make_item(Category="Miscellaneous", Company="Another Shop"),
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/attention?month=2026-02")
        assert_ok(resp)

        data = resp.json()
        assert data["count"] == 2
        for txn in data["transactions"]:
            assert txn["category"].lower() == "miscellaneous"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_empty_attention_queue(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = [_make_item(Category="groceries")]

        resp = api_client.get("/api/v1/transactions/attention?month=2026-02")
        data = resp.json()
        assert data["count"] == 0
        assert data["transactions"] == []

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_extraction_audit_row_in_attention(self, mock_run_sync: AsyncMock, api_client) -> None:
        """An AI-extracted row (ExtractionAudit present) lands in attention even
        when its category is non-miscellaneous and it carries no CategoryAudit."""
        extraction = {"method": "ai_fallback", "model": "gpt-5.4-nano", "validated": True, "schema_version": 1}
        mock_run_sync.return_value = [
            _make_item(Category="groceries", Company="Recovered Co", ExtractionAudit=extraction),
        ]

        resp = api_client.get("/api/v1/transactions/attention?month=2026-02")
        assert_ok(resp)
        data = resp.json()
        assert data["count"] == 1
        assert data["transactions"][0]["company"] == "Recovered Co"
        assert data["transactions"][0]["extraction_audit"]["method"] == "ai_fallback"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_manual_reviewed_extraction_row_not_in_attention(self, mock_run_sync: AsyncMock, api_client) -> None:
        """Once the user touches an extracted row (CategoryAudit source becomes
        manual/manual_edit/manual_bulk/audit) it drops out of attention."""
        extraction = {"method": "ai_fallback", "model": "gpt-5.4-nano", "validated": True, "schema_version": 1}
        items = [
            _make_item(
                Category="groceries",
                Company="Reviewed Co",
                ExtractionAudit=extraction,
                CategoryAudit={"source": src, "reviewed_at": "2026-06-09T00:00:00-07:00"},
            )
            for src in ("manual", "manual_edit", "manual_bulk", "audit")
        ]
        mock_run_sync.return_value = items

        resp = api_client.get("/api/v1/transactions/attention?month=2026-02")
        assert_ok(resp)
        data = resp.json()
        assert data["count"] == 0
        assert data["transactions"] == []

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_plain_rows_attention_unaffected_by_extraction_clause(self, mock_run_sync: AsyncMock, api_client) -> None:
        """Rows with no ExtractionAudit keep today's miscellaneous-only behavior."""
        mock_run_sync.return_value = [
            _make_item(Category="miscellaneous", Company="Needs Review"),
            _make_item(Category="groceries", Company="Already Sorted"),
        ]

        resp = api_client.get("/api/v1/transactions/attention?month=2026-02")
        assert_ok(resp)
        data = resp.json()
        assert data["count"] == 1
        assert data["transactions"][0]["company"] == "Needs Review"


class TestIsAttentionExtractionClause:
    """Direct unit tests for the _is_attention extraction clause (clause ordering)."""

    _EXTRACTION = {"method": "ai_fallback", "model": "m", "validated": True, "schema_version": 1}

    def test_extraction_row_needs_attention(self) -> None:
        from src.api.serializers import is_attention as _is_attention

        assert _is_attention(_make_item(Category="groceries", ExtractionAudit=self._EXTRACTION)) is True

    @pytest.mark.parametrize("source", ["manual", "manual_edit", "manual_bulk", "audit"])
    def test_extraction_row_cleared_by_manual_review(self, source: str) -> None:
        from src.api.serializers import is_attention as _is_attention

        item = _make_item(
            Category="groceries",
            ExtractionAudit=self._EXTRACTION,
            CategoryAudit={"source": source},
        )
        assert _is_attention(item) is False

    def test_extraction_row_with_ai_category_audit_still_attention(self) -> None:
        from src.api.serializers import is_attention as _is_attention

        item = _make_item(
            Category="groceries",
            ExtractionAudit=self._EXTRACTION,
            CategoryAudit={"source": "ai"},
        )
        assert _is_attention(item) is True

    def test_ignored_or_deleted_extraction_row_excluded(self) -> None:
        from src.api.serializers import is_attention as _is_attention

        ignored = _make_item(Category="groceries", ExtractionAudit=self._EXTRACTION, Ignored=True)
        deleted = _make_item(Category="groceries", ExtractionAudit=self._EXTRACTION, DeletedAt="2026-06-09T00:00:00Z")
        assert _is_attention(ignored) is False
        assert _is_attention(deleted) is False

    def test_plain_row_unaffected(self) -> None:
        from src.api.serializers import is_attention as _is_attention

        # No ExtractionAudit → miscellaneous-only behavior preserved exactly.
        assert _is_attention(_make_item(Category="miscellaneous")) is True
        assert _is_attention(_make_item(Category="groceries")) is False
