"""Pydantic models for insights endpoints."""

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = [
    "BriefingFigure",
    "BriefingValidation",
    "BriefingValidationSummary",
    "FixedCharge",
    "InsightsContextResponse",
    "InsightsGenerateResponse",
    "InsightsStatusResponse",
    "LargestTransaction",
    "MonthProgress",
    "PaceBlock",
    "PaceCategory",
    "PaceCeiling",
    "PaceUnbudgeted",
    "PreviousBriefing",
    "RecurringAnnualCategory",
    "SameMonthLastYear",
    "SavedInsightDetail",
    "SavedInsightItem",
    "SavedInsightListResponse",
    "SuspectedIgnored",
]


class InsightsGenerateResponse(BaseModel):
    """Response when kicking off a background insights generation job."""

    status: str = Field(..., description='Always "running" on successful start.')
    month: str


class InsightsStatusResponse(BaseModel):
    """Current state of the single-slot insights generation task.

    `status` is one of: "idle", "running", "error". Other fields are populated
    based on status — `month`/`started_at` when running, `error` when errored.
    """

    status: Literal["idle", "running", "error"]
    month: str | None = None
    started_at: str | None = None
    error: str | None = None


class CategoryDelta(BaseModel):
    """Month-over-month spend change for a single category."""

    category: str
    current: float
    previous: float
    delta_amount: float
    delta_pct: float | None = None


class CategoryAnomaly(BaseModel):
    """A quietly-detected deviation from the prior 6-month baseline.

    `annotated_amount` is the portion of the month the user has already
    explained via transaction comments; it is > 0 only when a comment partially
    (not fully) explains the deviation, so the anomaly is kept but noted.
    """

    category: str
    current: float
    baseline: float
    severity: Literal["low", "medium", "high"]
    reason: str
    annotated_amount: float = 0


class PaceCeiling(BaseModel):
    """Precomputed pace math for the annual spending ceiling."""

    annual: float
    ytd_spent: float
    prorated_to_date: float
    variance_amount: float
    variance_pct: float
    projected_naive: float
    projected_adjusted: float
    method_note: str


class PaceCategory(BaseModel):
    """Precomputed pace math for one budgeted category.

    Variable categories carry `expected_to_date`/`variance_*`; lumpy (annual)
    categories carry `pct_of_annual`/`remaining_expected` instead — the unused
    fields stay null.
    """

    category: str
    category_type: str
    annual_target: float
    monthly_target: float
    month_actual: float
    ytd_actual: float
    expected_to_date: float | None = None
    variance_amount: float | None = None
    variance_pct: float | None = None
    pct_of_annual: float | None = None
    remaining_expected: float | None = None
    assessment: str


class PaceUnbudgeted(BaseModel):
    """A spend category with no budget target, for pace completeness."""

    category: str
    ytd_actual: float
    month_actual: float


class MonthProgress(BaseModel):
    """Elapsed-days projection, present only when the target month is current."""

    days_elapsed: int
    days_in_month: int
    projected_month_end: float


class PaceBlock(BaseModel):
    """Authoritative, precomputed budget-pace math (null when no targets exist).

    The LLM must read every projection/variance from here rather than deriving
    its own — naive annualization distorts lumpy annual categories.
    """

    months_elapsed: int
    ceiling: PaceCeiling
    categories: list[PaceCategory]
    unbudgeted: list[PaceUnbudgeted]
    month_progress: MonthProgress | None = None


class LargestTransaction(BaseModel):
    """One of the month's largest live spending transactions."""

    date: str
    company: str
    amount: float
    category: str
    comment: str | None = None


class SuspectedIgnored(BaseModel):
    """A merchant active this month that resembles ones the user usually ignores."""

    company: str
    amount: float
    count: int
    historical_ignored_share: float


class SameMonthLastYear(BaseModel):
    """The target month one calendar year earlier — a seasonal comparison anchor.

    `by_category` mirrors the trimmed trend-entry shape. `comments` are LAST
    YEAR's user annotations on that month's live spending, carried forward so the
    model can cite prior-year context ("as it did last May") without the user
    re-annotating.
    """

    year_month: str
    total_spending: float
    spending_count: int
    by_category: dict[str, Any]
    comments: list[dict[str, Any]]


class RecurringAnnualCategory(BaseModel):
    """A category that historically bills around this time of year (once or twice annually)."""

    category: str
    typical_amount: float
    months_seen: list[str]
    last_seen: str


class FixedCharge(BaseModel):
    """A recurring flat merchant/category charge, stable across the 6-month baseline."""

    company: str
    category: str
    monthly_amount: float
    months_active: int


class PreviousBriefing(BaseModel):
    """The most recent saved briefing for the previous month, for continuity."""

    month: str
    generated_at: str
    excerpt: str


class InsightsContextResponse(BaseModel):
    """Raw aggregation context handed to the AI analysis.

    The nested dicts (current_month, trend entries, historical_averages, etc.)
    come directly from the spending-summary and budget services; they are not
    tightly typed here because their shape is owned by those services.
    """

    generated_at: str
    month: str
    current_month: dict[str, Any]
    previous_month: dict[str, Any] | None = None
    delta: dict[str, float]
    trend: list[dict[str, Any]]
    budget: dict[str, Any] | None = None
    pace: PaceBlock | None = None
    historical_averages: dict[str, Any]
    category_deltas: list[CategoryDelta]
    anomalies: list[CategoryAnomaly]
    largest_transactions: list[LargestTransaction] = Field(default_factory=list)
    suspected_ignored: list[SuspectedIgnored] = Field(default_factory=list)
    commented_transactions: list[dict[str, Any]]
    same_month_last_year: SameMonthLastYear | None = None
    recurring_annual: list[RecurringAnnualCategory] = Field(default_factory=list)
    fixed_charges: list[FixedCharge] = Field(default_factory=list)
    previous_briefing: PreviousBriefing | None = None
    user_memo: str | None = None


class BriefingFigure(BaseModel):
    """A single dollar amount or percentage extracted from a briefing.

    `kind` is "dollar" or "percent"; `value` is the parsed magnitude; `snippet`
    is the surrounding markdown for human-readable reporting.
    """

    raw: str
    kind: Literal["dollar", "percent"]
    value: float
    snippet: str


class BriefingValidationSummary(BaseModel):
    """Roll-up counts for a briefing's figure check."""

    total: int
    matched: int
    unmatched: int


class BriefingValidation(BaseModel):
    """Figure-check result for a saved briefing.

    Populated when a `<stem>.validation.json` sidecar exists next to the saved
    markdown. `ok` is true when every extracted figure traces back to the
    context that fed the prompt; `unmatched` lists only the figures that did not
    (with snippets), keeping the payload light.
    """

    ok: bool
    summary: BriefingValidationSummary
    unmatched: list[BriefingFigure] = Field(default_factory=list)


class SavedInsightItem(BaseModel):
    """Summary entry in the saved insights list.

    `figures_ok` is null when no validation sidecar exists (older briefings, or
    briefings saved before the figure check shipped), true/false otherwise.
    """

    id: str
    month: str
    generated_at: str
    figures_ok: bool | None = None


class SavedInsightListResponse(BaseModel):
    """Envelope for the saved-insights list — items plus a count."""

    items: list[SavedInsightItem]
    count: int


class SavedInsightDetail(BaseModel):
    """Full saved insight including the markdown briefing.

    `validation` is populated from the sidecar JSON when present, and null
    otherwise.
    """

    id: str
    month: str
    generated_at: str
    content: str
    validation: BriefingValidation | None = None
