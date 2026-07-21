"""Category override CRUD endpoints and suggestion engine."""

import logging
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.activity import stage_before
from src.api.dependencies import (
    get_embedding_cache,
    get_openai_client,
    get_override_service,
    get_transactions_db,
    run_sync,
)
from src.api.models import (
    DismissSuggestionRequest,
    OverrideConsolidateRequest,
    OverrideConsolidateResponse,
    OverrideDeleteResponse,
    OverrideDuplicateGroup,
    OverrideDuplicateMember,
    OverrideDuplicatesResponse,
    OverrideEntry,
    OverrideListResponse,
    OverrideMatchCandidate,
    OverrideMatchResponse,
    OverridePutRequest,
    OverrideSuggestion,
    OverrideSuggestionsResponse,
    SuggestionDismissResponse,
    SuggestionUndismissResponse,
)
from src.api.utils import run_with_conflict_handling
from src.finance.category_resolver import resolve_override
from src.finance.category_suggest import CategorySuggester
from src.finance.config_loader import get_override_context, invalidate_category_overrides_cache
from src.finance.demo_clock import app_today
from src.finance.embedding_cache import EmbeddingCache
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.openai_client import OpenAIClient
from src.finance.protocols import IOverrideService, ITransactionsDB

logger = logging.getLogger(__name__)

router = APIRouter(tags=["overrides"])


@router.get(
    "/overrides",
    response_model=OverrideListResponse,
    operation_id="listOverrides",
    summary="List all category override rules",
)
async def list_overrides(
    svc: IOverrideService = Depends(get_override_service),
):
    item = await run_sync(svc.get_overrides)
    if item is None:
        return OverrideListResponse(overrides=[], count=0, version=0)

    data = item.get("Data", {})
    overrides = [OverrideEntry(company=k, category=v) for k, v in sorted(data.items())]
    return OverrideListResponse(
        overrides=overrides,
        count=len(overrides),
        version=int(item.get("Version", 0)),
    )


@router.get(
    "/overrides/match",
    response_model=OverrideMatchResponse,
    operation_id="matchOverride",
    summary="Preview the tiered category resolver against current overrides + aliases",
)
async def match_override(
    company: str = Query(..., min_length=1, description="Raw company name to resolve"),
    include_history: bool = Query(
        False,
        description=(
            "When true, build the embedding corpus from the user's full "
            "transaction history in addition to overrides. Use from the "
            "CategoryPicker so prior categorizations of a merchant in months "
            "not currently cached can still surface. The settings add-rule "
            "form leaves this off — DB items add noise for consolidation UX."
        ),
    ),
    min_score: float = Query(
        0.70,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum cosine similarity for fuzzy candidates. The 0.70 default "
            "is the disclosure floor used by the settings add-rule form. The "
            "CategoryPicker passes a lower value (e.g. 0.55) — short merchant "
            "strings cluster loosely under text-embedding-3-small and a weak "
            "but-non-zero suggestion still beats scrolling the full list."
        ),
    ),
    svc: IOverrideService = Depends(get_override_service),
    openai_client: OpenAIClient | None = Depends(get_openai_client),
    embedding_cache: EmbeddingCache = Depends(get_embedding_cache),
    db: ITransactionsDB = Depends(get_transactions_db),
) -> OverrideMatchResponse:
    """Preview the tiered resolver against the current overrides + aliases.

    Read-only. Called by the add-rule form on the settings page to surface
    "closest existing rule" hints. Returns the primary resolver hit plus up
    to 5 additional fuzzy candidates with confidence ≥ 0.70 (disclosure
    threshold — below the 0.90 auto-apply gate, used for user context).
    Empty `candidates` + null fields when no tier matches.
    """
    if not company.strip():
        raise HTTPException(status_code=422, detail="company cannot be empty")

    overrides, aliases = get_override_context()
    if not overrides:
        return OverrideMatchResponse(
            category=None,
            matched_rule=None,
            confidence=None,
            tier=None,
            candidates=[],
        )

    # Build a fresh suggester per request. The embedding cache absorbs the
    # cost — corpus vectors are paid once and reused across calls.
    suggester = None
    if openai_client is not None:
        suggester = CategorySuggester(openai_client, embedding_cache=embedding_cache, min_confidence=0.70)
        db_items = await run_sync(db.scan_all_transactions) if include_history else []
        suggester.build_corpus(overrides, db_items)

    match = await run_sync(
        resolve_override,
        company,
        overrides,
        aliases=aliases,
        suggester=suggester,
        min_confidence=0.90,
    )

    # Collect up to 5 fuzzy candidates (≥ 0.70) for the disclosure list.
    candidates: list[OverrideMatchCandidate] = []
    if match is not None:
        candidates.append(
            OverrideMatchCandidate(
                category=match.category,
                matched_rule=match.matched_rule,
                confidence=match.confidence,
                tier=match.tier,
            )
        )
    if suggester is not None:
        vector = await run_sync(suggester.embed_one, company)
        if vector:
            # Exclude the primary-hit corpus entry to avoid listing it twice.
            primary_rule_lower = match.matched_rule.lower() if match is not None else None
            for category, matched_rule, score in suggester.top_candidates(vector, limit=5, min_score=min_score):
                if primary_rule_lower is not None and matched_rule.lower() == primary_rule_lower:
                    continue
                candidates.append(
                    OverrideMatchCandidate(
                        category=category,
                        matched_rule=matched_rule,
                        confidence=score,
                        tier="fuzzy",
                    )
                )
                if len(candidates) >= 5:
                    break

    if match is None:
        return OverrideMatchResponse(
            category=None,
            matched_rule=None,
            confidence=None,
            tier=None,
            candidates=candidates,
        )
    return OverrideMatchResponse(
        category=match.category,
        matched_rule=match.matched_rule,
        confidence=match.confidence,
        tier=match.tier,
        candidates=candidates,
    )


