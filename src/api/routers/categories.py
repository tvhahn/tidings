"""Categories endpoint."""

from fastapi import APIRouter

from src.api.dependencies import run_sync
from src.api.models import CategoriesResponse
from src.finance.config_loader import get_category_list

router = APIRouter(tags=["categories"])


@router.get(
    "/categories",
    response_model=CategoriesResponse,
    operation_id="listCategories",
    summary="List predefined categories",
)
async def list_categories():
    # Read the active list from storage (DynamoDB/SQLite), falling back to the seed
    # JSON when storage is empty — the same source `/categories/managed` uses, so the
    # whole app stays consistent. Returned raw (no title-casing): the stored strings
    # are the exact category values written onto transactions, and title-casing would
    # corrupt entries like "Hygiene/Personal care".
    categories = await run_sync(get_category_list)
    return CategoriesResponse(categories=list(categories))
