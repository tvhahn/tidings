"""Merchant auto-ignore rule CRUD, history backfill, and suggestion engine.

Parallel to ``routers/overrides.py``: where an override pins a merchant to a
category at ingestion, an ignore rule pins a matching merchant to *ignored* at
write time (see ``TransactionsDBBase._resolve_ignored``). This router manages
the rule set, backfills existing rows, and suggests rules from merchants the
user habitually ignores by hand.
"""

import logging
from collections import defaultdict
from typing import Any

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import (
    ensure_not_demo,
    get_ignore_rule_service,
    get_transactions_db,
    run_sync,
)
from src.api.models import (
    DismissedIgnoreRuleSuggestion,
    DismissedIgnoreRuleSuggestionsResponse,
    IgnoreRuleAddRequest,
    IgnoreRuleApplyRequest,
    IgnoreRuleApplyResponse,
    IgnoreRuleApplyResult,
    IgnoreRuleDeleteResponse,
    IgnoreRuleEntry,
    IgnoreRuleListResponse,
    IgnoreRuleSuggestion,
    IgnoreRuleSuggestionDismissRequest,
    IgnoreRuleSuggestionDismissResponse,
    IgnoreRuleSuggestionsResponse,
    IgnoreRuleSuggestionUndismissResponse,
)
from src.api.utils import run_with_conflict_handling
from src.finance.category_resolver import resolve_ignore
from src.finance.config_loader import get_ignore_context, invalidate_ignore_rules_cache
from src.finance.demo_clock import app_today
from src.finance.protocols import IIgnoreRuleService, ITransactionsDB, TransactionItem

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ignore-rules"])

_DEMO_DETAIL = "Auto-ignore rules cannot be changed in demo mode"


def _list_response(item: dict[str, Any] | None) -> IgnoreRuleListResponse:
    if item is None:
        return IgnoreRuleListResponse(rules=[], count=0, version=0)
    data = item.get("Data", {})
    rules = [IgnoreRuleEntry(pattern=p) for p in sorted(data.keys())]
    return IgnoreRuleListResponse(rules=rules, count=len(rules), version=int(item.get("Version", 0)))


@router.get(
    "/ignore-rules",
    response_model=IgnoreRuleListResponse,
    operation_id="listIgnoreRules",
    summary="List all merchant auto-ignore rules",
)
async def list_ignore_rules(
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
) -> IgnoreRuleListResponse:
    item = await run_sync(svc.get_rules)
    return _list_response(item)


@router.post(
    "/ignore-rules/apply",
    response_model=IgnoreRuleApplyResponse,
    operation_id="applyIgnoreRules",
    summary="Backfill Ignored on existing transactions matching a rule (or all rules)",
)
async def apply_ignore_rules(
    body: IgnoreRuleApplyRequest,
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
    db: ITransactionsDB = Depends(get_transactions_db),
) -> IgnoreRuleApplyResponse:
    """Set Ignored on existing non-deleted transactions matching the rule(s).

    Only rows currently un-ignored are changed — there is no stored "user
    un-ignored this" signal, so the safe move is to never re-ignore a row the
    user may have deliberately restored. ``matched`` counts every non-deleted
    row the rule fires on; ``updated`` counts only the rows this call flipped.
    """
    ensure_not_demo(_DEMO_DETAIL)

    patterns = await run_sync(svc.get_patterns)
    if body.pattern is not None:
        target = [p for p in patterns if p.lower() == body.pattern.strip().lower()]
        if not target:
            raise HTTPException(status_code=404, detail=f"No ignore rule found for '{body.pattern}'")
        patterns = target

    if not patterns:
        return IgnoreRuleApplyResponse(results=[], total_matched=0, total_updated=0)

    _, aliases = get_ignore_context()
    matched, updated = await run_sync(_apply_rules_sync, patterns, aliases, db)

    results = [IgnoreRuleApplyResult(pattern=p, matched=matched.get(p, 0), updated=updated.get(p, 0)) for p in patterns]
    return IgnoreRuleApplyResponse(
        results=results,
        total_matched=sum(matched.values()),
        total_updated=sum(updated.values()),
    )


