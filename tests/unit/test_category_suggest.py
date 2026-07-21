"""Tests for embedding-based category suggestion."""

import math
from pathlib import Path
from unittest.mock import MagicMock

from src.finance.category_suggest import CategorySuggester, _cosine_similarity
from src.finance.embedding_cache import EmbeddingCache


def _unit_vector(dims: int, index: int) -> list[float]:
    """Create a unit vector with 1.0 at the given index, 0.0 elsewhere."""
    v = [0.0] * dims
    v[index] = 1.0
    return v


def _similar_vector(base: list[float], noise: float = 0.05) -> list[float]:
    """Create a vector similar to base by adding small noise to non-primary dims."""
    v = list(base)
    for i in range(len(v)):
        if v[i] == 0.0:
            v[i] = noise
    # Re-normalize
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


class TestCosimSimilarity:
    def test_identical_vectors(self):
        v = [0.5, 0.5, 0.5, 0.5]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-9

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(a, b)) < 1e-9

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0


class TestExactMatch:
    def test_exact_match_from_overrides(self):
        suggester = CategorySuggester()
        suggester.build_corpus({"Walmart": "groceries"}, [])
        assert suggester.suggest("Walmart") == "groceries"

    def test_exact_match_case_insensitive(self):
        suggester = CategorySuggester()
        suggester.build_corpus({"Walmart": "groceries"}, [])
        assert suggester.suggest("walmart") == "groceries"
        assert suggester.suggest("WALMART") == "groceries"

    def test_exact_match_returns_lowercase_category(self):
        suggester = CategorySuggester()
        suggester.build_corpus({"Walmart": "Groceries"}, [])
        assert suggester.suggest("Walmart") == "groceries"

    def test_normalized_tier_catches_store_number_variant(self):
        """After commit (d), _exact_match delegates to resolve_override so Tier 1 hits here."""
        suggester = CategorySuggester()
        suggester.build_corpus({"BOOSTER JUICE #232": "Restaurant/Dining"}, [])
        assert suggester.suggest("BOOSTER JUICE #999") == "restaurant/dining"

    def test_no_match_returns_miscellaneous(self):
        suggester = CategorySuggester()
        suggester.build_corpus({"Walmart": "groceries"}, [])
        assert suggester.suggest("Unknown Store XYZ") == "miscellaneous"


class TestEmbeddingMatch:
    def _make_client(self, corpus_vectors: list[list[float]], query_vectors: list[list[float]]) -> MagicMock:
        """Create a mock client that returns pre-defined vectors."""
        client = MagicMock()
        call_count = [0]

        def mock_embed(texts: list[str]) -> list[list[float]]:
            if call_count[0] == 0:
                call_count[0] += 1
                return corpus_vectors
            return query_vectors

        client.embed.side_effect = mock_embed
        return client

    def test_high_similarity_returns_category(self):
        # Corpus: "Walmart" → groceries
        corpus_vec = _unit_vector(4, 0)
        query_vec = _similar_vector(corpus_vec, noise=0.01)  # Very similar

        client = self._make_client([corpus_vec], [query_vec])
        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        result = suggester.suggest("Wal-Mart Supercentre #123")
        assert result == "groceries"

    def test_low_similarity_returns_miscellaneous(self):
        # Corpus: "Walmart" → groceries
        corpus_vec = _unit_vector(4, 0)
        # Orthogonal vector — very different
        query_vec = _unit_vector(4, 3)

        client = self._make_client([corpus_vec], [query_vec])
        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        result = suggester.suggest("Totally Different")
        assert result == "miscellaneous"

    def test_exact_match_skips_embedding(self):
        client = MagicMock(name="client")
        # Corpus embedding call
        client.embed.return_value = [_unit_vector(4, 0)]

        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        # Reset call count after build_corpus
        client.embed.reset_mock()

        result = suggester.suggest("Walmart")
        assert result == "groceries"
        # Should NOT call embed again for exact match
        client.embed.assert_not_called()


