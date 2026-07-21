"""Merchant alias schemas."""

from pydantic import BaseModel

__all__ = [
    "MerchantAliasEntry",
    "MerchantAliasListResponse",
    "MerchantAliasMutationResponse",
    "MerchantAliasPutRequest",
]


class MerchantAliasEntry(BaseModel):
    raw_name: str
    canonical_name: str


class MerchantAliasListResponse(BaseModel):
    aliases: list[MerchantAliasEntry]
    count: int
    version: int


class MerchantAliasPutRequest(BaseModel):
    canonical_name: str


class MerchantAliasMutationResponse(BaseModel):
    ok: bool
