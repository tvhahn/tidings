"""Category management schemas."""

from pydantic import BaseModel

__all__ = [
    "CategoriesManagementResponse",
    "CategoryAddRequest",
    "CategoryDeleteResponse",
    "CategoryGroupUpdateRequest",
    "CategoryGroupUpdateResponse",
    "CategoryIconsResponse",
    "CategoryRenameRequest",
    "CategoryRenameResponse",
    "CategoryUsageResponse",
    "CategoryWithGroup",
    "SetCategoryIconRequest",
]


class CategoryWithGroup(BaseModel):
    name: str
    group: str | None


class CategoriesManagementResponse(BaseModel):
    categories: list[CategoryWithGroup]
    count: int
    version: int
    groups: list[str]


class CategoryAddRequest(BaseModel):
    name: str
    group: str | None = None


class CategoryRenameRequest(BaseModel):
    new_name: str


class CategoryRenameResponse(BaseModel):
    old_name: str
    new_name: str
    transactions_updated: int
    overrides_updated: int
    budget_groups_updated: bool


class CategoryGroupUpdateRequest(BaseModel):
    group: str | None


class CategoryGroupUpdateResponse(BaseModel):
    category: str
    old_group: str | None
    new_group: str | None


class CategoryUsageResponse(BaseModel):
    category: str
    transaction_count: int
    override_count: int
    in_budget: bool
    in_group: str | None


class CategoryDeleteResponse(BaseModel):
    deleted_name: str
    transactions_reassigned: int
    reassigned_to: str | None


class CategoryIconsResponse(BaseModel):
    icons: dict[str, str]
    version: int


class SetCategoryIconRequest(BaseModel):
    icon: str