def _apply_rules_sync(
    patterns: list[str],
    aliases: dict[str, str],
    db: ITransactionsDB,
) -> tuple[dict[str, int], dict[str, int]]:
    """Scan full history, ignore matching non-deleted rows, return per-rule counts.

    Runs in the thread pool (one ``run_sync`` dispatch) so the sequential
    per-row work never blocks the event loop. Each matched row is attributed to
    the single rule the tiered resolver reports, so counts never double-count a
    row covered by two patterns.
    """
    matched: dict[str, int] = defaultdict(int)
    updated: dict[str, int] = defaultdict(int)
    for item in db.scan_all_transactions():
        if item.get("DeletedAt"):
            continue
        company = item.get("Company")
        if not company:
            continue
        hit = resolve_ignore(company, patterns, aliases=aliases)
        if hit is None:
            continue
        matched[hit.matched_rule] += 1
        if not item.get("Ignored"):
            db.set_ignored(item["ForwardedTo"], item["DateFileName"], True)
            updated[hit.matched_rule] += 1
    return dict(matched), dict(updated)


def _query_recent_transactions(months: int) -> list[TransactionItem]:
    """Return non-deleted-eligible transactions across the last ``months`` months.

    Uses the spending summary's ``query_month`` so it works for both DynamoDB
    and SQLite; dispatched via a single ``run_sync`` by the caller.
    """
    from src.api.dependencies import get_spending_summary

    today = app_today()
    summary = get_spending_summary()
    items: list[TransactionItem] = []
    for i in range(months):
        ym = (today - relativedelta(months=i)).strftime("%Y-%m")
        items.extend(summary.query_month(ym))
    return items


@router.get(
    "/ignore-rules/suggestions",
    response_model=IgnoreRuleSuggestionsResponse,
    operation_id="getIgnoreRuleSuggestions",
    summary="Suggest ignore rules from merchants you habitually ignore by hand",
)
async def get_ignore_suggestions(
    months: int = 12,
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
) -> IgnoreRuleSuggestionsResponse:
    """Surface merchants with ≥3 recent transactions where ≥60% are ignored.

    Merchants already covered by a rule (via the tiered resolver) are excluded,
    so the list only offers rules that would actually change behavior. Merchants
    the user has dismissed (case-insensitive) are excluded too — a dismissal
    persists until reversed via the un-dismiss endpoint.
    """
    patterns = await run_sync(svc.get_patterns)
    dismissed = await run_sync(svc.get_dismissed)
    _, aliases = get_ignore_context()

    try:
        items = await run_sync(_query_recent_transactions, months)
    except Exception:
        logger.exception("Failed to query transactions for ignore-rule suggestions")
        return IgnoreRuleSuggestionsResponse(suggestions=[], count=0)

    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "ignored": 0, "name": None})
    for item in items:
        if item.get("DeletedAt"):
            continue
        company = (item.get("Company") or "").strip()
        if not company:
            continue
        entry = stats[company.lower()]
        if entry["name"] is None:
            entry["name"] = company
        entry["total"] += 1
        if item.get("Ignored"):
            entry["ignored"] += 1

    suggestions: list[IgnoreRuleSuggestion] = []
    for entry in stats.values():
        total = entry["total"]
        ignored = entry["ignored"]
        if total < 3:
            continue
        share = ignored / total
        if share < 0.60:
            continue
        merchant = entry["name"]
        # Skip merchants the user has dismissed (case-insensitive).
        if merchant.lower() in dismissed:
            continue
        # Skip merchants an existing rule already covers.
        if patterns and resolve_ignore(merchant, patterns, aliases=aliases) is not None:
            continue
        suggestions.append(
            IgnoreRuleSuggestion(
                merchant=merchant,
                total_count=total,
                ignored_count=ignored,
                share=round(share, 3),
            )
        )

    suggestions.sort(key=lambda s: (s.ignored_count, s.share), reverse=True)
    return IgnoreRuleSuggestionsResponse(suggestions=suggestions, count=len(suggestions))


