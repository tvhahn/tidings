"""Category override schemas."""

from typing import Literal

from pydantic import BaseModel

__all__ = [
    "DismissSuggestionRequest",
    "OverrideConsolidateRequest",
    "OverrideConsolidateResponse",
    "OverrideDeleteResponse",
    "OverrideDuplicateGroup",
    "OverrideDuplicateMember",
    "OverrideDuplicatesResponse",
    "OverrideEntry",
    "OverrideListResponse",
    "OverrideMatchCandidate",
    "OverrideMatchResponse",
    "OverridePutRequest",
    "OverrideSuggestion",
    "OverrideSuggestionsResponse",
    "SuggestionDismissResponse",
    "SuggestionUndismissResponse",
]


class OverrideEntry(BaseModel):
    company: str
    category: str


class OverrideListResponse(BaseModel):
    overrides: list[OverrideEntry]
    count: int
    version: int


class OverridePutRequest(BaseModel):
    category: str


class OverrideSuggestion(BaseModel):
    company: str
    suggested_category: str
    correction_count: int
    last_corrected: str


class OverrideSuggestionsResponse(BaseModel):
    suggestions: list[OverrideSuggestion]
    count: int


class DismissSuggestionRequest(BaseModel):
    company: str
    category: str


class OverrideMatchCandidate(BaseModel):
    category: str
    matched_rule: str
    confidence: float
    tier: Literal["exact", "normalized", "alias", "fuzzy"]


class OverrideMatchResponse(BaseModel):
    """Phase 2: preview endpoint response for the add-rule hint widget.

    `tier`/`category`/`matched_rule`/`confidence` mirror the top candidate;
    `candidates` is the full sorted list (≥ 0.70 disclosure threshold,
    capped at 5). When no tier matches, every field is null and
    `candidates` is `[]`.
    """

    category: str | None
    matched_rule: str | None
    confidence: float | None
    tier: Literal["exact", "normalized", "alias", "fuzzy"] | None
    candidates: list[OverrideMatchCandidate]


class OverrideDuplicateMember(BaseModel):
    company: str
    category: str


class OverrideDuplicateGroup(BaseModel):
    """Phase 4: overrides that share a normalized key.

    `unanimous_category` is non-null when every member agrees on category
    (case-insensitive) — this group can be consolidated with one click.
    Null means the group is blacklisted from Tier 1 matching and needs
    user review before consolidation.
    """

    normalized_key: str
    members: list[OverrideDuplicateMember]
    unanimous_category: str | None


class OverrideDuplicatesResponse(BaseModel):
    groups: list[OverrideDuplicateGroup]
    count: int


class OverrideConsolidateRequest(BaseModel):
    """Collapse the listed member companies into a single consolidated override.

    Atomic: either the consolidated override is created and every member
    deleted, or nothing changes. Members are matched case-insensitively
    against the current overrides map.
    """

    normalized_key: str
    canonical_company: str
    category: str
    members: list[str]


class OverrideConsolidateResponse(BaseModel):
    detail: str
    canonical: str


class OverrideDeleteResponse(BaseModel):
    ok: bool = True


class SuggestionDismissResponse(BaseModel):
    detail: str


class SuggestionUndismissResponse(BaseModel):
    detail: str
