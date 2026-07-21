"""Tests for GET /api/v1/overrides/match — the preview-match endpoint used by
the CategoryRulesSection add-rule hint widget."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from src.api.dependencies import get_embedding_cache, get_openai_client
from src.api.main import app
from tests.asserts import assert_ok, assert_problem


def _ctx(
    overrides: dict[str, str],
    aliases: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build the (overrides, aliases) tuple that get_override_context returns."""
    return (overrides, aliases or {})


@pytest.fixture
def no_openai() -> Iterator[None]:
    """Force the openai dependency to return None so Tier 3 is skipped cleanly."""
    app.dependency_overrides[get_openai_client] = lambda: None
    yield
    app.dependency_overrides.pop(get_openai_client, None)


@pytest.fixture
def mock_openai_suggester() -> Iterator[MagicMock]:
    """Override both the openai dependency and the suggester class, returning a
    MagicMock the test can configure for Tier 3 behavior."""
    suggester = MagicMock()
    suggester.embed_one.return_value = [0.1, 0.2, 0.3]

    app.dependency_overrides[get_openai_client] = lambda: MagicMock()
    app.dependency_overrides[get_embedding_cache] = lambda: MagicMock()

    patcher = patch("src.api.routers.overrides.CategorySuggester", return_value=suggester)
    patcher.start()
    yield suggester
    patcher.stop()
    app.dependency_overrides.pop(get_openai_client, None)
    app.dependency_overrides.pop(get_embedding_cache, None)


class TestMatchEndpointTier0:
    @patch("src.api.routers.overrides.get_override_context")
    def test_exact_hit_populates_top_level_and_first_candidate(
        self, mock_ctx: MagicMock, no_openai: None, api_client
    ) -> None:
        mock_ctx.return_value = _ctx({"AMAZON.CA": "Miscellaneous"})
        resp = api_client.get("/api/v1/overrides/match", params={"company": "AMAZON.CA"})
        assert_ok(resp)
        body = resp.json()
        assert body["tier"] == "exact"
        assert body["category"] == "Miscellaneous"
        assert body["matched_rule"] == "AMAZON.CA"
        assert body["confidence"] == 1.0
        # Top candidate mirrors the primary hit.
        assert body["candidates"][0]["matched_rule"] == "AMAZON.CA"
        assert body["candidates"][0]["tier"] == "exact"


class TestMatchEndpointTier1:
    @patch("src.api.routers.overrides.get_override_context")
    def test_normalized_hit_via_store_number(self, mock_ctx: MagicMock, no_openai: None, api_client) -> None:
        mock_ctx.return_value = _ctx({"BOOSTER JUICE #232": "Restaurant/Dining"})
        resp = api_client.get("/api/v1/overrides/match", params={"company": "BOOSTER JUICE #999"})
        assert_ok(resp)
        body = resp.json()
        assert body["tier"] == "normalized"
        assert body["category"] == "Restaurant/Dining"
        assert body["matched_rule"] == "BOOSTER JUICE #232"

    @patch("src.api.routers.overrides.get_override_context")
    def test_ambiguous_normalized_group_returns_null_primary(
        self, mock_ctx: MagicMock, no_openai: None, api_client
    ) -> None:
        mock_ctx.return_value = _ctx(
            {
                "SHOPPERS DRUG MART #123": "Health Care",
                "SHOPPERS DRUG MART #456": "Groceries",
            }
        )
        resp = api_client.get("/api/v1/overrides/match", params={"company": "SHOPPERS DRUG MART #789"})
        assert_ok(resp)
        body = resp.json()
        assert body["tier"] is None
        assert body["category"] is None
        assert body["matched_rule"] is None
        # No suggester (openai_client=None) → no fuzzy candidates either.
        assert body["candidates"] == []


class TestMatchEndpointTier2:
    @patch("src.api.routers.overrides.get_override_context")
    def test_alias_rescue(self, mock_ctx: MagicMock, no_openai: None, api_client) -> None:
        mock_ctx.return_value = _ctx(
            {"AMAZON.CA": "Miscellaneous"},
            aliases={"amzn mktp": "AMAZON.CA"},
        )
        resp = api_client.get("/api/v1/overrides/match", params={"company": "AMZN MKTP CA #8888"})
        assert_ok(resp)
        body = resp.json()
        assert body["tier"] == "alias"
        assert body["category"] == "Miscellaneous"


class TestMatchEndpointTier3Fuzzy:
    """Covers the suggester-backed path. CategorySuggester is mocked so no real
    OpenAI call fires."""

    @patch("src.api.routers.overrides.get_override_context")
    def test_fuzzy_hit_when_tiers_0_1_2_miss(
        self, mock_ctx: MagicMock, mock_openai_suggester: MagicMock, api_client
    ) -> None:
        mock_ctx.return_value = _ctx({"COFFEE SPOT": "Restaurant/Dining"})
        mock_openai_suggester.embedding_match.return_value = ("restaurant/dining", "COFFEE SPOT", 0.93)
        mock_openai_suggester.top_candidates.return_value = [
            ("restaurant/dining", "COFFEE SPOT", 0.93),
            ("restaurant/dining", "COFFEE SPOT #45", 0.82),
        ]

        resp = api_client.get("/api/v1/overrides/match", params={"company": "COFFEE SPOT IN NEW MALL"})
        assert_ok(resp)
        body = resp.json()
        assert body["tier"] == "fuzzy"
        assert body["category"] == "restaurant/dining"
        assert body["matched_rule"] == "COFFEE SPOT"
        assert body["confidence"] == 0.93
        matched_rules = [c["matched_rule"] for c in body["candidates"]]
        assert matched_rules[0] == "COFFEE SPOT"
        assert "COFFEE SPOT #45" in matched_rules

    @patch("src.api.routers.overrides.get_override_context")
    def test_fuzzy_score_below_0_90_is_candidate_only_not_primary(
        self, mock_ctx: MagicMock, mock_openai_suggester: MagicMock, api_client
    ) -> None:
        mock_ctx.return_value = _ctx({"COFFEE SPOT": "Restaurant/Dining"})
        mock_openai_suggester.embedding_match.return_value = ("restaurant/dining", "COFFEE SPOT", 0.82)
        mock_openai_suggester.top_candidates.return_value = [("restaurant/dining", "COFFEE SPOT", 0.82)]

        resp = api_client.get("/api/v1/overrides/match", params={"company": "MAYBE COFFEE SPOT"})
        body = resp.json()
        assert body["tier"] is None
        assert body["candidates"][0]["confidence"] == 0.82


class TestMatchEndpointValidation:
    def test_missing_company_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/overrides/match")
        assert_problem(resp, 422)

    def test_empty_company_returns_422(self, api_client) -> None:
        resp = api_client.get("/api/v1/overrides/match", params={"company": ""})
        assert_problem(resp, 422)

    @patch("src.api.routers.overrides.get_override_context", return_value=({}, {}))
    def test_no_overrides_returns_empty_candidates(self, _mock_ctx: MagicMock, no_openai: None, api_client) -> None:
        resp = api_client.get("/api/v1/overrides/match", params={"company": "ANYTHING"})
        assert_ok(resp)
        body = resp.json()
        assert body["candidates"] == []
        assert body["tier"] is None
