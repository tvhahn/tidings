"""Tests for the tx_id-shaped transaction endpoints + 308 redirects from
the legacy composite-key URLs.

Covers the spec at
`docs/specs/01_backend-as-platform/2026-04-30-stable-transaction-ids/`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from src.finance.tx_id import composite_from_tx_id, tx_id_from_composite
from tests.asserts import assert_ok, assert_problem, assert_status
from tests.factories import make_transaction_item

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

FWD = "alerts@example.com"
DFN = "2026.04.15_14.32_rbc-purchase.eml"
TX_ID = tx_id_from_composite(FWD, DFN)


def _make_item(**overrides: Any) -> dict[str, Any]:
    """Stored transaction item for the tx_id under test.

    Thin wrapper over the shared ``make_transaction_item`` factory, pinning
    ForwardedTo/DateFileName to this module's FWD/DFN so the derived tx_id round
    trips through the endpoints.
    """
    base = make_transaction_item(ForwardedTo=FWD, DateFileName=DFN, Ignored=False)
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# tx_id is included in response payloads
# ---------------------------------------------------------------------------


class TestTxIdInResponses:
    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_tx_id_in_get_detail(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = _make_item()
        resp = api_client.get(f"/api/v1/transactions/{TX_ID}/detail")
        assert_ok(resp)
        body = resp.json()
        assert body["tx_id"] == TX_ID
        assert body["forwarded_to"] == FWD
        assert body["date_file_name"] == DFN

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_tx_id_in_patch_response(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_item (ledger before-image) then update_category (returns old category).
        mock_run_sync.side_effect = [None, "Restaurant/Dining"]
        resp = api_client.patch(f"/api/v1/transactions/{TX_ID}", json={"category": "Groceries"})
        assert_ok(resp)
        body = resp.json()
        assert body["tx_id"] == TX_ID
        assert body["new_category"] == "groceries"

    def test_tx_id_round_trip_via_decode(self) -> None:
        # The tx_id we issued decodes back to the original composite.
        assert composite_from_tx_id(TX_ID) == (FWD, DFN)


# ---------------------------------------------------------------------------
# 308 redirect from legacy URL → tx_id URL
# ---------------------------------------------------------------------------


class TestLegacyRedirects:
    @pytest.fixture
    def no_follow(self, api_client: TestClient) -> TestClient:
        # TestClient follows redirects by default; turn that off so we can
        # observe the 308 + headers directly.
        api_client.follow_redirects = False
        return api_client

    def test_legacy_get_detail_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.get(f"/api/v1/transactions/{FWD}/{DFN}/detail")
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}/detail"
        assert resp.headers.get("deprecation") == "true"
        assert "successor-version" in resp.headers.get("link", "")

    def test_legacy_patch_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.patch(
            f"/api/v1/transactions/{FWD}/{DFN}",
            json={"category": "Groceries"},
        )
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}"

    def test_legacy_delete_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.delete(f"/api/v1/transactions/{FWD}/{DFN}")
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}"

    def test_legacy_post_review_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.post(f"/api/v1/transactions/{FWD}/{DFN}/review")
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}/review"

    def test_legacy_post_ignore_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.post(
            f"/api/v1/transactions/{FWD}/{DFN}/ignore",
            json={"ignored": True},
        )
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}/ignore"

    def test_legacy_put_comment_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.put(
            f"/api/v1/transactions/{FWD}/{DFN}/comment",
            json={"comment": "test"},
        )
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}/comment"

    def test_legacy_post_delete_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.post(
            f"/api/v1/transactions/{FWD}/{DFN}/delete",
            json={"deleted": True},
        )
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}/delete"

    def test_legacy_put_fields_redirects(self, no_follow: TestClient) -> None:
        resp = no_follow.put(
            f"/api/v1/transactions/{FWD}/{DFN}/fields",
            json={"company": "TEST"},
        )
        assert_status(resp, 308)
        assert resp.headers["location"] == f"/api/v1/transactions/{TX_ID}/fields"

    @pytest.mark.parametrize("mock_run_sync", ["transactions"], indirect=True)
    def test_following_redirect_reaches_canonical(self, mock_run_sync: AsyncMock, api_client) -> None:
        """End-to-end: follow the redirect and confirm the final 200."""
        mock_run_sync.return_value = _make_item()
        # follow_redirects=True (TestClient default)
        resp = api_client.get(f"/api/v1/transactions/{FWD}/{DFN}/detail")
        assert_ok(resp)
        body = resp.json()
        assert body["tx_id"] == TX_ID


# ---------------------------------------------------------------------------
# Bad tx_id → 404 (not 500)
# ---------------------------------------------------------------------------


class TestBadTxId:
    def test_garbage_tx_id_returns_404(self, api_client) -> None:
        resp = api_client.get("/api/v1/transactions/!!!not-base64!!!/detail")
        # FastAPI may interpret this as a literal route mismatch (404) or
        # decode failure (422). Either is acceptable; the contract is
        # "not 500". A range check, so assert_problem (single-status) doesn't fit.
        assert resp.status_code in (404, 422)

    def test_tx_id_without_separator_returns_404(self, api_client) -> None:
        import base64

        # Encoded "no-separator" decodes to a string with no `|`.
        bad = base64.urlsafe_b64encode(b"no-separator-here").rstrip(b"=").decode()
        resp = api_client.get(f"/api/v1/transactions/{bad}/detail")
        assert_problem(resp, 404)