@router.get(
    "/overrides/duplicates",
    response_model=OverrideDuplicatesResponse,
    operation_id="listOverrideDuplicates",
    summary="List override groups sharing a normalized merchant key",
)
async def list_override_duplicates(
    svc: IOverrideService = Depends(get_override_service),
) -> OverrideDuplicatesResponse:
    """List override groups that share a normalized merchant key.

    Unanimous groups (every member agrees on category) are candidates for
    one-click consolidation. Ambiguous groups (two or more distinct
    categories under the same normalized key) surface as review-only — they
    fall through to OpenAI in the resolver today. Aliases are NOT applied
    here; the grouping is built purely from `merchant_normalizer`'s regex
    cleanup so consolidation semantics stay predictable even as the alias
    map evolves.
    """
    item = await run_sync(svc.get_overrides)
    if item is None:
        return OverrideDuplicatesResponse(groups=[], count=0)

    data = item.get("Data", {})
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for company, category in data.items():
        normalized = normalize_merchant(company).lower()
        if not normalized:
            continue
        groups[normalized].append((company, category))

    result: list[OverrideDuplicateGroup] = []
    for normalized_key, members in groups.items():
        if len(members) < 2:
            continue  # Singletons aren't duplicates — skip.
        distinct = {cat.strip().lower() for _, cat in members}
        unanimous = members[0][1] if len(distinct) == 1 else None
        result.append(
            OverrideDuplicateGroup(
                normalized_key=normalized_key,
                members=[OverrideDuplicateMember(company=c, category=cat) for c, cat in members],
                unanimous_category=unanimous,
            )
        )
    # Order: unanimous first (actionable), then ambiguous, then by member count desc.
    result.sort(key=lambda g: (g.unanimous_category is None, -len(g.members), g.normalized_key))
    return OverrideDuplicatesResponse(groups=result, count=len(result))


