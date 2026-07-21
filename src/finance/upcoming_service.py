"""Expected-upcoming-charge derivation for the commitment-aware projection.

Pure derivation over existing rows — zero new storage, no migration, dual-backend
safe. For each recurring merchant found in ``13 complete months + the current
month`` of raw ``query_month`` rows (the ``tax_pack_service`` fan-out pattern,
NOT month-level ``by_company`` aggregates — charge dates are gone at that
altitude), it derives a profile (cadence, median charge day, amount estimate,
observation channel, modal category, confidence) and then, for the current
month, runs the four-state status machine (L4):

- ``upcoming``   — expected day is still ahead of today.
- ``arrived``    — a current-month row (or the previous month's last few days,
  for day-of-month ≤ 3 merchants) matched on merchant + amount tolerance.
- ``assumed``    — expected day has passed, the merchant is observed via
  statements, and the statement has not been imported yet. Counts in the
  projection, never alarming.
- ``unrecorded`` — expected day + grace has passed for an email-observed
  merchant. The calm quiet-note case (failed payment / template drift); it
  counts in NO committed term because it may never arrive.

Channel discriminator is ``"_stmt_" in DateFileName`` — statement-*created*
rows carry it; statement *enrichment* stamps ``StatementSource`` onto ordinary
email rows, which stay email-observed. All statuses are derived at query time
and never stored: importing a statement creates the row, and the next query's
matcher flips ``assumed`` → ``arrived`` on its own.

Fail-open by design: the API pace block wraps this service and degrades to the
curve-only pace on any error.
"""

from __future__ import annotations

import calendar
import logging
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta

from src.finance.forecast_service import forecast_today
from src.finance.merchant_intelligence import RECURRING_CV_MAX, is_recognizable_merchant
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.spending_aggregator import SPENDING_TYPES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from src.finance.protocols import IMerchantAliasService, ISpendingSummary

logger = logging.getLogger(__name__)

# --- Window (L1) ------------------------------------------------------------
_WINDOW_COMPLETE_MONTHS = 13  # locked: complete months of history before the current month
_MONTH_QUERY_WORKERS = 6  # tunable: query fan-out cap (matches tax_pack_service)
_CACHE_TTL_SECONDS = 3600  # locked: 1-hour cache, mirrors ForecastService

# --- Recurring classification (L3) ------------------------------------------
_FIXED_MIN_CONSECUTIVE = 3  # locked: ≥3 consecutive recent complete months → monthly-fixed
#   RECURRING_CV_MAX (imported): the fixed-vs-variable amount-stability ceiling.
_VARIABLE_MIN_MONTHS = 4  # locked: ≥4 of the trailing 6 complete months → monthly-variable
_VARIABLE_WINDOW = 6  # locked
_ANNUAL_MIN_SPACING = 11  # locked: 11-13 months between charges → annual cadence
_ANNUAL_MAX_SPACING = 13  # locked
_CHANNEL_RECENT_CHARGES = 6  # tunable: channel = majority of the last 6 charges
# Bill-cadence guard (added 2026-07-17 after real-data validation): bills charge
# ~once a month. A monthly profile is penciled only when its mean charges-per-
# active-month over the trailing 6 complete months is <= this. Multi-visit
# everyday merchants (groceries: Wal-Mart 3-8 charges/mo, Northwind Foods 6-13/mo) exceed
# it and are neither penciled nor removed from the discretionary curve.
BILL_CADENCE_MAX_PER_MONTH = 1.5  # locked

# --- Status matching (L4) ---------------------------------------------------
AMOUNT_TOL_ABS = 2.00  # locked: |amount - estimate| tolerance floor ($2.00)
AMOUNT_TOL_PCT = 0.10  # locked: …or 10% of the estimate, whichever is larger
UNRECORDED_GRACE_DAYS = 3  # locked: email charge overdue by >3 days → unrecorded
EARLY_MONTH_BOUNDARY_DAY = 3  # locked: median_day ≤ 3 also scans the previous-month tail
PREV_MONTH_TAIL_DAYS = 3  # locked: last 3 days of the previous month for boundary fuzz