@router.post(
    "/ignore-rules",
    response_model=IgnoreRuleListResponse,
    operation_id="addIgnoreRule",
    summary="Add a merchant auto-ignore rule",
)
async def add_ignore_rule(
    body: IgnoreRuleAddRequest,
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
) -> IgnoreRuleListResponse:
    ensure_not_demo(_DEMO_DETAIL)

    pattern = body.pattern.strip()
    if not pattern:
        raise HTTPException(status_code=422, detail="pattern cannot be empty")

    await run_with_conflict_handling(
        run_sync,
        svc.add_rule,
        pattern,
        detail="Version conflict — ignore rules were modified concurrently",
    )
    invalidate_ignore_rules_cache()

    item = await run_sync(svc.get_rules)
    return _list_response(item)


@router.get(
    "/ignore-rules/suggestions/dismissed",
    response_model=DismissedIgnoreRuleSuggestionsResponse,
    operation_id="listDismissedIgnoreRuleSuggestions",
    summary="List dismissed ignore-rule suggestions, newest first",
)
async def list_dismissed_ignore_suggestions(
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
) -> DismissedIgnoreRuleSuggestionsResponse:
    """Return every dismissed suggestion so the user can review or restore them.

    The service normalizes the stored value shape (including legacy bare-string
    dismissals) and sorts newest-first; this handler just wraps the rows.
    """
    entries = await run_sync(svc.list_dismissed)
    dismissed = [DismissedIgnoreRuleSuggestion(**e) for e in entries]
    return DismissedIgnoreRuleSuggestionsResponse(dismissed=dismissed, count=len(dismissed))


@router.post(
    "/ignore-rules/suggestions/dismissed",
    response_model=IgnoreRuleSuggestionDismissResponse,
    operation_id="dismissIgnoreRuleSuggestion",
    summary="Dismiss a suggested merchant so it stops being surfaced",
)
async def dismiss_ignore_suggestion(
    body: IgnoreRuleSuggestionDismissRequest,
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
) -> IgnoreRuleSuggestionDismissResponse:
    ensure_not_demo(_DEMO_DETAIL)

    merchant = body.merchant.strip()
    if not merchant:
        raise HTTPException(status_code=422, detail="merchant cannot be empty")

    await run_with_conflict_handling(
        run_sync,
        svc.dismiss_suggestion,
        merchant,
        detail="Version conflict — ignore rules were modified concurrently",
    )
    return IgnoreRuleSuggestionDismissResponse(detail="dismissed")


@router.delete(
    "/ignore-rules/suggestions/dismissed/{merchant:path}",
    response_model=IgnoreRuleSuggestionUndismissResponse,
    operation_id="undismissIgnoreRuleSuggestion",
    summary="Reverse a suggestion dismissal so the merchant may resurface",
)
async def undismiss_ignore_suggestion(
    merchant: str,
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
) -> IgnoreRuleSuggestionUndismissResponse:
    ensure_not_demo(_DEMO_DETAIL)

    await run_with_conflict_handling(
        run_sync,
        svc.undismiss_suggestion,
        merchant,
        detail="Version conflict — ignore rules were modified concurrently",
    )
    return IgnoreRuleSuggestionUndismissResponse(detail="undismissed")


@router.delete(
    "/ignore-rules/{pattern:path}",
    response_model=IgnoreRuleDeleteResponse,
    operation_id="deleteIgnoreRule",
    summary="Remove a merchant auto-ignore rule",
)
async def delete_ignore_rule(
    pattern: str,
    svc: IIgnoreRuleService = Depends(get_ignore_rule_service),
) -> IgnoreRuleDeleteResponse:
    ensure_not_demo(_DEMO_DETAIL)

    try:
        await run_with_conflict_handling(
            run_sync,
            svc.delete_rule,
            pattern,
            detail="Version conflict — ignore rules were modified concurrently",
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"No ignore rule found for '{pattern}'") from e

    invalidate_ignore_rules_cache()
    return IgnoreRuleDeleteResponse(detail="deleted")
