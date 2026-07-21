"""Merchant alias CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.activity import stage_before
from src.api.dependencies import get_merchant_alias_service, run_sync
from src.api.models import (
    MerchantAliasEntry,
    MerchantAliasListResponse,
    MerchantAliasMutationResponse,
    MerchantAliasPutRequest,
)
from src.finance.config_loader import invalidate_override_context_cache
from src.finance.protocols import IMerchantAliasService

router = APIRouter(tags=["merchant-aliases"])


@router.get(
    "/merchant-aliases",
    response_model=MerchantAliasListResponse,
    operation_id="listMerchantAliases",
    summary="List all merchant aliases (raw → canonical mappings)",
)
async def list_aliases(
    svc: IMerchantAliasService = Depends(get_merchant_alias_service),
):
    item = await run_sync(svc.get_aliases)
    if item is None:
        return MerchantAliasListResponse(aliases=[], count=0, version=0)

    data = item.get("Data", {})
    version = int(item.get("Version", 0))
    aliases = [MerchantAliasEntry(raw_name=k, canonical_name=v) for k, v in sorted(data.items())]
    return MerchantAliasListResponse(aliases=aliases, count=len(aliases), version=version)


@router.put(
    "/merchant-aliases/{raw_name}",
    response_model=MerchantAliasMutationResponse,
    operation_id="putMerchantAlias",
    summary="Create or update a merchant alias (raw → canonical)",
)
async def put_alias(
    raw_name: str,
    body: MerchantAliasPutRequest,
    request: Request,
    svc: IMerchantAliasService = Depends(get_merchant_alias_service),
):
    # Pre-mutation before-image (L5): current canonical for this raw name, or a
    # create-shaped empty before when the alias does not yet exist.
    current = await run_sync(svc.get_aliases)
    before_canonical = (current.get("Data", {}) if current else {}).get(raw_name)

    await run_sync(svc.put_alias, raw_name, body.canonical_name)

    stage_before(
        request,
        resource="merchant_alias",
        before={"raw_name": raw_name, "canonical_name": before_canonical} if before_canonical is not None else {},
        after={"raw_name": raw_name, "canonical_name": body.canonical_name},
        summary=f"set merchant alias for {raw_name}",
    )

    invalidate_override_context_cache()
    return MerchantAliasMutationResponse(ok=True)


@router.delete(
    "/merchant-aliases/{raw_name}",
    response_model=MerchantAliasMutationResponse,
    operation_id="deleteMerchantAlias",
    summary="Delete a merchant alias by raw name",
)
async def delete_alias(
    raw_name: str,
    request: Request,
    svc: IMerchantAliasService = Depends(get_merchant_alias_service),
):
    # Read the current canonical before deleting so the ledger before-image (L5)
    # can restore it on revert; a delete stages after=None with before set.
    current = await run_sync(svc.get_aliases)
    before_canonical = (current.get("Data", {}) if current else {}).get(raw_name)

    try:
        await run_sync(svc.delete_alias, raw_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Alias not found") from e

    stage_before(
        request,
        resource="merchant_alias",
        before={"raw_name": raw_name, "canonical_name": before_canonical},
        after=None,
        summary=f"removed merchant alias for {raw_name}",
    )

    invalidate_override_context_cache()
    return MerchantAliasMutationResponse(ok=True)