class TestBatchSuggest:
    def test_batch_returns_correct_categories(self):
        client = MagicMock()

        # Corpus: 2 companies
        corpus_vecs = [_unit_vector(4, 0), _unit_vector(4, 1)]
        # Query: 2 descriptions — one matches corpus[0], one matches corpus[1]
        query_vecs = [_similar_vector(_unit_vector(4, 0), 0.01), _similar_vector(_unit_vector(4, 1), 0.01)]

        call_count = [0]

        def mock_embed(texts: list[str]) -> list[list[float]]:
            if call_count[0] == 0:
                call_count[0] += 1
                return corpus_vecs
            return query_vecs

        client.embed.side_effect = mock_embed

        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries", "Shell": "gasoline"}, [])

        results = suggester.suggest_batch(["Wal-Mart #123", "Shell Gas Station"])
        assert results == ["groceries", "gasoline"]

    def test_batch_exact_match_skips_embedding(self):
        client = MagicMock(name="client")
        corpus_vecs = [_unit_vector(4, 0)]
        client.embed.return_value = corpus_vecs

        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        client.embed.reset_mock()

        # Both descriptions have exact match
        results = suggester.suggest_batch(["Walmart", "walmart"])
        assert results == ["groceries", "groceries"]
        # No embedding call needed
        client.embed.assert_not_called()

    def test_batch_mixed_exact_and_embedding(self):
        client = MagicMock()

        corpus_vecs = [_unit_vector(4, 0), _unit_vector(4, 1)]
        # Only one unmatched query
        query_vecs = [_similar_vector(_unit_vector(4, 1), 0.01)]

        call_count = [0]

        def mock_embed(texts: list[str]) -> list[list[float]]:
            if call_count[0] == 0:
                call_count[0] += 1
                return corpus_vecs
            return query_vecs

        client.embed.side_effect = mock_embed

        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries", "Shell": "gasoline"}, [])

        results = suggester.suggest_batch(["Walmart", "Shell Gas Station"])
        assert results[0] == "groceries"  # exact match
        assert results[1] == "gasoline"  # embedding match

    def test_batch_unmatched_returns_miscellaneous(self):
        client = MagicMock()

        corpus_vecs = [_unit_vector(4, 0)]
        # Orthogonal query — no match
        query_vecs = [_unit_vector(4, 3)]

        call_count = [0]

        def mock_embed(texts: list[str]) -> list[list[float]]:
            if call_count[0] == 0:
                call_count[0] += 1
                return corpus_vecs
            return query_vecs

        client.embed.side_effect = mock_embed

        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        results = suggester.suggest_batch(["Unknown Store XYZ"])
        assert results == ["miscellaneous"]


class TestFailOpen:
    def test_no_client_uses_exact_match_only(self):
        suggester = CategorySuggester(openai_client=None)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        assert suggester.suggest("Walmart") == "groceries"
        assert suggester.suggest("Unknown Store") == "miscellaneous"

    def test_embed_returns_empty_falls_back(self):
        client = MagicMock()
        client.embed.return_value = []  # API failure

        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        # Corpus vectors are empty, so embedding match is disabled
        assert suggester.suggest("Wal-Mart #123") == "miscellaneous"

    def test_embed_query_returns_empty_falls_back(self):
        client = MagicMock()
        corpus_vecs = [_unit_vector(4, 0)]

        call_count = [0]

        def mock_embed(texts: list[str]) -> list[list[float]]:
            if call_count[0] == 0:
                call_count[0] += 1
                return corpus_vecs
            return []  # Query embedding fails

        client.embed.side_effect = mock_embed

        suggester = CategorySuggester(client)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        assert suggester.suggest("Wal-Mart #123") == "miscellaneous"


