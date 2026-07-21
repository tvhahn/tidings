"""Tests for the merchant aliases API endpoints.

Lifts ``src/api/routers/merchant_aliases.py`` from 43% to >90% coverage —
the audit (/review-tests) flagged it as the only router without a dedicated
test file. Mirrors the post-codemod patterns in ``test_api_overrides.py``.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.asserts import assert_ok, assert_problem


def _make_aliases_item(
    data: dict[str, str] | None = None,
    version: int = 1,
) -> dict[str, Any]:
    """Shape the merchant_aliases router expects from
    ``MerchantAliasService.get_aliases()``."""
    if data is None:
        data = {"costco #1234": "Costco", "shell #567": "Shell"}
    return {
        "PK": "USER#default",
        "SK": "CONFIG#merchant_aliases",
        "Data": data,
        "Version": version,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/merchant-aliases
# ---------------------------------------------------------------------------


class TestListAliases:
    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_returns_aliases_sorted(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = _make_aliases_item()
        body = assert_ok(api_client.get("/api/v1/merchant-aliases"))
        assert body["count"] == 2
        assert body["version"] == 1
        # Sorted by raw_name (lowercased map key)
        names = [a["raw_name"] for a in body["aliases"]]
        assert names == sorted(names)

    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_returns_empty_when_unseeded(self, mock_run_sync: AsyncMock, api_client) -> None:
        mock_run_sync.return_value = None
        body = assert_ok(api_client.get("/api/v1/merchant-aliases"))
        assert body["count"] == 0
        assert body["version"] == 0
        assert body["aliases"] == []


# ---------------------------------------------------------------------------
# Endpoint PUT /api/v1/merchant-aliases/{raw_name}
# ---------------------------------------------------------------------------


class TestPutAlias:
    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_returns_ok_on_create(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_aliases before-image (None → create-shaped), then put_alias → version.
        mock_run_sync.side_effect = [None, 2]
        body = assert_ok(
            api_client.put(
                "/api/v1/merchant-aliases/COSTCO%20%231234",
                json={"canonical_name": "Costco"},
            )
        )
        assert body["ok"] is True

    def test_validation_error_on_missing_canonical_name(self, api_client) -> None:
        # Empty body trips pydantic; the unified envelope handles it.
        assert_problem(api_client.put("/api/v1/merchant-aliases/X", json={}), 422)


# ---------------------------------------------------------------------------
# Endpoint DELETE /api/v1/merchant-aliases/{raw_name}
# ---------------------------------------------------------------------------


class TestDeleteAlias:
    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_returns_ok_on_existing(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_aliases before-image, then delete_alias -> bumped version.
        mock_run_sync.side_effect = [None, 3]
        body = assert_ok(api_client.delete("/api/v1/merchant-aliases/costco%20%231234"))
        assert body["ok"] is True

    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_returns_404_on_missing(self, mock_run_sync: AsyncMock, api_client) -> None:
        # get_aliases before-image succeeds; delete_alias raises KeyError.
        mock_run_sync.side_effect = [None, KeyError("nonexistent")]
        assert_problem(
            api_client.delete("/api/v1/merchant-aliases/nonexistent"),
            404,
        )


# ---------------------------------------------------------------------------
# Cache invalidation — both PUT and DELETE must clear the resolver cache so
# subsequent transactions see the new alias mapping.
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_put_invalidates_override_context(
        self,
        mock_run_sync: AsyncMock,
        api_client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[None] = []
        monkeypatch.setattr(
            "src.api.routers.merchant_aliases.invalidate_override_context_cache",
            lambda: calls.append(None),
        )
        mock_run_sync.side_effect = [None, 1]  # get_aliases before-image, then put_alias
        api_client.put("/api/v1/merchant-aliases/foo", json={"canonical_name": "Foo"})
        assert len(calls) == 1

    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_delete_invalidates_override_context(
        self,
        mock_run_sync: AsyncMock,
        api_client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[None] = []
        monkeypatch.setattr(
            "src.api.routers.merchant_aliases.invalidate_override_context_cache",
            lambda: calls.append(None),
        )
        mock_run_sync.side_effect = [None, 2]  # get_aliases before-image, then delete_alias
        api_client.delete("/api/v1/merchant-aliases/foo")
        assert len(calls) == 1

    @pytest.mark.parametrize("mock_run_sync", ["merchant_aliases"], indirect=True)
    def test_404_does_not_invalidate(
        self,
        mock_run_sync: AsyncMock,
        api_client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed DELETE must leave the cache alone — otherwise a 404
        could thrash the resolver cache for unrelated traffic."""
        calls: list[None] = []
        monkeypatch.setattr(
            "src.api.routers.merchant_aliases.invalidate_override_context_cache",
            lambda: calls.append(None),
        )
        # get_aliases before-image succeeds; delete_alias raises KeyError (-> 404).
        mock_run_sync.side_effect = [None, KeyError("missing")]
        api_client.delete("/api/v1/merchant-aliases/missing")
        assert calls == []