@router.post(
    "/overrides/consolidate",
    response_model=OverrideConsolidateResponse,
    operation_id="consolidateOverrides",
    summary="Atomically replace member overrides with a single canonical override",
)
async def consolidate_override_group(
    body: OverrideConsolidateRequest,
    svc: IOverrideService = Depends(get_override_service),
):
    """Atomically replace `body.members` with a single `body.canonical_company` override.

    Create + deletes run as a single unit: if the canonical key already
    exists (someone else added it) or any member was concurrently deleted,
    the whole operation fails and no partial state lands. DynamoDB uses
    `TransactWriteItems`; SQLite wraps the equivalent writes in a single
    transaction in the override service.
    """
    try:
        await run_sync(
            svc.consolidate_overrides,
            body.canonical_company,
            body.category,
            body.members,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Member not found: {e}") from e
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception("Override consolidation failed")
        raise HTTPException(status_code=500, detail="Consolidation failed") from e

    invalidate_category_overrides_cache()
    return OverrideConsolidateResponse(detail="consolidated", canonical=body.canonical_company)


@router.post(
    "/overrides/suggestions/dismissed",
    response_model=SuggestionDismissResponse,
    operation_id="dismissOverrideSuggestion",
    summary="Dismiss an override suggestion (it stops surfacing until a newer correction)",
)
async def dismiss_suggestion(
    body: DismissSuggestionRequest,
    svc: IOverrideService = Depends(get_override_service),
):
    await run_with_conflict_handling(run_sync, svc.dismiss_suggestion, body.company, body.category)
    return SuggestionDismissResponse(detail="dismissed")


@router.delete(
    "/overrides/suggestions/dismissed/{key:path}",
    response_model=SuggestionUndismissResponse,
    operation_id="undismissOverrideSuggestion",
    summary="Reverse a previous dismissal (suggestion may resurface)",
)
async def undismiss_suggestion(
    key: str,
    svc: IOverrideService = Depends(get_override_service),
):
    await run_sync(svc.undismiss_suggestion, key)
    return SuggestionUndismissResponse(detail="undismissed")


@router.put(
    "/overrides/{company:path}",
    response_model=OverrideListResponse,
    operation_id="putOverride",
    summary="Pin a company → category override",
)
async def put_override(
    company: str,
    body: OverridePutRequest,
    request: Request,
    svc: IOverrideService = Depends(get_override_service),
):
    # Pre-mutation before-image (L5): the current category for this company, or a
    # create-shaped empty before when the override does not yet exist.
    current = await run_sync(svc.get_overrides)
    before_category = (current.get("Data", {}) if current else {}).get(company)

    await run_with_conflict_handling(
        run_sync,
        svc.put_override,
        company,
        body.category,
        detail="Version conflict — overrides were modified concurrently",
    )

    stage_before(
        request,
        resource="override",
        before={"company": company, "category": before_category} if before_category is not None else {},
        after={"company": company, "category": body.category},
        summary=f"set category override for {company}",
    )

    invalidate_category_overrides_cache()

    # Return full list for convenience
    item = await run_sync(svc.get_overrides)
    # put_override just succeeded, so the item is guaranteed to exist.
    assert item is not None  # noqa: S101 — type-narrowing; None case handled above
    data = item.get("Data", {})
    overrides = [OverrideEntry(company=k, category=v) for k, v in sorted(data.items())]
    return OverrideListResponse(
        overrides=overrides,
        count=len(overrides),
        version=int(item.get("Version", 0)),
    )


@router.delete(
    "/overrides/{company:path}",
    response_model=OverrideDeleteResponse,
    operation_id="deleteOverride",
    summary="Remove a company → category override",
)
async def delete_override(
    company: str,
    request: Request,
    svc: IOverrideService = Depends(get_override_service),
):
    # Read the current category before deleting so the ledger before-image (L5)
    # can restore it on revert; a delete stages after=None with before set.
    current = await run_sync(svc.get_overrides)
    before_category = (current.get("Data", {}) if current else {}).get(company)

    try:
        await run_with_conflict_handling(
            run_sync,
            svc.delete_override,
            company,
            detail="Version conflict — overrides were modified concurrently",
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"No override found for '{company}'") from e

    stage_before(
        request,
        resource="override",
        before={"company": company, "category": before_category},
        after=None,
        summary=f"removed category override for {company}",
    )

    invalidate_category_overrides_cache()
    return OverrideDeleteResponse(ok=True)


def _query_correction_items(months: int) -> list[Mapping[str, Any]]:
    """Query the last ``months`` months, keeping only rows with a CategoryAudit.

    Runs synchronously in the thread pool (dispatched via a single ``run_sync``)
    so the sequential per-month ``query_month`` calls never block the event
    loop. Uses the spending summary so it works for both DynamoDB and SQLite.
    """
    # Local import mirrors the original call site — avoids a module-load cycle
    # between routers and dependencies.
    from src.api.dependencies import get_spending_summary

    today = app_today()
    summary = get_spending_summary()
    items: list[Mapping[str, Any]] = []
    for i in range(months):
        d = today - relativedelta(months=i)
        ym = d.strftime("%Y-%m")
        month_items = summary.query_month(ym)
        items.extend([item for item in month_items if item.get("CategoryAudit")])
    return items


@router.get(
    "/overrides/suggestions",
    response_model=OverrideSuggestionsResponse,
    operation_id="getOverrideSuggestions",
    summary="Suggest new override rules from manual category corrections",
)
async def get_suggestions(
    months: int = Query(12, ge=1, le=24),
    svc: IOverrideService = Depends(get_override_service),
):
    """Analyze manual category corrections to suggest new override rules.

    Algorithm: find companies with 1+ manual corrections to the same target
    category that don't already have an override.
    """
    # Get existing overrides
    override_item = await run_sync(svc.get_overrides)
    existing = {}
    dismissed = {}
    if override_item:
        existing = {k.lower(): v for k, v in override_item.get("Data", {}).items()}
        dismissed = dict(override_item.get("Dismissed", {}))

    # Query recent transactions across all partitions off the event loop.
    try:
        items = await run_sync(_query_correction_items, months)
    except Exception:
        logger.exception("Failed to query transactions for suggestions")
        return OverrideSuggestionsResponse(suggestions=[], count=0)

    # Group manual corrections by company
    corrections: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        audit = item.get("CategoryAudit", {})
        if audit.get("source") != "manual":
            continue
        company = (item.get("Company") or "").strip()
        category = (item.get("Category") or "").strip()
        if not company or not category:
            continue
        corrections[company.lower()][category.lower()].append(audit.get("reviewed_at", ""))

    suggestions = []
    for company_lower, cat_map in corrections.items():
        # Skip companies that already have an override
        if company_lower in existing:
            continue

        # Find the most-corrected-to category
        best_cat = max(cat_map, key=lambda c: len(cat_map[c]))
        count = len(cat_map[best_cat])

        if count < 1:
            continue

        # Find the original company name (preserve case from first item)
        original_name = company_lower
        for item in items:
            if (item.get("Company") or "").strip().lower() == company_lower:
                original_name = item["Company"].strip()
                break

        last_corrected = ""
        timestamps = cat_map[best_cat]
        if timestamps:
            last_corrected = max(t for t in timestamps if t) if any(timestamps) else ""

        # Filter dismissed suggestions (timestamp-aware resurfacing)
        dismiss_key = f"{company_lower}|{best_cat}"
        if dismiss_key in dismissed:
            dismissed_at = dismissed[dismiss_key]
            # Resurface if a newer correction happened after dismissal
            if last_corrected and last_corrected > dismissed_at:
                pass  # Newer correction — show the suggestion
            else:
                continue  # Still dismissed

        suggestions.append(
            OverrideSuggestion(
                company=original_name,
                suggested_category=best_cat.title(),
                correction_count=count,
                last_corrected=last_corrected,
            )
        )

    suggestions.sort(key=lambda s: s.correction_count, reverse=True)
    return OverrideSuggestionsResponse(suggestions=suggestions, count=len(suggestions))
