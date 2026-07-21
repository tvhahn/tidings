"""Merchant-level recurring detection, price change, and burn-rate analysis.

Computes per-merchant temporal patterns from existing per-month
``SpendingSummary.by_company`` data. No new storage - entirely derived from
six months of summaries with a 1-hour in-memory cache. Reuses
``BudgetServiceBase.infer_category_type()`` so a merchant active 6/6 months
with low coefficient-of-variation classifies as ``"fixed"`` (subscription),
6/6 with higher variance as ``"variable"``, 1-5/6 as ``"lumpy"``, and absent
as ``"none"``.
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from datetime import date
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta

from src.finance.budget_service_base import BudgetServiceBase

if TYPE_CHECKING:
    from src.finance.protocols import IMerchantAliasService, ISpendingSummary

logger = logging.getLogger(__name__)


# Decisions resolved during planning:
#   * price-change tolerance: ≥5% AND ≥$1 absolute
#   * "consistency" for price-change: only fixed merchants
#   * committed burn = sum of avg_amount for fixed merchants (excludes variable)
#   * new merchant: active in current month AND prior month, absent earlier
#     in window — drops one-shot purchases (annual fees, single doctor visits)
#     that the original "≥3 prior months absent" rule mis-flagged
#   * churned: was fixed/variable two months ago, absent for ≥2 most recent months
PRICE_CHANGE_PCT = 0.05
PRICE_CHANGE_ABS = 1.0
CHURN_MIN_RECENT_ABSENT = 2

# Shared recurring-classification threshold: coefficient-of-variation ceiling
# below which a merchant's amounts are "fixed" (stable subscription) rather than
# "variable". Mirrors ``BudgetServiceBase.infer_category_type`` — this module
# reaches that logic through ``infer_category_type``, and ``UpcomingService``
# imports this constant so the two services never fork the 0.15 bar silently.
RECURRING_CV_MAX = 0.15


def is_recognizable_merchant(name: str) -> bool:
    """Filter out company strings that don't represent a real merchant.

    The upstream summary occasionally surfaces ``"Unknown"`` (parser fallback
    for transactions where a payee couldn't be extracted) and raw Interac
    e-Transfer descriptions that include the recipient name plus a memo
    pipe-delimited (e.g.
    ``"Morgan Westland for the amount of $123.45 (CAD) | Thanks ... | CAsAmPLe"``).
    These shouldn't surface on the merchants page; alias normalization
    typically catches them but not always.
    """
    s = name.strip()
    if not s:
        return False
    if s.lower() == "unknown":
        return False
    # Interac e-Transfer memo strings always contain a pipe separator.
    if "|" in s:
        return False
    return "for the amount of" not in s.lower()


class MerchantIntelligenceService:
    """Per-merchant recurring detection and committed-burn calculation.

    Read-only over ``ISpendingSummary``; safe under both DynamoDB and SQLite
    backends because it only consumes the storage-agnostic protocol.
    """

    def __init__(
        self,
        spending_summary: ISpendingSummary,
        merchant_alias_service: IMerchantAliasService,
    ) -> None:
        self._summary = spending_summary
        self._aliases = merchant_alias_service
        self._cache: dict[tuple[str, int], dict[str, Any]] = {}
        self._cache_time: dict[tuple[str, int], float] = {}
        # Single-flights the miss path across the request threadpool so one
        # invalidation isn't followed by N parallel 6-month recomputes.
        self._lock = threading.Lock()

    def get_intelligence(self, year_month: str, months: int = 6) -> dict[str, Any]:
        """Return the full merchant-intelligence payload for ``year_month``.

        Caches the result in memory for 1 hour, keyed by (year_month, months).
        Single-flight: concurrent cold-cache callers serialize on ``_lock`` and
        only the first runs ``_compute``.
        """
        key = (year_month, months)
        now = time.time()
        cached = self._cache.get(key)
        if cached and (now - self._cache_time.get(key, 0)) < 3600:
            return cached

        with self._lock:
            # Re-check under the lock: another thread may have built it while we
            # waited, so only the first miss runs _compute.
            now = time.time()
            cached = self._cache.get(key)
            if cached and (now - self._cache_time.get(key, 0)) < 3600:
                return cached
            result = self._compute(year_month, months)
            self._cache[key] = result
            self._cache_time[key] = now
            return result

    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_time.clear()

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def _compute(self, year_month: str, months: int) -> dict[str, Any]:
        parts = year_month.split("-")
        target_date = date(int(parts[0]), int(parts[1]), 1)
        # Window ends at year_month inclusive; oldest first.
        window_keys = [(target_date - relativedelta(months=i)).strftime("%Y-%m") for i in range(months - 1, -1, -1)]
        aliases = self._aliases.get_aliases_map()

        # Aggregate per-month per-canonical-merchant.
        per_month_amounts: dict[str, list[float]] = {}
        per_month_counts: dict[str, list[int]] = {}
        latest_category: dict[str, str] = {}
        zero_amounts = [0.0] * len(window_keys)
        zero_counts = [0] * len(window_keys)

        for idx, ym in enumerate(window_keys):
            month_summary = self._summary.get_summary(ym)
            for raw_company, info in month_summary.get("by_company", {}).items():
                if not isinstance(raw_company, str) or not raw_company:
                    continue
                canonical = aliases.get(raw_company.lower(), raw_company)
                if not is_recognizable_merchant(canonical):
                    continue
                amounts = per_month_amounts.setdefault(canonical, list(zero_amounts))
                counts = per_month_counts.setdefault(canonical, list(zero_counts))
                amounts[idx] += float(info.get("amount", 0))
                counts[idx] += int(info.get("count", 0))
                cat = info.get("category")
                if cat:
                    latest_category[canonical] = cat

        merchants: list[dict[str, Any]] = []
        for canonical, amounts in per_month_amounts.items():
            counts = per_month_counts[canonical]
            months_active = sum(1 for a in amounts if a > 0)
            total = round(sum(amounts), 2)
            avg_active = total / months_active if months_active > 0 else 0.0

            cv: float | None = None
            if months_active >= 2:
                active_amounts = [a for a in amounts if a > 0]
                stdev = statistics.stdev(active_amounts)
                mean = sum(active_amounts) / len(active_amounts)
                cv = stdev / mean if mean > 0 else None

            frequency_type = BudgetServiceBase.infer_category_type(months_active, len(window_keys), cv)
            is_recurring = frequency_type in ("fixed", "variable")

            price_change = self._detect_price_change(amounts, window_keys) if frequency_type == "fixed" else None
            is_new = self._is_new(amounts)
            is_churned = self._is_churned(amounts)

            merchants.append(
                {
                    "company": canonical,
                    "total": total,
                    "monthly_amounts": [round(a, 2) for a in amounts],
                    "monthly_counts": counts,
                    "months_active": months_active,
                    "avg_amount": round(avg_active, 2),
                    "frequency_type": frequency_type,
                    "category": latest_category.get(canonical, "miscellaneous"),
                    "is_recurring": is_recurring,
                    "price_change": price_change,
                    "is_new": is_new,
                    "is_churned": is_churned,
                }
            )

        merchants.sort(key=lambda m: m["total"], reverse=True)

        # Summary block — recurring burn rate, new/churned, price changes.
        recurring_burn_rate = round(sum(m["avg_amount"] for m in merchants if m["frequency_type"] == "fixed"), 2)
        recurring_count = sum(1 for m in merchants if m["frequency_type"] == "fixed")

        # Discretionary = current-month spend minus the recurring burn rate
        # (i.e. what landed this month outside the locked-in subscriptions).
        target_summary = self._summary.get_summary(year_month)
        discretionary_this_month = round(float(target_summary.get("total_spending", 0)) - recurring_burn_rate, 2)

        new_merchants = [m["company"] for m in merchants if m["is_new"]]
        churned_merchants = [m["company"] for m in merchants if m["is_churned"]]
        price_changes = [
            {
                "merchant": m["company"],
                "old_amount": m["price_change"]["old_amount"],
                "new_amount": m["price_change"]["new_amount"],
                "since_month": m["price_change"]["since_month"],
            }
            for m in merchants
            if m["price_change"]
        ]

        return {
            "month": year_month,
            "months_analyzed": len(window_keys),
            "period": {"from": window_keys[0], "to": window_keys[-1]},
            "merchants": merchants,
            "summary": {
                "recurring_burn_rate": recurring_burn_rate,
                "recurring_count": recurring_count,
                "discretionary_this_month": discretionary_this_month,
                "new_merchants": new_merchants,
                "churned_merchants": churned_merchants,
                "price_changes": price_changes,
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_price_change(amounts: list[float], window_keys: list[str]) -> dict[str, Any] | None:
        """Compare the latest two non-zero months. Returns None if the change
        is below the configured tolerance.

        ``amounts`` and ``window_keys`` are oldest-first and the same length.
        """
        positives = [(i, a) for i, a in enumerate(amounts) if a > 0]
        if len(positives) < 2:
            return None
        _, prev_amt = positives[-2]
        curr_idx, curr_amt = positives[-1]
        delta = curr_amt - prev_amt
        if abs(delta) < PRICE_CHANGE_ABS:
            return None
        if prev_amt <= 0 or abs(delta) / prev_amt < PRICE_CHANGE_PCT:
            return None
        return {
            "old_amount": round(prev_amt, 2),
            "new_amount": round(curr_amt, 2),
            "since_month": window_keys[curr_idx],
        }

    @staticmethod
    def _is_new(amounts: list[float]) -> bool:
        """True iff the merchant is active in the current month AND the
        immediately prior month, and was absent earlier in the window.

        The earlier rule fired on any merchant active in the current month
        with ≥3 absent prior months, which over-flagged one-off purchases
        (annual professional fees, single doctor visits, single grocery
        trips). Requiring a second consecutive month is a stronger signal
        that a recurring relationship is forming.
        """
        if len(amounts) < 2 or amounts[-1] <= 0 or amounts[-2] <= 0:
            return False
        earlier = amounts[:-2]
        return all(a == 0 for a in earlier)

    @staticmethod
    def _is_churned(amounts: list[float]) -> bool:
        """True iff the merchant was active for most of the early window but
        has been silent for the most recent ``CHURN_MIN_RECENT_ABSENT`` months."""
        if len(amounts) <= CHURN_MIN_RECENT_ABSENT:
            return False
        recent = amounts[-CHURN_MIN_RECENT_ABSENT:]
        prior = amounts[:-CHURN_MIN_RECENT_ABSENT]
        if any(a > 0 for a in recent):
            return False
        prior_active = sum(1 for a in prior if a > 0)
        return prior_active >= max(2, len(prior) - 1)
