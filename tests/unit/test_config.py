"""Tests for the externalized config loader (src/finance/config.py)."""

from unittest.mock import patch

from src.finance.config_loader import (
    get_blocked_companies,
    get_card_name_mappings,
    get_categories,
    get_category_list,
    get_category_overrides,
    get_override_context,
    invalidate_categories_cache,
    invalidate_category_overrides_cache,
    invalidate_override_context_cache,
)


class TestGetCategories:
    def test_returns_list(self):
        assert isinstance(get_categories(), list)

    def test_contains_miscellaneous_fallback(self):
        assert "Miscellaneous" in get_categories()

    def test_caching_returns_same_object(self):
        first = get_categories()
        second = get_categories()
        assert first is second


class TestGetCategoryList:
    """Storage-backed active category vocabulary with seed-JSON fallback."""

    def _patch_category_svc(self, categories: list[str]):
        class _StubSvc:
            def get_categories_list(self):
                return list(categories)

        # Patch the factory, not a concrete class — it routes between DynamoDB
        # and SQLite based on app_config, so patching one backend is bypassed in
        # the other branch (same reasoning as TestGetOverrideContext).
        return patch("src.finance.storage.create_category_service", return_value=_StubSvc())

    def test_returns_stored_list_raw(self):
        """Reads storage first and returns values verbatim — no title-casing."""
        invalidate_categories_cache()
        custom = ["Liquor/Beer/Wine", "Hygiene/Personal care", "Misc. Car Expense"]
        with self._patch_category_svc(custom):
            result = get_category_list()
        assert result == custom

    def test_caches_on_second_call(self):
        invalidate_categories_cache()
        with self._patch_category_svc(["First"]):
            first = get_category_list()
        with self._patch_category_svc(["Second"]):
            second = get_category_list()
        # Second call hits the 5-minute cache — sees "First", not "Second".
        assert first == ["First"]
        assert second == ["First"]

    def test_invalidate_forces_refresh(self):
        invalidate_categories_cache()
        with self._patch_category_svc(["First"]):
            get_category_list()
        invalidate_categories_cache()
        with self._patch_category_svc(["Second"]):
            result = get_category_list()
        assert result == ["Second"]

    def test_falls_back_to_seed_when_storage_unavailable(self):
        """If the storage lookup raises, fail open to the bundled seed JSON."""
        invalidate_categories_cache()
        with patch(
            "src.finance.storage.create_category_service",
            side_effect=RuntimeError("DynamoDB unreachable"),
        ):
            result = get_category_list()
        assert result == get_categories()
        assert "Miscellaneous" in result


class TestGetCardNameMappings:
    def test_returns_dict(self):
        assert isinstance(get_card_name_mappings(), dict)

    def test_has_rbc_entry(self):
        mappings = get_card_name_mappings()
        assert "RBC" in mappings
        assert isinstance(mappings["RBC"], dict)

    def test_has_mbna_entry(self):
        mappings = get_card_name_mappings()
        assert "MBNA" in mappings
        assert isinstance(mappings["MBNA"], dict)

    def test_caching_returns_same_object(self):
        first = get_card_name_mappings()
        second = get_card_name_mappings()
        assert first is second


class TestGetBlockedCompanies:
    def test_returns_list(self):
        assert isinstance(get_blocked_companies(), list)

    def test_seed_default_is_empty(self):
        # The shipped seed is an empty suppression list — the honest
        # fresh-install default. Users populate their own blocked companies.
        assert get_blocked_companies() == []

    def test_caching_returns_same_object(self):
        first = get_blocked_companies()
        second = get_blocked_companies()
        assert first is second


class TestGetCategoryOverrides:
    def test_returns_dict(self):
        assert isinstance(get_category_overrides(), dict)

    def test_caching_returns_same_object(self):
        first = get_category_overrides()
        second = get_category_overrides()
        assert first is second


class TestGetOverrideContext:
    """Bundled overrides + aliases cache."""

    def _patch_alias_svc(self, aliases_map: dict[str, str]):
        class _StubSvc:
            def get_aliases_map(self):
                return dict(aliases_map)

        # Patch the factory rather than the underlying class — the factory
        # routes between DynamoDB and SQLite based on app_config, so patching
        # one concrete class is bypassed in the other backend's branch.
        return patch("src.finance.storage.create_merchant_alias_service", return_value=_StubSvc())

    def test_returns_overrides_and_aliases_tuple(self):
        invalidate_override_context_cache()
        with self._patch_alias_svc({"amzn mktp": "AMAZON.CA"}):
            overrides, aliases = get_override_context()
        assert isinstance(overrides, dict)
        assert aliases == {"amzn mktp": "AMAZON.CA"}

    def test_caches_on_second_call(self):
        invalidate_override_context_cache()
        with self._patch_alias_svc({"first": "FIRST"}):
            first = get_override_context()
        with self._patch_alias_svc({"second": "SECOND"}):
            second = get_override_context()
        # Second call hits the cache — sees "first" aliases, not "second"
        assert first is second
        assert second[1] == {"first": "FIRST"}

    def test_invalidate_context_forces_refresh(self):
        invalidate_override_context_cache()
        with self._patch_alias_svc({"first": "FIRST"}):
            get_override_context()
        invalidate_override_context_cache()
        with self._patch_alias_svc({"second": "SECOND"}):
            _, aliases = get_override_context()
        assert aliases == {"second": "SECOND"}

    def test_invalidating_overrides_also_invalidates_context(self):
        """Override mutations (PUT/DELETE) call invalidate_category_overrides_cache — it must chain."""
        invalidate_override_context_cache()
        with self._patch_alias_svc({"first": "FIRST"}):
            get_override_context()
        invalidate_category_overrides_cache()
        with self._patch_alias_svc({"second": "SECOND"}):
            _, aliases = get_override_context()
        assert aliases == {"second": "SECOND"}

    def test_alias_fetch_failure_fails_open_to_empty(self):
        """If DynamoDB alias read raises, aliases default to {} (Tier 0/1 still work)."""
        invalidate_override_context_cache()
        with patch(
            "src.finance.merchant_alias_service.MerchantAliasService",
            side_effect=RuntimeError("DynamoDB unreachable"),
        ):
            overrides, aliases = get_override_context()
        assert aliases == {}
        assert isinstance(overrides, dict)
