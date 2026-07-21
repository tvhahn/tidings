"""Unit tests for the tiered category override resolver."""

from unittest.mock import MagicMock

from src.finance.category_resolver import (
    ResolvedOverride,
    get_blacklisted_keys,
    resolve_override,
)


class TestTier0Exact:
    def test_exact_match_preserves_casing(self):
        overrides = {"COFFEE SPOT #45": "Restaurant/Dining"}
        result = resolve_override("COFFEE SPOT #45", overrides)
        assert result == ResolvedOverride(
            category="Restaurant/Dining",
            tier="exact",
            matched_rule="COFFEE SPOT #45",
            confidence=1.0,
        )

    def test_exact_match_is_case_insensitive(self):
        overrides = {"AMAZON.CA": "Miscellaneous"}
        result = resolve_override("amazon.ca", overrides)
        assert result is not None
        assert result.tier == "exact"
        assert result.category == "Miscellaneous"
        assert result.matched_rule == "AMAZON.CA"


class TestTier1Normalized:
    def test_normalized_match_via_store_number_suffix(self):
        overrides = {"BOOSTER JUICE #232": "Restaurant/Dining"}
        result = resolve_override("BOOSTER JUICE #999", overrides)
        assert result is not None
        assert result.tier == "normalized"
        assert result.category == "Restaurant/Dining"
        assert result.matched_rule == "BOOSTER JUICE #232"
        assert result.confidence == 1.0

    def test_normalized_hit_collapses_multiple_variants(self):
        overrides = {
            "NORTHWIND BOOKS #004": "Hobbies",
            "NORTHWIND BOOKS #007": "Hobbies",
        }
        result = resolve_override("NORTHWIND BOOKS #099", overrides)
        assert result is not None
        assert result.tier == "normalized"
        assert result.category == "Hobbies"
        # matched_rule is the first-encountered override key, not the normalized form
        assert result.matched_rule == "NORTHWIND BOOKS #004"

    def test_ambiguous_group_is_blacklisted(self):
        overrides = {
            "SHOPPERS DRUG MART #123": "Health Care",
            "SHOPPERS DRUG MART #456": "Groceries",
        }
        assert resolve_override("SHOPPERS DRUG MART #789", overrides) is None

    def test_unanimity_with_category_case_variation(self):
        # Spec's explicit tradeoff: `Restaurant/Dining` + `restaurant/dining`
        # compare equal after .strip().lower() and count as unanimous.
        overrides = {
            "BOOSTER JUICE #232": "Restaurant/Dining",
            "BOOSTER JUICE #345": "restaurant/dining",
        }
        result = resolve_override("BOOSTER JUICE #999", overrides)
        assert result is not None
        assert result.tier == "normalized"
        # First-encountered (original-case) wins as the canonical value.
        assert result.category == "Restaurant/Dining"


class TestTier2Alias:
    def test_alias_rescues_cleaned_form(self):
        # Alias key must match the CLEANED form (cleanup runs before alias lookup),
        # so "amzn mktp" — not "amzn mktp ca" — is the alias key once ` CA` and
        # ` #8888` are stripped.
        overrides = {"AMAZON.CA": "Miscellaneous"}
        aliases = {"amzn mktp": "AMAZON.CA"}
        result = resolve_override("AMZN MKTP CA #8888", overrides, aliases=aliases)
        assert result is not None
        assert result.tier == "alias"
        assert result.category == "Miscellaneous"
        assert result.matched_rule == "AMAZON.CA"

    def test_aliases_none_skips_tier_2(self):
        overrides = {"AMAZON.CA": "Miscellaneous"}
        # Without aliases, AMZN MKTP normalizes to "amzn mktp" — no match against
        # "amazon.ca". Returns None (falls through to OpenAI in Lambda).
        assert resolve_override("AMZN MKTP CA #8888", overrides) is None

    def test_empty_aliases_dict_skips_tier_2(self):
        overrides = {"AMAZON.CA": "Miscellaneous"}
        assert resolve_override("AMZN MKTP CA #8888", overrides, aliases={}) is None


class TestTierOrdering:
    def test_exact_wins_over_normalized(self):
        # Both tiers would match — exact must win because it's cheaper and
        # carries the most specific matched_rule.
        overrides = {
            "BOOSTER JUICE #232": "Restaurant/Dining",
            "BOOSTER JUICE #345": "Restaurant/Dining",
        }
        result = resolve_override("BOOSTER JUICE #232", overrides)
        assert result is not None
        assert result.tier == "exact"
        assert result.matched_rule == "BOOSTER JUICE #232"

    def test_normalized_wins_over_alias(self):
        overrides = {"BOOSTER JUICE #232": "Restaurant/Dining"}
        # Even with aliases present, Tier 1 hits first.
        aliases = {"booster juice": "SOMETHING ELSE"}
        result = resolve_override("BOOSTER JUICE #999", overrides, aliases=aliases)
        assert result is not None
        assert result.tier == "normalized"


class TestEdgeCases:
    def test_empty_company_returns_none(self):
        assert resolve_override("", {"FOO": "bar"}) is None

    def test_empty_overrides_returns_none(self):
        assert resolve_override("FOO", {}) is None

    def test_no_match_returns_none(self):
        assert resolve_override("UNKNOWN MERCHANT", {"FOO": "bar"}) is None


