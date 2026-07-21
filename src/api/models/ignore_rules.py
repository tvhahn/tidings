"""Merchant auto-ignore rule schemas.

Parallel to ``models/overrides.py``: an ignore rule pins a merchant pattern to
*ignored* the way an override pins a merchant to a category.
"""

from pydantic import BaseModel

__all__ = [
    "DismissedIgnoreRuleSuggestion",
    "DismissedIgnoreRuleSuggestionsResponse",
    "IgnoreRuleAddRequest",
    "IgnoreRuleApplyRequest",
    "IgnoreRuleApplyResponse",
    "IgnoreRuleApplyResult",
    "IgnoreRuleDeleteResponse",
    "IgnoreRuleEntry",
    "IgnoreRuleListResponse",
    "IgnoreRuleSuggestion",
    "IgnoreRuleSuggestionDismissRequest",
    "IgnoreRuleSuggestionDismissResponse",
    "IgnoreRuleSuggestionUndismissResponse",
    "IgnoreRuleSuggestionsResponse",
]


class IgnoreRuleEntry(BaseModel):
    pattern: str


class IgnoreRuleListResponse(BaseModel):
    rules: list[IgnoreRuleEntry]
    count: int
    version: int


class IgnoreRuleAddRequest(BaseModel):
    pattern: str


class IgnoreRuleDeleteResponse(BaseModel):
    detail: str


class IgnoreRuleApplyRequest(BaseModel):
    """Backfill Ignored on existing transactions.

    When ``pattern`` is set, only that rule is applied; when null, every rule
    is applied. Only rows currently un-ignored are changed, so a rerun is a
    no-op and the counts report exactly what moved.
    """

    pattern: str | None = None


class IgnoreRuleApplyResult(BaseModel):
    pattern: str
    matched: int
    updated: int


class IgnoreRuleApplyResponse(BaseModel):
    results: list[IgnoreRuleApplyResult]
    total_matched: int
    total_updated: int


class IgnoreRuleSuggestion(BaseModel):
    merchant: str
    total_count: int
    ignored_count: int
    share: float


class IgnoreRuleSuggestionsResponse(BaseModel):
    suggestions: list[IgnoreRuleSuggestion]
    count: int


class IgnoreRuleSuggestionDismissRequest(BaseModel):
    """Dismiss a suggested merchant so it stops being surfaced.

    The dismissal persists until reversed via the un-dismiss endpoint — unlike
    override-suggestion dismissals, an ignore suggestion never resurfaces on its
    own (there is no per-merchant "newer correction" signal to compare against).
    """

    merchant: str


class IgnoreRuleSuggestionDismissResponse(BaseModel):
    detail: str


class DismissedIgnoreRuleSuggestion(BaseModel):
    """A single dismissed suggestion, shown in the management view.

    ``merchant`` carries the original casing recorded at dismissal time;
    ``dismissed_at`` is an ISO timestamp (empty only for legacy backups that
    never stored one).
    """

    merchant: str
    dismissed_at: str


class DismissedIgnoreRuleSuggestionsResponse(BaseModel):
    dismissed: list[DismissedIgnoreRuleSuggestion]
    count: int


class IgnoreRuleSuggestionUndismissResponse(BaseModel):
    detail: str
