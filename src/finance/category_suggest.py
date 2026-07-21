"""Embedding-based category suggestion for statement import.

Tier 1: Exact case-insensitive match against overrides (zero cost).
Tier 2: Cosine similarity against a cached corpus of company→category pairs.
Fallback: "miscellaneous".
"""

import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any

from src.finance.category_resolver import resolve_override
from src.finance.embedding_cache import EmbeddingCache
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

# Default minimum cosine similarity for an embedding match. Human-confirmed callers
# (statement reconciler) accept this default; automatic callers (resolve_override's
# Tier 3) tighten to 0.90 via the constructor's `min_confidence` parameter.
_DEFAULT_SIMILARITY_THRESHOLD = 0.85


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity via dot product. OpenAI embeddings are already L2-normalized,
    so dot product equals cosine similarity. We compute the full formula as a safety net."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class CategorySuggester:
    """Suggests categories for statement descriptions using embeddings."""

    def __init__(
        self,
        openai_client: OpenAIClient | None = None,
        embedding_cache: EmbeddingCache | None = None,
        min_confidence: float = _DEFAULT_SIMILARITY_THRESHOLD,
    ):
        self._client = openai_client
        self._cache = embedding_cache
        self._min_confidence = min_confidence
        self._corpus_companies: list[str] = []
        self._corpus_categories: list[str] = []
        self._corpus_vectors: list[list[float]] = []
        self._overrides: dict[str, str] = {}

    def build_corpus(self, overrides: dict[str, str], db_items: Sequence[Mapping[str, Any]]) -> None:
        """Build the embedding corpus from overrides + DB transaction history.

        Each override key contributes up to TWO corpus entries: the raw-case key
        and its `normalize_merchant()` form (when different). This lets novel
        phrasing like `COFFEE SPOT IN NEW MALL` cosine-match a corpus vector seeded by
        a short override key like `COFFEE SPOT` at high similarity. Deduplication is
        by lowercase, so overrides whose raw key already equals the normalized
        form contribute only one vector.

        Priority: overrides win over DB. DB items that are deleted, ignored, or
        categorized as "miscellaneous" are excluded. When an embedding_cache is
        available, cached vectors are reused and only uncached texts hit the API.
        """
        self._overrides = overrides

        # Collect (company, category) pairs — overrides first, with normalized variants
        seen_lower: set[str] = set()
        pairs: list[tuple[str, str]] = []

        for company, category in overrides.items():
            cat_lower = category.lower()
            # Skip overrides mapped to "miscellaneous" — that's the "I don't know"
            # bucket users are trying to escape. Including them in the corpus
            # makes the suggester confidently echo "miscellaneous" back, which
            # is never useful in either the picker or the add-rule form.
            if cat_lower == "miscellaneous":
                continue
            key = company.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                pairs.append((company, cat_lower))
            # Also seed the normalized variant so novel phrasing hits the same cluster.
            normalized = normalize_merchant(company)
            norm_key = normalized.lower()
            if norm_key and norm_key != key and norm_key not in seen_lower:
                seen_lower.add(norm_key)
                pairs.append((normalized, cat_lower))

        # Add DB history (unique companies only, skip miscellaneous/deleted/ignored)
        for item in db_items:
            if item.get("DeletedAt"):
                continue
            if item.get("Ignored"):
                continue
            company = item.get("Company") or ""
            category = (item.get("Category") or "").lower()
            if not company or category == "miscellaneous":
                continue
            key = company.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                pairs.append((company, category))

        if not pairs:
            return

        self._corpus_companies = [p[0] for p in pairs]
        self._corpus_categories = [p[1] for p in pairs]

        # Embed corpus company names (with cache support)
        if self._client:
            self._corpus_vectors = self._embed_with_cache(self._corpus_companies)

    def _embed_with_cache(self, texts: list[str]) -> list[list[float]]:
        """Embed texts, using cache for previously seen values.

        Returns a list of vectors aligned with the input texts.
        Returns an empty list on failure.
        """
        if not self._client:
            return []

        # Without cache, embed everything directly
        if not self._cache:
            vectors = self._client.embed(texts)
            if vectors and len(vectors) == len(texts):
                return vectors
            logger.warning("Corpus embedding failed or returned wrong count; embedding disabled")
            return []

        # Check cache for existing embeddings
        cached = self._cache.get_many(texts)

        # Identify uncached texts
        uncached: list[tuple[int, str]] = []
        for i, text in enumerate(texts):
            if text.lower() not in cached:
                uncached.append((i, text))

        # Embed uncached texts
        fresh_vectors: dict[str, list[float]] = {}
        if uncached:
            uncached_texts = [t for _, t in uncached]
            vectors = self._client.embed(uncached_texts)
            if vectors and len(vectors) == len(uncached_texts):
                to_cache: list[tuple[str, list[float]]] = []
                for j, (_, text) in enumerate(uncached):
                    fresh_vectors[text.lower()] = vectors[j]
                    to_cache.append((text, vectors[j]))
                self._cache.put_many(to_cache)
            else:
                logger.warning("Corpus embedding failed for %d uncached texts", len(uncached_texts))

        # Assemble full vector list in order
        result: list[list[float]] = []
        for text in texts:
            key = text.lower()
            vec = cached.get(key) or fresh_vectors.get(key)
            if vec is None:
                # Missing vector — can't build complete corpus
                logger.warning("Missing embedding for %r; embedding disabled", text)
                return []
            result.append(vec)

        return result

    def _exact_match(self, description: str) -> str | None:
        """Resolve against overrides via the tiered resolver (Tier 0/1).

        The suggester's own Tier 3 (embedding) path is the fallback after this.
        Aliases aren't threaded in here yet — that lives on the caller side.
        """
        match = resolve_override(description, self._overrides, aliases=None)
        return match.category.lower() if match else None

    def embedding_match(self, vector: list[float]) -> tuple[str, str, float] | None:
        """Find best corpus match by cosine similarity.

        Returns `(category, matched_company, score)` when the best score clears
        `self._min_confidence`, else None. `matched_company` is the original-case
        corpus entry that won — used as `matched_rule` for Tier 3 audit rows and
        for the `/api/overrides/match` `candidates` payload.
        """
        if not self._corpus_vectors or not vector:
            return None

        best_score = -1.0
        best_idx = -1
        for i, corpus_vec in enumerate(self._corpus_vectors):
            score = _cosine_similarity(vector, corpus_vec)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score >= self._min_confidence:
            return (self._corpus_categories[best_idx], self._corpus_companies[best_idx], best_score)
        return None

    def top_candidates(
        self,
        vector: list[float],
        limit: int = 5,
        min_score: float = 0.70,
    ) -> list[tuple[str, str, float]]:
        """Return the top-N corpus matches above `min_score`, ordered by score desc.

        Used by the `/api/overrides/match` endpoint to render disclosure candidates
        below the primary hit. Entries are `(category, matched_company, score)`.
        """
        if not self._corpus_vectors or not vector:
            return []

        scored: list[tuple[str, str, float]] = []
        for i, corpus_vec in enumerate(self._corpus_vectors):
            score = _cosine_similarity(vector, corpus_vec)
            if score >= min_score:
                scored.append((self._corpus_categories[i], self._corpus_companies[i], score))
        scored.sort(key=lambda t: t[2], reverse=True)
        return scored[:limit]

    def embed_one(self, text: str) -> list[float] | None:
        """Embed a single text through the cache. Returns None if no client is configured."""
        if not self._client:
            return None
        vectors = self._embed_with_cache([text])
        return vectors[0] if vectors else None

    def suggest(self, description: str) -> str:
        """Suggest a category for a single description.

        Tier 1: exact override match.
        Tier 2: embedding similarity.
        Fallback: "miscellaneous".
        """
        # Tier 1: exact match
        exact = self._exact_match(description)
        if exact:
            return exact

        # Tier 2: embedding match
        if self._client and self._corpus_vectors:
            vectors = self._client.embed([description])
            if vectors:
                result = self.embedding_match(vectors[0])
                if result:
                    category, matched_company, score = result
                    logger.debug(
                        "Embedding match: %r → %s via %r (score=%.3f)",
                        description,
                        category,
                        matched_company,
                        score,
                    )
                    return category

        return "miscellaneous"

    def suggest_batch(self, descriptions: list[str]) -> list[str]:
        """Suggest categories for multiple descriptions in one batch.

        Exact matches are resolved first; only unmatched descriptions are embedded.
        """
        results = [""] * len(descriptions)
        to_embed: list[tuple[int, str]] = []

        # Tier 1: exact matches
        for i, desc in enumerate(descriptions):
            exact = self._exact_match(desc)
            if exact:
                results[i] = exact
            else:
                to_embed.append((i, desc))

        # Tier 2: batch embedding for unmatched
        if to_embed and self._client and self._corpus_vectors:
            texts = [desc for _, desc in to_embed]
            vectors = self._client.embed(texts)
            if vectors and len(vectors) == len(texts):
                for j, (orig_idx, desc) in enumerate(to_embed):
                    match = self.embedding_match(vectors[j])
                    if match:
                        category, matched_company, score = match
                        logger.debug(
                            "Batch embedding match: %r → %s via %r (score=%.3f)",
                            desc,
                            category,
                            matched_company,
                            score,
                        )
                        results[orig_idx] = category

        # Fill remaining with miscellaneous
        for i in range(len(results)):
            if not results[i]:
                results[i] = "miscellaneous"

        return results
