"""Tiered category override resolution.

Unifies exact, normalized, and alias-based override matching behind a single
`resolve_override()` call. Replaces the five separate `company.lower() ==
override.lower()` loops in the codebase (Lambda categorizer, webapp override
lookup, statement reconciler, retroactive fix script, and CategorySuggester).

Tier ordering is cheap-to-expensive; the first hit wins:

- Tier 0 (exact):      case-insensitive string equality against override keys.
- Tier 1 (normalized): merchant_normalizer regex cleanup on both sides, with
                       an ambiguity blacklist on override groups that would
                       collapse to the same key with differing categories.
- Tier 2 (alias):      same as Tier 1 but with alias substitution applied to
                       both sides. Skipped when `aliases` is falsy.
- Tier 3 (fuzzy):      embedding similarity via an optional `suggester`
                       parameter. When provided and Tiers 0/1/2 miss, the
                       resolver embeds the input, scores it against the
                       suggester's corpus, and returns the top match if the
                       cosine score clears `min_confidence` (default 0.90).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from src.finance.merchant_normalizer import normalize_merchant

if TYPE_CHECKING:
    from src.finance.category_suggest import CategorySuggester

Tier = Literal["exact", "normalized", "alias", "fuzzy"]

# Sentinel "category" pinned to every ignore-rule pattern so the override
# resolver's normalized-map unanimity check always agrees (all patterns share
# the same value). Ignore rules carry no category — only membership matters.
_IGNORE_SENTINEL = "\x00ignore"


@dataclass(frozen=True)
class ResolvedOverride:
    category: str
    tier: Tier
    matched_rule: str
    confidence: float


@dataclass(frozen=True)
class ResolvedIgnore:
    """Result of matching a company against the ignore-rule pattern set."""

    matched_rule: str
    tier: Tier


def resolve_ignore(
    company: str,
    patterns: Iterable[str],
    aliases: Mapping[str, str] | None = None,
) -> ResolvedIgnore | None:
    """Resolve whether ``company`` matches any ignore-rule pattern.

    Reuses the exact same tiered matcher as category overrides — Tier 0
    (case-insensitive exact), Tier 1 (merchant-normalized), Tier 2 (alias
    substitution when ``aliases`` is provided) — so an ignore rule fires the
    way a category rule does. Returns the matched pattern + tier, or ``None``.

    Ignore rules are a *set* of patterns with no associated category, so this
    pins every pattern to a shared sentinel value and delegates to
    ``resolve_override``: the normalized-map unanimity check then always agrees
    and only membership decides the match. The fuzzy embedding tier is
    deliberately never offered — ignoring silently drops a transaction from
    every total, so it must fire only on deterministic matches.
    """
    pattern_map = {p: _IGNORE_SENTINEL for p in patterns if p}
    if not company or not pattern_map:
        return None
    match = resolve_override(company, pattern_map, aliases=aliases)
    if match is None:
        return None
    return ResolvedIgnore(matched_rule=match.matched_rule, tier=match.tier)


def resolve_override(
    company: str,
    overrides: Mapping[str, str],
    aliases: Mapping[str, str] | None = None,
    suggester: "CategorySuggester | None" = None,
    min_confidence: float = 0.90,
) -> ResolvedOverride | None:
    """Resolve a company name to an override category via tiered matching.

    Returns the first tier that hits, or `None` if every tier misses.
    Category casing is preserved from the override value; `matched_rule`
    carries the original-case override key (Tiers 0-2) or the winning
    corpus entry (Tier 3) so downstream UI can render the exact rule that
    fired.

    Tier 3 (fuzzy): when `suggester` is provided and Tiers 0/1/2 miss, the
    resolver embeds `company`, scores it against the suggester's corpus,
    and returns the top match if the cosine score clears `min_confidence`.
    `min_confidence=0.90` is the default for automatic callers (webapp
    match endpoint, Lambda — though Lambda deliberately doesn't pass a
    suggester). Human-confirmed callers (statement reconciler) tighten
    or loosen via the suggester's own `min_confidence` instance attribute
    and pass `min_confidence=0.0` here to defer to the suggester.
    """
    if not company or not overrides:
        return None

    company_lower = company.lower()

    # Tier 0 — exact case-insensitive match
    for key, value in overrides.items():
        if key.lower() == company_lower:
            return ResolvedOverride(
                category=value,
                tier="exact",
                matched_rule=key,
                confidence=1.0,
            )

    # Tier 1 — normalized (no aliases applied)
    company_norm = normalize_merchant(company).lower()
    if company_norm:
        normalized_map = _build_normalized_map(overrides, aliases=None)
        hit = normalized_map.get(company_norm)
        if hit is not None:
            category, matched_rule = hit
            return ResolvedOverride(
                category=category,
                tier="normalized",
                matched_rule=matched_rule,
                confidence=1.0,
            )

    # Tier 2 — alias (normalization first, alias lookup second)
    if aliases:
        company_alias = normalize_merchant(company, aliases=aliases).lower()
        if company_alias:
            alias_map = _build_normalized_map(overrides, aliases=aliases)
            hit = alias_map.get(company_alias)
            if hit is not None:
                category, matched_rule = hit
                return ResolvedOverride(
                    category=category,
                    tier="alias",
                    matched_rule=matched_rule,
                    confidence=1.0,
                )

    # Tier 3 — fuzzy embedding match via optional suggester
    if suggester is not None:
        vector = suggester.embed_one(company)
        if vector:
            match = suggester.embedding_match(vector)
            if match is not None:
                category, matched_rule, score = match
                if score >= min_confidence:
                    return ResolvedOverride(
                        category=category,
                        tier="fuzzy",
                        matched_rule=matched_rule,
                        confidence=score,
                    )

    return None


def _group_overrides_by_normalized_key(
    overrides: Mapping[str, str],
    aliases: Mapping[str, str] | None,
) -> dict[str, list[tuple[str, str]]]:
    """Group overrides by their normalized (optionally alias-resolved) key."""
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, value in overrides.items():
        norm = normalize_merchant(key, aliases=aliases).lower()
        if not norm:
            continue
        groups[norm].append((key, value))
    return groups


def _build_normalized_map(
    overrides: Mapping[str, str],
    aliases: Mapping[str, str] | None,
) -> dict[str, tuple[str, str]]:
    """Group overrides by normalized key; keep groups that unanimously agree.

    Returns `{normalized_key_lower: (category, original_key)}` for groups
    where every override in the group resolves to the same category value
    (case-insensitive, whitespace-stripped). Ambiguous groups — two or more
    distinct categories under the same normalized key — are excluded entirely
    so they fall through to the next tier (or to OpenAI, in Lambda's case).

    The original-case key returned in the tuple is the first override
    encountered in the group, used as `matched_rule` for audit.
    """
    resolved: dict[str, tuple[str, str]] = {}
    for norm_key, entries in _group_overrides_by_normalized_key(overrides, aliases).items():
        distinct = {value.strip().lower() for _, value in entries}
        if len(distinct) == 1:
            first_key, first_value = entries[0]
            resolved[norm_key] = (first_value, first_key)
    return resolved


def get_blacklisted_keys(
    overrides: Mapping[str, str],
    aliases: Mapping[str, str] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Return override groups excluded from Tier 1/2 due to category conflicts.

    Keys are the lowercased normalized (or alias-resolved, when `aliases` is
    provided) form. Values are the list of `(original_key, category)` entries
    in the conflicting group.

    `resolve_override` returns `None` for both blacklisted fall-throughs and
    genuine misses; this helper lets callers (e.g. the retroactive `/fix-
    categories` dry-run) distinguish the two so the tier breakdown can show
    how many transactions were blocked by ambiguous overrides vs. having no
    override at all.

    When `aliases` is truthy, the returned map reflects the Tier-2 blacklist
    (normalization + alias substitution). When `aliases` is falsy or empty,
    it reflects the Tier-1 blacklist (normalization only). A group that
    conflicts in Tier 1 can resolve cleanly in Tier 2 (and vice versa), so
    callers that need both should invoke twice.
    """
    blacklisted: dict[str, list[tuple[str, str]]] = {}
    for norm_key, entries in _group_overrides_by_normalized_key(overrides, aliases).items():
        distinct = {value.strip().lower() for _, value in entries}
        if len(distinct) > 1:
            blacklisted[norm_key] = list(entries)
    return blacklisted