class TestCorpusDeduplication:
    def test_overrides_take_priority_over_db(self):
        client = MagicMock()

        # Override says "groceries", DB says "restaurant/dining"
        overrides = {"Walmart": "groceries"}
        db_items = [
            {"Company": "Walmart", "Category": "restaurant/dining"},
            {"Company": "Shell", "Category": "gasoline"},
        ]

        # Two companies in corpus (Walmart from override, Shell from DB)
        corpus_vecs = [_unit_vector(4, 0), _unit_vector(4, 1)]
        client.embed.return_value = corpus_vecs

        suggester = CategorySuggester(client)
        suggester.build_corpus(overrides, db_items)

        # Walmart should be "groceries" (from override), not "restaurant/dining"
        assert suggester._exact_match("Walmart") == "groceries"
        # Shell should come from DB
        assert len(suggester._corpus_companies) == 2

    def test_deleted_items_excluded(self):
        client = MagicMock()
        client.embed.return_value = [_unit_vector(4, 0)]

        db_items = [
            {"Company": "Shell", "Category": "gasoline", "DeletedAt": "2026-01-01T00:00:00"},
            {"Company": "Costco", "Category": "groceries"},
        ]

        suggester = CategorySuggester(client)
        suggester.build_corpus({}, db_items)

        assert len(suggester._corpus_companies) == 1
        assert suggester._corpus_companies[0] == "Costco"

    def test_ignored_items_excluded(self):
        client = MagicMock()
        client.embed.return_value = [_unit_vector(4, 0)]

        db_items = [
            {"Company": "Shell", "Category": "gasoline", "Ignored": True},
            {"Company": "Costco", "Category": "groceries"},
        ]

        suggester = CategorySuggester(client)
        suggester.build_corpus({}, db_items)

        assert len(suggester._corpus_companies) == 1
        assert suggester._corpus_companies[0] == "Costco"

    def test_miscellaneous_items_excluded(self):
        client = MagicMock()
        client.embed.return_value = [_unit_vector(4, 0)]

        db_items = [
            {"Company": "Unknown", "Category": "miscellaneous"},
            {"Company": "Costco", "Category": "groceries"},
        ]

        suggester = CategorySuggester(client)
        suggester.build_corpus({}, db_items)

        assert len(suggester._corpus_companies) == 1
        assert suggester._corpus_companies[0] == "Costco"

    def test_miscellaneous_overrides_excluded(self):
        """Overrides mapped to 'miscellaneous' must not enter the corpus.

        Otherwise the suggester would confidently echo 'miscellaneous' back to
        the picker, defeating the whole point of suggesting a real category.
        """
        client = MagicMock()
        client.embed.return_value = [_unit_vector(4, 0)]

        overrides = {
            "THRIFTMART #0410": "Miscellaneous",
            "THRIFTMART": "miscellaneous",
            "Walmart": "groceries",
        }

        suggester = CategorySuggester(client)
        suggester.build_corpus(overrides, [])

        # Only Walmart survives — both casings of "miscellaneous" overrides are skipped.
        assert suggester._corpus_companies == ["Walmart"]
        assert suggester._corpus_categories == ["groceries"]

    def test_empty_company_excluded(self):
        client = MagicMock()
        client.embed.return_value = []

        db_items = [
            {"Company": "", "Category": "groceries"},
            {"Company": None, "Category": "groceries"},
        ]

        suggester = CategorySuggester(client)
        suggester.build_corpus({}, db_items)

        assert len(suggester._corpus_companies) == 0

    def test_empty_corpus(self):
        suggester = CategorySuggester()
        suggester.build_corpus({}, [])
        assert suggester.suggest("Anything") == "miscellaneous"


class TestRawOverrideKeys:
    """Override keys are stored raw — queries should use raw descriptions to match."""

    def test_raw_billpayment_key_matches_raw_query(self):
        """'BillPayment WestlandUtilityCo' matches when queried with the same raw string."""
        suggester = CategorySuggester()
        suggester.build_corpus({"BillPayment WestlandUtilityCo": "utilities"}, [])
        assert suggester.suggest("BillPayment WestlandUtilityCo") == "utilities"

    def test_raw_monthlyfee_key_matches_raw_query(self):
        """'Monthlyfee' matches when queried with 'Monthlyfee'."""
        suggester = CategorySuggester()
        suggester.build_corpus({"Monthlyfee": "service charges/fees"}, [])
        assert suggester.suggest("Monthlyfee") == "service charges/fees"

    def test_raw_billpayment_north_mobile_matches(self):
        """'BillPayment NorthMobile' matches raw query."""
        suggester = CategorySuggester()
        suggester.build_corpus({"BillPayment NorthMobile": "communication/cell"}, [])
        assert suggester.suggest("BillPayment NorthMobile") == "communication/cell"

    def test_cleaned_query_does_not_match_raw_key(self):
        """Cleaned description should NOT match a raw override key."""
        suggester = CategorySuggester()
        suggester.build_corpus({"BillPayment WestlandUtilityCo": "utilities"}, [])
        # Cleaned form won't match raw key
        assert suggester.suggest("Westland Utility Co") == "miscellaneous"

    def test_corpus_stores_raw_keys(self):
        """Corpus company list should contain raw override keys, not cleaned."""
        suggester = CategorySuggester()
        suggester.build_corpus({"BillPayment WestlandUtilityCo": "utilities"}, [])
        assert suggester._corpus_companies == ["BillPayment WestlandUtilityCo"]


