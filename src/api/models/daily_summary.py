"""Pydantic models for daily summary endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from src.api.utils import MONTH_PATTERN


class DaySummaryGenerateRequest(BaseModel):
    month: str = Field(..., pattern=MONTH_PATTERN)
    dates: list[str] | None = None  # None = all missing
    force: bool = False  # True = regenerate even if summary exists


class DaySummaryStatusResponse(BaseModel):
    status: Literal["idle", "running", "error"]
    month: str | None = None
    completed: int = 0
    total: int = 0
    error: str | None = None


class DaySummariesResponse(BaseModel):
    month: str
    summaries: dict[str, str]  # date -> summary text


class DaySummaryGenerateResponse(BaseModel):
    status: Literal["running", "idle"]
    month: str
    dates_queued: int
