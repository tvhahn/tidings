"""Tests for the categories API endpoint.

`/categories` reads the active vocabulary from storage (DynamoDB/SQLite via
`get_category_list()`), returning the user's customized list when present and the
bundled seed JSON only as a fallback. We drive it through the shared `mock_run_sync`
fixture (which patches `src.api.routers.categories.run_sync`) so the tests are
hermetic and don't depend on the host's storage backend.
"""

import pytest

from tests.asserts import assert_ok


@pytest.mark.parametrize("mock_run_sync", ["categories"], indirect=True)
class TestListCategories:
    def test_returns_categories(self, mock_run_sync, api_client):
        mock_run_sync.return_value = ["Groceries", "Miscellaneous"]
        resp = api_client.get("/api/v1/categories")
        assert_ok(resp)

        data = resp.json()
        assert "categories" in data
        assert isinstance(data["categories"], list)

    def test_returns_storage_list_verbatim(self, mock_run_sync, api_client):
        """The active list is returned raw — no title-casing that would corrupt
        custom strings like 'Hygiene/Personal care' or 'Misc. Car Expense'."""
        custom = ["Liquor/Beer/Wine", "Hygiene/Personal care", "Misc. Car Expense"]
        mock_run_sync.return_value = list(custom)
        resp = api_client.get("/api/v1/categories")
        assert_ok(resp)
        assert resp.json()["categories"] == custom

    def test_count_matches_storage(self, mock_run_sync, api_client):
        """Count tracks the stored list, not the seed file's length."""
        stored = [f"Cat {i}" for i in range(46)]
        mock_run_sync.return_value = stored
        resp = api_client.get("/api/v1/categories")
        assert len(resp.json()["categories"]) == 46

    def test_contains_miscellaneous(self, mock_run_sync, api_client):
        mock_run_sync.return_value = ["Groceries", "Miscellaneous"]
        resp = api_client.get("/api/v1/categories")
        assert "Miscellaneous" in resp.json()["categories"]