class TestCacheIntegration:
    def _make_cache(self, tmp_path: Path) -> EmbeddingCache:
        return EmbeddingCache(db_path=tmp_path / "test_embeddings.db")

    def test_first_call_embeds_and_caches(self, tmp_path: Path) -> None:
        """First build_corpus should call embed and store results in cache."""
        cache = self._make_cache(tmp_path)
        client = MagicMock(name="client")
        vecs = [_unit_vector(4, 0), _unit_vector(4, 1)]
        client.embed.return_value = vecs

        suggester = CategorySuggester(client, embedding_cache=cache)
        suggester.build_corpus({"Walmart": "groceries", "Shell": "gasoline"}, [])

        # Embed should have been called once
        client.embed.assert_called_once()
        # Vectors should be in cache
        cached = cache.get_many(["Walmart", "Shell"])
        assert "walmart" in cached
        assert "shell" in cached

    def test_second_call_uses_cache(self, tmp_path: Path) -> None:
        """Second build_corpus with same companies should not call embed."""
        cache = self._make_cache(tmp_path)
        client = MagicMock(name="client")
        vecs = [_unit_vector(4, 0), _unit_vector(4, 1)]
        client.embed.return_value = vecs

        # First call — populates cache
        s1 = CategorySuggester(client, embedding_cache=cache)
        s1.build_corpus({"Walmart": "groceries", "Shell": "gasoline"}, [])
        assert client.embed.call_count == 1

        # Second call — should use cache, no embed call
        client.embed.reset_mock()
        s2 = CategorySuggester(client, embedding_cache=cache)
        s2.build_corpus({"Walmart": "groceries", "Shell": "gasoline"}, [])
        client.embed.assert_not_called()
        # Vectors should still be populated
        assert len(s2._corpus_vectors) == 2

    def test_partial_cache_hit(self, tmp_path: Path) -> None:
        """When some texts are cached, only uncached ones are embedded."""
        cache = self._make_cache(tmp_path)
        client = MagicMock(name="client")

        # Pre-populate cache with Walmart
        cache.put_many([("Walmart", _unit_vector(4, 0))])

        # Embed call should only be for Shell
        client.embed.return_value = [_unit_vector(4, 1)]

        suggester = CategorySuggester(client, embedding_cache=cache)
        suggester.build_corpus({"Walmart": "groceries", "Shell": "gasoline"}, [])

        # Should embed only Shell
        client.embed.assert_called_once_with(["Shell"])
        assert len(suggester._corpus_vectors) == 2

    def test_cache_does_not_affect_exact_match(self, tmp_path: Path) -> None:
        """Exact match still works with cache enabled."""
        cache = self._make_cache(tmp_path)
        client = MagicMock()
        client.embed.return_value = [_unit_vector(4, 0)]

        suggester = CategorySuggester(client, embedding_cache=cache)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        assert suggester.suggest("Walmart") == "groceries"

    def test_no_cache_still_works(self):
        """Without cache, behavior is unchanged."""
        client = MagicMock(name="client")
        vecs = [_unit_vector(4, 0)]
        client.embed.return_value = vecs

        suggester = CategorySuggester(client, embedding_cache=None)
        suggester.build_corpus({"Walmart": "groceries"}, [])

        assert len(suggester._corpus_vectors) == 1
        client.embed.assert_called_once()
