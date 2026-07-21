"""Tests for SQLite embedding cache."""

import math
from pathlib import Path

from src.finance.embedding_cache import EmbeddingCache, _pack_vector, _unpack_vector


def _make_cache(tmp_path: Path) -> EmbeddingCache:
    """Create an EmbeddingCache with a temporary DB path."""
    return EmbeddingCache(db_path=tmp_path / "test_embeddings.db")


class TestConnectionSetup:
    def test_busy_timeout_set(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        conn = cache._connect()
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row[0] == 5000
        finally:
            conn.close()


class TestPackUnpack:
    def test_roundtrip(self) -> None:
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        blob = _pack_vector(vec)
        result = _unpack_vector(blob)
        assert len(result) == len(vec)
        for a, b in zip(vec, result, strict=True):
            assert abs(a - b) < 1e-6

    def test_empty_vector(self) -> None:
        vec = []
        blob = _pack_vector(vec)
        assert _unpack_vector(blob) == []

    def test_single_element(self) -> None:
        vec = [42.0]
        blob = _pack_vector(vec)
        result = _unpack_vector(blob)
        assert abs(result[0] - 42.0) < 1e-6


class TestGetMany:
    def test_empty_input(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        assert cache.get_many([]) == {}

    def test_cache_miss(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        result = cache.get_many(["nonexistent"])
        assert result == {}

    def test_cache_hit_after_put(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        vec = [0.1, 0.2, 0.3]
        cache.put_many([("Walmart", vec)])

        result = cache.get_many(["Walmart"])
        assert "walmart" in result
        for a, b in zip(result["walmart"], vec, strict=True):
            assert abs(a - b) < 1e-6

    def test_case_insensitive_lookup(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        vec = [1.0, 0.0, 0.0]
        cache.put_many([("Walmart", vec)])

        for query in ["walmart", "WALMART", "Walmart", "wAlMaRt"]:
            result = cache.get_many([query])
            assert "walmart" in result

    def test_partial_hits(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        cache.put_many([("Apple", [1.0, 0.0]), ("Google", [0.0, 1.0])])

        result = cache.get_many(["Apple", "Unknown", "Google"])
        assert "apple" in result
        assert "google" in result
        assert "unknown" not in result


class TestPutMany:
    def test_empty_input(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        cache.put_many([])  # Should not raise

    def test_duplicate_insert_ignored(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        vec1 = [1.0, 0.0]
        vec2 = [0.0, 1.0]

        cache.put_many([("Walmart", vec1)])
        cache.put_many([("Walmart", vec2)])  # Should be ignored

        result = cache.get_many(["Walmart"])
        # First vector should be preserved
        assert abs(result["walmart"][0] - 1.0) < 1e-6
        assert abs(result["walmart"][1] - 0.0) < 1e-6

    def test_batch_insert(self, tmp_path: Path) -> None:
        cache = _make_cache(tmp_path)
        entries = [
            ("Company A", [0.1, 0.2]),
            ("Company B", [0.3, 0.4]),
            ("Company C", [0.5, 0.6]),
        ]
        cache.put_many(entries)

        result = cache.get_many(["Company A", "Company B", "Company C"])
        assert len(result) == 3


class TestPersistence:
    def test_survives_new_instance(self, tmp_path: Path) -> None:
        db_path = tmp_path / "persist.db"
        cache1 = EmbeddingCache(db_path=db_path)
        cache1.put_many([("test", [1.0, 2.0, 3.0])])

        # New instance, same DB
        cache2 = EmbeddingCache(db_path=db_path)
        result = cache2.get_many(["test"])
        assert "test" in result
        assert len(result["test"]) == 3


class TestHighDimensionVectors:
    def test_1536_dim_vector(self, tmp_path: Path) -> None:
        """Test with real embedding dimension (text-embedding-3-small)."""
        cache = _make_cache(tmp_path)
        vec = [math.sin(i * 0.01) for i in range(1536)]
        cache.put_many([("test_company", vec)])

        result = cache.get_many(["test_company"])
        assert "test_company" in result
        assert len(result["test_company"]) == 1536
        for a, b in zip(result["test_company"], vec, strict=True):
            assert abs(a - b) < 1e-5
