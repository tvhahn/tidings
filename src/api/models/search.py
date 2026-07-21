"""Transaction search schemas."""

from pydantic import BaseModel, ConfigDict, Field

from src.api.models.transactions import TransactionResponse
from src.api.utils import MONTH_PATTERN

__all__ = [
    "SearchByFilterRequest",
    "SearchResponse",
    "SearchSummary",
]


class SearchSummary(BaseModel):
    total_count: int
    total_amount: float
    avg_amount: float
    by_category: dict[str, float]
    months_queried: int


class SearchByFilterRequest(BaseModel):
    """POST-body filter for cross-month transaction search.

    Sibling to ``GET /transactions/search`` — added in 2026-05 because URL-
    encoding 10+ comma-separated merchant names is awkward for agents and
    tooling. The GET stays for cacheability and existing frontend usage.

    Array fields are *any-of* matches. Empty / null arrays are treated as
    "no filter on this dimension". String exact-match fields (category,
    institution, type) are case-insensitive; ``merchant_in`` is a
    case-insensitive substring match (each entry is a substring; an item
    matches if any entry is contained in its company string).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "from_month": "2026-01",
                    "to_month": "2026-04",
                    "category_in": ["Groceries", "Restaurants"],
                    "min_amount": 10,
                    "max_amount": 500,
                },
                {
                    "from_month": "2026-04",
                    "to_month": "2026-04",
                    "merchant_in": ["whole foods", "trader joe", "costco"],
                },
            ]
        }
    )
    from_month: str = Field(pattern=MONTH_PATTERN, description="Inclusive start month, YYYY-MM.")
    to_month: str = Field(pattern=MONTH_PATTERN, description="Inclusive end month, YYYY-MM. Capped at 24 months.")
    merchant_in: list[str] | None = Field(
        default=None,
        description="Any-of substring match against Company. Each entry is a case-insensitive substring.",
    )
    category_in: list[str] | None = Field(
        default=None,
        description="Any-of exact-match (case-insensitive) against Category.",
    )
    institution_in: list[str] | None = Field(
        default=None,
        description="Any-of exact-match (case-insensitive) against Institution.",
    )
    type_in: list[str] | None = Field(
        default=None,
        description="Any-of exact-match (case-insensitive) against TransactionType.",
    )
    min_amount: float | None = Field(default=None, description="Inclusive lower bound on Amount.")
    max_amount: float | None = Field(default=None, description="Inclusive upper bound on Amount.")
    include_ignored: bool = Field(default=False, description="If true, include rows flagged Ignored.")
    include_deleted: bool = Field(default=False, description="If true, include soft-deleted rows.")


class SearchResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "transactions": [],
                    "summary": {
                        "total_count": 23,
                        "total_amount": 612.45,
                        "avg_amount": 26.63,
                        "by_category": {"groceries": 612.45},
                        "months_queried": 3,
                    },
                    "capped": False,
                    "total_matching": 23,
                }
            ]
        }
    )
    transactions: list[TransactionResponse]
    summary: SearchSummary
    capped: bool = False
    total_matching: int = 0
