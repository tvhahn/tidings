"""Tests for the externalized config loader (src/finance/config.py)."""

import logging
from unittest.mock import patch

import pytest

import src.finance.config_loader as config_module
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


# ---------------------------------------------------------------------------
# NOTIFICATION_BLOCKED_COMPANIES — the Lambda's personal-config channel
# ---------------------------------------------------------------------------

# Synthetic, non-identifying stand-ins. Real entries are merchant names, so the
# assertions below also prove none of them reach a log record.
ENV_VAR = "NOTIFICATION_BLOCKED_COMPANIES"
ENTRY_A = "SyntheticStreamCo"
ENTRY_B = "SyntheticNewsHound"


class TestBlockedCompaniesEnv:
    """The env var unions into the bundled seed and is never cached."""

    @pytest.fixture(autouse=True)
    def _no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Start every test with the env channel closed."""
        monkeypatch.delenv(ENV_VAR, raising=False)

    def _seed_bundled(self, entries: list[str]) -> None:
        """Pin the bundled seed without touching the shipped JSON file.

        ``_simple_caches`` is module state the root conftest clears per test.
        """
        config_module._simple_caches["blocked_companies.json"] = entries

    def test_bundled_only_when_env_absent(self) -> None:
        self._seed_bundled([ENTRY_A])
        assert get_blocked_companies() == [ENTRY_A]

    def test_env_comma_separated_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_bundled([])
        monkeypatch.setenv(ENV_VAR, f" {ENTRY_A} , {ENTRY_B} , ")
        assert get_blocked_companies() == [ENTRY_A, ENTRY_B]

    def test_env_json_array(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_bundled([])
        monkeypatch.setenv(ENV_VAR, f'  ["{ENTRY_A}", " {ENTRY_B} ", ""]  ')
        assert get_blocked_companies() == [ENTRY_A, ENTRY_B]

    def test_union_keeps_bundled_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_bundled([ENTRY_A])
        monkeypatch.setenv(ENV_VAR, ENTRY_B)
        assert get_blocked_companies() == [ENTRY_A, ENTRY_B]

    def test_union_dedupes_case_insensitively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_bundled([ENTRY_A])
        monkeypatch.setenv(ENV_VAR, f"{ENTRY_A.lower()},{ENTRY_B}")
        assert get_blocked_companies() == [ENTRY_A, ENTRY_B]

    def test_env_internal_duplicates_collapse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._seed_bundled([])
        monkeypatch.setenv(ENV_VAR, f"{ENTRY_A},{ENTRY_A.upper()},{ENTRY_B}")
        assert get_blocked_companies() == [ENTRY_A, ENTRY_B]

    def test_malformed_json_warns_and_keeps_bundled(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._seed_bundled([ENTRY_A])
        monkeypatch.setenv(ENV_VAR, f'["{ENTRY_B}"')  # unterminated array
        with caplog.at_level(logging.WARNING):
            result = get_blocked_companies()
        assert result == [ENTRY_A]
        assert ENV_VAR in caplog.text

    def test_non_string_json_entry_warns_and_keeps_bundled(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._seed_bundled([ENTRY_A])
        monkeypatch.setenv(ENV_VAR, f'["{ENTRY_B}", 7]')
        with caplog.at_level(logging.WARNING):
            result = get_blocked_companies()
        assert result == [ENTRY_A]
        assert ENV_VAR in caplog.text

    def test_value_not_starting_with_bracket_is_a_comma_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only a leading '[' selects the JSON form — everything else splits on commas."""
        self._seed_bundled([])
        monkeypatch.setenv(ENV_VAR, f'{{"a": "{ENTRY_B}"}}')
        assert get_blocked_companies() == [f'{{"a": "{ENTRY_B}"}}']

    def test_blank_env_keeps_the_cached_seed_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env value must be byte-for-byte the old behaviour — same object."""
        monkeypatch.setenv(ENV_VAR, "   ")
        assert get_blocked_companies() is get_blocked_companies()

    def test_env_change_is_picked_up_without_a_restart(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Never cached: a Lambda env-map update takes effect on the next call."""
        self._seed_bundled([])
        monkeypatch.setenv(ENV_VAR, ENTRY_A)
        assert get_blocked_companies() == [ENTRY_A]
        monkeypatch.setenv(ENV_VAR, f"{ENTRY_A},{ENTRY_B}")
        assert get_blocked_companies() == [ENTRY_A, ENTRY_B]
        monkeypatch.delenv(ENV_VAR)
        assert get_blocked_companies() == []

    @pytest.mark.parametrize(
        "raw",
        [
            f"{ENTRY_A},{ENTRY_B}",
            f'["{ENTRY_A}", "{ENTRY_B}"]',
            f'["{ENTRY_A}", 7]',
            f'["{ENTRY_A}"',
        ],
    )
    def test_entries_never_reach_a_log_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
    ) -> None:
        """Blocked companies are personal merchant names — logs carry counts only."""
        self._seed_bundled([])
        monkeypatch.setenv(ENV_VAR, raw)
        with caplog.at_level(logging.DEBUG):
            get_blocked_companies()
        for record in caplog.records:
            rendered = record.getMessage() + str(record.args)
            assert ENTRY_A not in rendered
            assert ENTRY_B not in rendered
        assert ENTRY_A not in caplog.text
        assert ENTRY_B not in caplog.text