class TestTier3Fuzzy:
    """Suggester-backed fallback when Tiers 0/1/2 miss."""

    def _make_suggester(
        self,
        match_result: tuple[str, str, float] | None = None,
        vector: list[float] | None = None,
    ) -> MagicMock:
        suggester = MagicMock(name="suggester")
        suggester.embed_one.return_value = vector or [0.1, 0.2, 0.3]
        suggester.embedding_match.return_value = match_result
        return suggester

    def test_fuzzy_hit_when_tiers_miss(self):
        overrides = {"COFFEE SPOT": "Restaurant/Dining"}
        suggester = self._make_suggester(match_result=("restaurant/dining", "COFFEE SPOT", 0.93))
        result = resolve_override("COFFEE SPOT IN NEW MALL", overrides, suggester=suggester)
        assert result is not None
        assert result.tier == "fuzzy"
        assert result.category == "restaurant/dining"
        assert result.matched_rule == "COFFEE SPOT"
        assert result.confidence == 0.93

    def test_fuzzy_score_below_min_confidence_returns_none(self):
        overrides = {"COFFEE SPOT": "Restaurant/Dining"}
        suggester = self._make_suggester(match_result=("restaurant/dining", "COFFEE SPOT", 0.85))
        # Default min_confidence=0.90 → 0.85 rejected
        assert resolve_override("MAYBE COFFEE SPOT", overrides, suggester=suggester) is None

    def test_fuzzy_score_at_custom_threshold_hits(self):
        overrides = {"COFFEE SPOT": "Restaurant/Dining"}
        suggester = self._make_suggester(match_result=("restaurant/dining", "COFFEE SPOT", 0.86))
        result = resolve_override("MAYBE COFFEE SPOT", overrides, suggester=suggester, min_confidence=0.85)
        assert result is not None
        assert result.tier == "fuzzy"

    def test_suggester_none_skips_tier_3(self):
        overrides = {"COFFEE SPOT": "Restaurant/Dining"}
        # No suggester → no Tier 3; novel phrasing returns None.
        assert resolve_override("COFFEE SPOT IN NEW MALL", overrides) is None

    def test_suggester_with_no_match_returns_none(self):
        overrides = {"COFFEE SPOT": "Restaurant/Dining"}
        suggester = self._make_suggester(match_result=None)
        assert resolve_override("TOTALLY UNRELATED", overrides, suggester=suggester) is None

    def test_tier_3_is_skipped_when_earlier_tier_hits(self):
        overrides = {"COFFEE SPOT": "Restaurant/Dining"}
        suggester = self._make_suggester(match_result=("something/else", "OTHER", 0.99))
        # Exact match should win — suggester must not even be consulted.
        result = resolve_override("COFFEE SPOT", overrides, suggester=suggester)
        assert result is not None
        assert result.tier == "exact"
        suggester.embed_one.assert_not_called()


class TestGetBlacklistedKeys:
    def test_returns_tier1_conflict_groups(self):
        overrides = {
            "SHOPPERS DRUG MART #123": "Health Care",
            "SHOPPERS DRUG MART #456": "Groceries",
            "AMAZON.CA": "Miscellaneous",  # unanimous — must NOT appear
        }
        blacklisted = get_blacklisted_keys(overrides)
        assert "shoppers drug mart" in blacklisted
        keys = {k for k, _ in blacklisted["shoppers drug mart"]}
        assert keys == {"SHOPPERS DRUG MART #123", "SHOPPERS DRUG MART #456"}
        assert "amazon.ca" not in blacklisted

    def test_unanimous_groups_excluded(self):
        overrides = {
            "COFFEE SPOT #45": "Restaurant/Dining",
            "COFFEE SPOT #99": "Restaurant/Dining",
        }
        assert get_blacklisted_keys(overrides) == {}

    def test_alias_substitution_can_create_or_resolve_conflicts(self):
        overrides = {"ACME": "CategoryA", "WIDGET": "CategoryB"}
        aliases = {"widget": "ACME"}
        # Without aliases — no shared key, no conflict.
        assert get_blacklisted_keys(overrides) == {}
        # With aliases — both collapse to "acme" with disagreeing categories.
        tier2 = get_blacklisted_keys(overrides, aliases=aliases)
        assert "acme" in tier2
        assert {v for _, v in tier2["acme"]} == {"CategoryA", "CategoryB"}

    def test_case_insensitive_unanimity_rule_matches_resolver(self):
        # Spec tradeoff: "Restaurant/Dining" + "restaurant/dining" are unanimous.
        overrides = {
            "BOOSTER JUICE #232": "Restaurant/Dining",
            "BOOSTER JUICE #345": "restaurant/dining",
        }
        assert get_blacklisted_keys(overrides) == {}


class TestTier2AliasInteraction:
    """Aliases change the Tier 2 blacklist independently of Tier 1."""

    def test_alias_creates_tier_2_conflict(self):
        """An alias that merges two distinct override keys into the same alias-resolved
        key with different categories blacklists the alias-resolved key in Tier 2."""
        overrides = {"ACME": "CategoryA", "WIDGET": "CategoryB"}
        aliases = {"widget": "ACME"}
        # Tier 0 still hits ACME literally — unaffected by Tier 2 blacklist.
        acme_result = resolve_override("ACME", overrides, aliases=aliases)
        assert acme_result is not None
        assert acme_result.tier == "exact"
        # Input `WIDGET WORLD` misses Tier 0 (not literal) and Tier 1 (normalizes to
        # "widget world", no match). Tier 2 normalizes + aliases to "ACME", where the
        # alias-map contains both (ACME, CategoryA) and (WIDGET, CategoryB) → blacklisted.
        assert resolve_override("WIDGET WORLD", overrides, aliases=aliases) is None