@dataclass(frozen=True)
class ExpectedCharge:
    """One expected charge for the current month (mirrors ``ExpectedChargeInfo``)."""

    merchant: str  # normalized key
    display_name: str
    amount_estimate: float
    expected_day: int  # median day-of-month, clamped to the month's length
    status: str  # "upcoming" | "arrived" | "assumed" | "unrecorded"
    channel: str  # "email" | "statement" | "mixed"
    cadence: str  # "monthly" | "annual"
    category: str | None = None
    actual_amount: float | None = None  # arrived only
    actual_date: str | None = None  # arrived only, YYYY-MM-DD
    previous_amount: float | None = None  # annual price memory (last year's charge)


@dataclass(frozen=True)
class UpcomingResult:
    charges: list[ExpectedCharge]
    recurring_merchants: set[str]  # normalized keys (for the L5 discretionary subtraction)


@dataclass(frozen=True)
class _Event:
    """One qualifying charge row reduced to what classification needs."""

    year_month: str
    day: int
    amount: float
    category: str
    is_stmt: bool

    @property
    def when(self) -> date:
        year, month = int(self.year_month[:4]), int(self.year_month[5:7])
        return date(year, month, min(max(self.day, 1), calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class _Profile:
    merchant: str
    display_name: str
    amount_estimate: float
    median_day: int
    cadence: str  # "monthly" | "annual"
    channel: str
    category: str | None
    confidence: str  # "high" | "medium"
    previous_amount: float | None  # annual: last year's charge amount
    anniversary_month: int | None  # annual only: emit an expected charge only in this calendar month


def _display_name(merchant: str) -> str:
    """Title-case a fully-cased key for display (mirrors ``_display_company``).

    Bank feeds ship ALL-CAPS names; alias-canonicalized merchants are already
    mixed-case and pass through untouched.
    """
    if not merchant:
        return "unknown merchant"

    def fix(word: str) -> str:
        if len(word) > 1 and word.isupper():
            return word[0].upper() + word[1:].lower()
        return word

    return " ".join(fix(w) for w in merchant.split())


def _included(item: Mapping[str, Any]) -> bool:
    """Row inclusion (L1): statement-created rows COUNT — they are the statement channel."""
    if item.get("DeletedAt") or item.get("Ignored"):
        return False
    if item.get("TransactionType") not in SPENDING_TYPES:
        return False
    return item.get("Amount") is not None


def _day_of(item: Mapping[str, Any]) -> int | None:
    raw = item.get("DateFileName") or ""
    try:
        return int(raw[8:10])
    except (ValueError, IndexError):
        return None


def _date_str(item: Mapping[str, Any]) -> str:
    return (item.get("DateFileName") or "")[:10].replace(".", "-")


def _is_stmt(item: Mapping[str, Any]) -> bool:
    return "_stmt_" in (item.get("DateFileName") or "")


def _within_tolerance(amount: float, estimate: float) -> bool:
    return abs(amount - estimate) <= max(AMOUNT_TOL_ABS, AMOUNT_TOL_PCT * abs(estimate))


def _cv(values: list[float]) -> float:
    """Coefficient of variation; 0.0 for <2 values (a single point is perfectly stable)."""
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    if mean <= 0:
        return 0.0
    return statistics.stdev(values) / mean


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


class UpcomingService:
    """Derive per-merchant expected charges for the current month (L1/L3/L4).

    Read-only over ``ISpendingSummary``; dual-backend safe (consumes only the
    storage-agnostic protocol). 1-hour in-memory cache keyed by ``(year_month,)``.
    """

    def __init__(
        self,
        spending_summary: ISpendingSummary,
        merchant_alias_service: IMerchantAliasService,
    ) -> None:
        self._summary = spending_summary
        self._aliases = merchant_alias_service
        self._cache: dict[tuple[str], UpcomingResult] = {}
        self._cache_time: dict[tuple[str], float] = {}

    def get_upcoming(self, year_month: str) -> UpcomingResult:
        """Expected charges + recurring-merchant set for ``year_month`` (cached 1h)."""
        key = (year_month,)
        now = time.time()
        cached = self._cache.get(key)
        if cached is not None and (now - self._cache_time.get(key, 0)) < _CACHE_TTL_SECONDS:
            return cached
        result = self._compute(year_month)
        self._cache[key] = result
        self._cache_time[key] = now
        return result

    def invalidate_cache(self) -> None:
        self._cache.clear()
        self._cache_time.clear()

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def _compute(self, year_month: str) -> UpcomingResult:
        target = date(int(year_month[:4]), int(year_month[5:7]), 1)
        # 14 keys, oldest first: 13 complete months + the current month (last).
        window_keys = [
            (target - relativedelta(months=i)).strftime("%Y-%m") for i in range(_WINDOW_COMPLETE_MONTHS, -1, -1)
        ]
        current_key = window_keys[-1]
        complete_keys = window_keys[:-1]
        prev_key = complete_keys[-1]
        aliases = self._aliases.get_aliases_map()

        with ThreadPoolExecutor(max_workers=min(_MONTH_QUERY_WORKERS, len(window_keys))) as executor:
            fetched = list(executor.map(self._summary.query_month, window_keys))
        items_by_month = dict(zip(window_keys, fetched, strict=True))

        # Per-merchant charge events across the whole window (annual spacing needs
        # the current month too); classification restricts to complete months.
        events: dict[str, list[_Event]] = {}
        for ym in window_keys:
            for item in items_by_month[ym]:
                if not _included(item):
                    continue
                merchant = normalize_merchant(str(item.get("Company") or ""), aliases)
                if not merchant or not is_recognizable_merchant(merchant):
                    continue
                day = _day_of(item)
                if day is None:
                    continue
                raw_amount = item.get("Amount")
                if raw_amount is None:
                    continue
                events.setdefault(merchant, []).append(
                    _Event(
                        year_month=ym,
                        day=day,
                        amount=float(raw_amount),
                        category=str(item.get("Category") or "miscellaneous"),
                        is_stmt=_is_stmt(item),
                    )
                )

        complete_set = set(complete_keys)
        profiles: list[_Profile] = []
        for merchant, evs in events.items():
            profile = self._classify(merchant, sorted(evs, key=lambda e: e.when), complete_keys, complete_set)
            if profile is not None:
                profiles.append(profile)

        recurring_merchants = {p.merchant for p in profiles}
        charges = self._match(
            profiles, items_by_month[current_key], items_by_month[prev_key], target, prev_key, aliases
        )
        return UpcomingResult(charges=charges, recurring_merchants=recurring_merchants)

    # ------------------------------------------------------------------
    # Recurring-profile classification, per L3.
    # ------------------------------------------------------------------

    def _classify(
        self, merchant: str, evs: list[_Event], complete_keys: list[str], complete_set: set[str]
    ) -> _Profile | None:
        complete_evs = [e for e in evs if e.year_month in complete_set]
        present = {e.year_month for e in complete_evs}

        month_amount: dict[str, float] = {}
        for e in complete_evs:
            month_amount[e.year_month] = month_amount.get(e.year_month, 0.0) + e.amount

        # Consecutive active streak ending at the most recent complete month.
        streak: list[str] = []
        for ym in reversed(complete_keys):
            if ym in present:
                streak.append(ym)
            else:
                break

        category = self._modal_category(complete_evs or evs)
        channel = self._channel(complete_evs or evs)

        is_fixed = len(streak) >= _FIXED_MIN_CONSECUTIVE and _cv([month_amount[ym] for ym in streak]) < RECURRING_CV_MAX
        recent6 = complete_keys[-_VARIABLE_WINDOW:]
        recent6_set = set(recent6)
        active_recent = sum(1 for ym in recent6 if ym in present)
        is_variable = (not is_fixed) and active_recent >= _VARIABLE_MIN_MONTHS

        if is_fixed or is_variable:
            # Bill-cadence guard: bills charge ~once a month. A merchant whose mean
            # charges-per-active-month over the trailing 6 complete months exceeds
            # the threshold is a multi-visit everyday merchant (groceries), not a
            # bill — pencil nothing and keep its whole spend in the discretionary
            # curve (it joins neither `charges` nor `recurring_merchants`).
            recent6_charges = sum(1 for e in complete_evs if e.year_month in recent6_set)
            charges_per_active_month = recent6_charges / active_recent if active_recent > 0 else 0.0
            if charges_per_active_month > BILL_CADENCE_MAX_PER_MONTH:
                return None
            if is_fixed:
                return _Profile(
                    merchant=merchant,
                    display_name=_display_name(merchant),
                    amount_estimate=round(complete_evs[-1].amount, 2),  # most recent charge
                    median_day=self._median_day(complete_evs),
                    cadence="monthly",
                    channel=channel,
                    category=category,
                    confidence="high",
                    previous_amount=None,
                    anniversary_month=None,
                )
            last3 = [e.amount for e in complete_evs[-3:]]
            return _Profile(
                merchant=merchant,
                display_name=_display_name(merchant),
                amount_estimate=round(statistics.median(last3) if last3 else 0.0, 2),
                median_day=self._median_day(complete_evs),
                cadence="monthly",
                channel=channel,
                category=category,
                confidence="medium",
                previous_amount=None,
                anniversary_month=None,
            )

        return self._classify_annual(merchant, evs, complete_evs, channel, category)

    def _classify_annual(
        self, merchant: str, evs: list[_Event], complete_evs: list[_Event], channel: str, category: str | None
    ) -> _Profile | None:
        # Need ≥2 charges 11-13 months apart with amounts within tolerance.
        annual_pair: tuple[_Event, _Event] | None = None
        for i in range(len(evs)):
            for j in range(i + 1, len(evs)):
                spacing = _months_between(evs[i].when, evs[j].when)
                if _ANNUAL_MIN_SPACING <= spacing <= _ANNUAL_MAX_SPACING and _within_tolerance(
                    evs[i].amount, evs[j].amount
                ):
                    annual_pair = (evs[i], evs[j])  # oldest-first sort → (earlier, later)
        if annual_pair is None:
            return None

        earlier, _later = annual_pair
        # "Last year's amount": the most recent complete-month occurrence (the
        # prior anniversary), falling back to the earlier charge of the pair.
        reference = complete_evs[-1] if complete_evs else earlier
        annual_days = [e.day for e in evs]
        return _Profile(
            merchant=merchant,
            display_name=_display_name(merchant),
            amount_estimate=round(reference.amount, 2),
            median_day=round(statistics.median(annual_days)),
            cadence="annual",
            channel=channel,
            category=category,
            confidence="medium",
            previous_amount=round(reference.amount, 2),
            anniversary_month=reference.when.month,
        )

    @staticmethod
    def _median_day(evs: list[_Event]) -> int:
        return round(statistics.median([e.day for e in evs])) if evs else 1

    @staticmethod
    def _modal_category(evs: list[_Event]) -> str | None:
        cats = [e.category for e in evs if e.category]
        return Counter(cats).most_common(1)[0][0] if cats else None

    @staticmethod
    def _channel(evs: list[_Event]) -> str:
        recent = evs[-_CHANNEL_RECENT_CHARGES:]
        if not recent:
            return "email"
        stmt = sum(1 for e in recent if e.is_stmt)
        email = len(recent) - stmt
        if email == 0:
            return "statement"
        if stmt == 0:
            return "email"
        return "mixed"

    # ------------------------------------------------------------------
    # Status machine (L4)
    # ------------------------------------------------------------------

    def _match(
        self,
        profiles: list[_Profile],
        current_items: Sequence[Mapping[str, Any]],
        prev_items: Sequence[Mapping[str, Any]],
        target: date,
        prev_key: str,
        aliases: Mapping[str, str],
    ) -> list[ExpectedCharge]:
        today = forecast_today()
        days_in_month = calendar.monthrange(target.year, target.month)[1]
        current_month_num = target.month

        # Candidate rows indexed by normalized merchant (used-row set below).
        current_by_merchant: dict[str, list[Mapping[str, Any]]] = {}
        for item in current_items:
            if not _included(item):
                continue
            current_by_merchant.setdefault(normalize_merchant(str(item.get("Company") or ""), aliases), []).append(item)

        prev_year, prev_month = int(prev_key[:4]), int(prev_key[5:7])
        prev_tail_cut = calendar.monthrange(prev_year, prev_month)[1] - PREV_MONTH_TAIL_DAYS + 1
        prev_tail_by_merchant: dict[str, list[Mapping[str, Any]]] = {}
        for item in prev_items:
            if not _included(item):
                continue
            day = _day_of(item)
            if day is None or day < prev_tail_cut:
                continue
            prev_tail_by_merchant.setdefault(normalize_merchant(str(item.get("Company") or ""), aliases), []).append(
                item
            )

        used: set[tuple[Any, Any]] = set()
        charges: list[ExpectedCharge] = []
        for profile in sorted(profiles, key=lambda p: p.merchant):
            # Annual charges pencil only in their anniversary month.
            if profile.anniversary_month is not None and profile.anniversary_month != current_month_num:
                continue

            expected_day = min(max(profile.median_day, 1), days_in_month)
            candidates = list(current_by_merchant.get(profile.merchant, []))
            if profile.median_day <= EARLY_MONTH_BOUNDARY_DAY:
                candidates += prev_tail_by_merchant.get(profile.merchant, [])

            match = self._pick_match(candidates, profile.amount_estimate, expected_day, used)
            if match is not None:
                used.add((match.get("ForwardedTo"), match.get("DateFileName")))
                charges.append(
                    ExpectedCharge(
                        merchant=profile.merchant,
                        display_name=profile.display_name,
                        amount_estimate=profile.amount_estimate,
                        expected_day=expected_day,
                        status="arrived",
                        channel=profile.channel,
                        cadence=profile.cadence,
                        category=profile.category,
                        actual_amount=round(float(match["Amount"]), 2),
                        actual_date=_date_str(match),
                        previous_amount=profile.previous_amount,
                    )
                )
                continue

            status = self._status_for_unmatched(profile, expected_day, today.day)
            charges.append(
                ExpectedCharge(
                    merchant=profile.merchant,
                    display_name=profile.display_name,
                    amount_estimate=profile.amount_estimate,
                    expected_day=expected_day,
                    status=status,
                    channel=profile.channel,
                    cadence=profile.cadence,
                    category=profile.category,
                    previous_amount=profile.previous_amount,
                )
            )
        return charges

    @staticmethod
    def _pick_match(
        candidates: list[Mapping[str, Any]], estimate: float, expected_day: int, used: set[tuple[Any, Any]]
    ) -> Mapping[str, Any] | None:
        """Closest unused row (by day distance, then date) within amount tolerance."""
        eligible = [
            item
            for item in candidates
            if (item.get("ForwardedTo"), item.get("DateFileName")) not in used
            and _within_tolerance(float(item["Amount"]), estimate)
        ]
        if not eligible:
            return None
        return min(eligible, key=lambda item: (abs((_day_of(item) or 0) - expected_day), _date_str(item)))

    @staticmethod
    def _status_for_unmatched(profile: _Profile, expected_day: int, today_day: int) -> str:
        if expected_day > today_day:
            return "upcoming"
        if profile.channel == "statement":
            # Statement-observed: happened in reality, awaiting import. Never alarming.
            return "assumed"
        # Email/mixed: still within grace renders as upcoming; past grace is a quiet note.
        if today_day - expected_day > UNRECORDED_GRACE_DAYS:
            return "unrecorded"
        return "upcoming"
