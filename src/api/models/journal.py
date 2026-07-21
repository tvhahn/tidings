"""Journal request/response schemas."""

from pydantic import BaseModel

from src.api.models.transactions import TransactionResponse

__all__ = [
    "JournalDay",
    "JournalResponse",
]


class JournalDay(BaseModel):
    date: str
    day_total: float
    count: int
    mtd_total: float
    transactions: list[TransactionResponse]


class JournalResponse(BaseModel):
    month: str
    days: list[JournalDay]
    month_total: float
    transaction_count: int
    budget_ceiling: float | None
