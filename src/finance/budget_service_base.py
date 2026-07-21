"""Abstract base class for BudgetService (DynamoDB) and BudgetServiceLocal (SQLite).

Contains shared business logic (historical averages, type inference, backup)
and the storage-agnostic public API (put_targets/put_groups template methods).
"""

import json
import logging
import statistics
import threading
import time
from abc import ABC, abstractmethod
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from dateutil.relativedelta import relativedelta

from src.finance.decimal_utils import DecimalEncoder as _DecimalEncoder
from src.finance.demo_clock import app_today
from src.finance.protocols import ISpendingSummary

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_PERSONAL_DIR = Path(__file__).resolve().parents[2] / "data" / "config"

DEFAULT_GROUPS = [
    {
        "name": "Food & Dining",
        "categories": [
            "groceries",
            "restaurant/dining",
            "coffee & cafes",
            "alcohol",
        ],
    },
    {
        "name": "Housing",
        "categories": [
            "rent",
            "mortgage",
            "utilities",
            "home maintenance",
            "home goods",
            "strata/hoa",
        ],
    },
    {
        "name": "Transport",
        "categories": [
            "gasoline",
            "auto maintenance",
            "car payment",
            "public transit",
            "rideshare & taxi",
        ],
    },
    {
        "name": "Health & Personal",
        "categories": [
            "health care",
            "personal care",
            "therapy",
            "fitness",
            "pets",
            "childcare",
        ],
    },
    {
        "name": "Entertainment",
        "categories": [
            "entertainment",
            "hobbies",
            "subscriptions",
            "travel",
        ],
    },
    {
        "name": "Shopping",
        "categories": [
            "clothing",
            "technology",
            "gifts",
            "baby & kids",
        ],
    },
    {
        "name": "Bills & Services",
        "categories": [
            "insurance",
            "phone",
            "internet",
            "bank fees",
            "professional services",
        ],
    },
    {
        "name": "Other",
        "categories": [
            "education",
            "taxes",
            "charitable giving",
            "moving",
            "miscellaneous",
        ],
    },
]


class BudgetServiceBase(ABC):
    """Storage-agnostic contract and shared logic for budget configuration."""

    def __init__(self) -> None:
        self._historical_cache: dict[int, dict[str, Any]] = {}
        self._historical_cache_time: dict[int, float] = {}
        # Single-flights the miss path across the request threadpool so one
        # invalidation isn't followed by N parallel 6-month aggregations.
        self._historical_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Abstract: storage-specific reads (implemented per backend)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_targets(self, year: int) -> dict[str, Any] | None:
        """Get budget targets for a year. Returns None if not configured."""

    @abstractmethod
    def get_groups(self, year: int) -> dict[str, Any] | None:
        """Get category groups for a year. Returns None if not configured."""

    # ------------------------------------------------------------------
    # Abstract: storage-specific writes (implemented per backend)
    # ------------------------------------------------------------------

    @abstractmethod
    def _store_targets(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        """Persist targets data. Returns new version. Raises VersionConflictError on conflict."""

    @abstractmethod
    def _store_groups(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        """Persist groups data. Returns new version. Raises VersionConflictError on conflict."""

    # ------------------------------------------------------------------
    # Concrete: shared business logic
    # ------------------------------------------------------------------

    def put_targets(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        """Write budget targets with monthly_amount derivation and backup.

        Returns new version. Raises VersionConflictError on conflict.
        """
        categories = data.get("categories", {})
        for cat_config in categories.values():
            target = cat_config.get("target", 0)
            cat_config["monthly_amount"] = round(target / 12, 2)
        new_version = self._store_targets(year, data, expected_version)
        self._write_backup(year)
        return new_version

    def put_groups(self, year: int, data: dict[str, Any], expected_version: int | None) -> int:
        """Write category groups and backup. Returns new version."""
        new_version = self._store_groups(year, data, expected_version)
        self._write_backup(year)
        return new_version

    def get_historical_averages(self, spending_summary: ISpendingSummary, months: int = 6) -> dict[str, Any]:
        """Compute per-category monthly averages from recent transaction data.

        Returns dict with months_analyzed, period, and per-category stats.
        Caches result in memory for 1 hour. Single-flight: concurrent cold-cache
        callers serialize on ``_historical_lock`` and only the first aggregates.
        """
        now = time.time()
        cached = self._historical_cache.get(months)
        if cached and (now - self._historical_cache_time.get(months, 0)) < 3600:
            return cached

        with self._historical_lock:
            # Re-check under the lock: another thread may have built it while we
            # waited, so only the first miss runs the aggregation below.
            now = time.time()
            cached = self._historical_cache.get(months)
            if cached and (now - self._historical_cache_time.get(months, 0)) < 3600:
                return cached
            result = self._compute_historical_averages(spending_summary, months)
            self._historical_cache[months] = result
            self._historical_cache_time[months] = now
            return result

    def _compute_historical_averages(self, spending_summary: ISpendingSummary, months: int) -> dict[str, Any]:
        """Aggregate per-category monthly averages from recent summaries.

        The uncached compute half of :meth:`get_historical_averages`; runs at
        most once per cache miss under ``_historical_lock``.
        """
        today = app_today()
        # Exclude current incomplete month — start from previous month
        current = date(today.year, today.month, 1) - timedelta(days=1)
        current = date(current.year, current.month, 1)

        month_keys = []
        for i in range(months):
            d = current - relativedelta(months=i)
            month_keys.append(d.strftime("%Y-%m"))
        month_keys.reverse()  # oldest first

        # Aggregate per-category across months
        cat_data: dict[str, dict[str, Any]] = {}
        for ym in month_keys:
            summary = spending_summary.get_summary(ym)
            for cat, info in summary.get("by_category", {}).items():
                if cat not in cat_data:
                    cat_data[cat] = {"total": Decimal(0), "months_active": 0, "amounts": []}
                amount = info["amount"]
                cat_data[cat]["total"] += amount
                cat_data[cat]["months_active"] += 1
                cat_data[cat]["amounts"].append(float(amount))

        categories = {}
        for cat, info in cat_data.items():
            total = float(info["total"])
            months_active = info["months_active"]
            monthly_avg = total / months if months > 0 else 0
            amounts = info["amounts"]

            cv = None
            if len(amounts) >= 2 and monthly_avg > 0:
                std = statistics.stdev(amounts)
                cv = std / (total / months_active) if months_active > 0 else None

            suggested_type = self.infer_category_type(months_active, months, cv)

            # Suggested monthly rounded to nearest $5
            suggested_monthly = round(monthly_avg / 5) * 5 if monthly_avg > 0 else 0
            if suggested_monthly == 0 and monthly_avg > 0:
                suggested_monthly = 5

            # Suggested annual
            if suggested_type == "lumpy":
                suggested_annual = round(suggested_monthly * 12 / 100) * 100
                if suggested_annual == 0 and suggested_monthly > 0:
                    suggested_annual = 100
            else:
                suggested_annual = suggested_monthly * 12

            categories[cat] = {
                "monthly_avg": round(monthly_avg, 2),
                "total": round(total, 2),
                "months_active": months_active,
                "suggested_type": suggested_type,
                "suggested_monthly": suggested_monthly,
                "suggested_annual": suggested_annual,
            }

        return {
            "months_analyzed": months,
            "period": {"from": month_keys[0], "to": month_keys[-1]} if month_keys else {},
            "categories": categories,
        }

    def get_category_anomalies(
        self,
        spending_summary: ISpendingSummary,
        year_month: str,
        months: int = 6,
        annotated_amounts: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect quiet anomalies in the target month against a prior baseline.

        For each category, compares the target month's spend against the mean +
        standard deviation of the ``months`` immediately prior. Emits an entry
        when:
          * |current - baseline_mean| / baseline_stdev >= 1.5, or
          * current == 0 and the category was active in every baseline month.

        Returned dicts use the shape:
          ``{category, current, baseline, severity, reason}``
        where ``baseline`` is the prior-window mean. Phrasing in ``reason`` is
        intentionally calm and observational — never alarmist — so it can be
        rendered directly in the UI under the "Notable changes" card.

        ``annotated_amounts`` (category → summed amount of user-commented,
        non-ignored, non-deleted spending this month) enables *proportional*
        comment handling. For an above-baseline spike, the anomaly is re-tested
        against ``current - annotated`` using the same z-score criterion:
          * if the remainder is no longer anomalous, the entry is dropped
            (the comment fully explains the change), otherwise
          * the entry is kept, gains an ``annotated_amount`` field, and its
            ``reason`` is calmly extended (e.g. ``"… ($96 of $893 annotated)"``).
        Annotation only explains *elevated* spending, so it is not applied to
        below-baseline or unexpected-zero anomalies.
        """
        annotated_amounts = annotated_amounts or {}
        parts = year_month.split("-")
        target_date = date(int(parts[0]), int(parts[1]), 1)
        baseline_keys = [(target_date - relativedelta(months=i)).strftime("%Y-%m") for i in range(months, 0, -1)]

        per_month: list[dict[str, float]] = []
        all_cats: set[str] = set()
        for ym in baseline_keys:
            summary = spending_summary.get_summary(ym)
            month_cats = {cat: float(info["amount"]) for cat, info in summary.get("by_category", {}).items()}
            per_month.append(month_cats)
            all_cats.update(month_cats.keys())

        baseline_data: dict[str, list[float]] = {cat: [m.get(cat, 0.0) for m in per_month] for cat in all_cats}

        target_summary = spending_summary.get_summary(year_month)
        target_cats = {cat: float(info["amount"]) for cat, info in target_summary.get("by_category", {}).items()}

        anomalies: list[dict[str, Any]] = []
        for cat, amounts in baseline_data.items():
            if not amounts:
                continue
            mean = sum(amounts) / len(amounts)
            current = target_cats.get(cat, 0.0)
            months_active = sum(1 for a in amounts if a > 0)

            # Unexpected zero: was active every baseline month, current is 0
            if current == 0 and months_active == len(amounts) and mean > 0:
                anomalies.append(
                    {
                        "category": cat,
                        "current": 0.0,
                        "baseline": round(mean, 2),
                        "severity": "medium",
                        "reason": f"no activity this month — usually averages ${mean:,.0f}",
                    }
                )
                continue

            if len(amounts) < 2:
                continue
            stdev = statistics.stdev(amounts)
            if stdev == 0:
                continue
            z = (current - mean) / stdev
            abs_z = abs(z)
            if abs_z < 1.5:
                continue

            severity = "low" if abs_z < 2 else ("medium" if abs_z < 3 else "high")
            direction = "above" if z > 0 else "below"
            pct = ((current - mean) / mean * 100) if mean > 0 else 0.0
            reason = (
                f"roughly {abs(pct):.0f}% {direction} the {len(amounts)}-month average of ${mean:,.0f}"
                if mean > 0
                else f"${current:,.0f} this month, baseline near zero"
            )

            # Proportional comment handling: subtract user-annotated spending and
            # re-test the remainder against the same z-score threshold.
            annotated = float(annotated_amounts.get(cat, 0.0))
            annotated_applied = 0.0
            if annotated > 0 and current > mean:
                adjusted = current - annotated
                # One-sided re-test: the anomaly survives only if the remainder is
                # still an *above*-baseline spike. (An annotation larger than the
                # whole excess fully explains it — abs() would resurrect it as a
                # phantom below-baseline anomaly.)
                if (adjusted - mean) / stdev < 1.5:
                    continue  # comment fully explains the change — drop
                annotated_applied = annotated
                reason = f"{reason} (${annotated:,.0f} of ${current:,.0f} annotated)"

            entry: dict[str, Any] = {
                "category": cat,
                "current": round(current, 2),
                "baseline": round(mean, 2),
                "severity": severity,
                "reason": reason,
            }
            if annotated_applied:
                entry["annotated_amount"] = round(annotated_applied, 2)
            anomalies.append(entry)

        # Stable order: highest severity first, then by absolute deviation
        sev_rank = {"high": 3, "medium": 2, "low": 1}
        anomalies.sort(
            key=lambda a: (sev_rank.get(a["severity"], 0), abs(a["current"] - a["baseline"])),
            reverse=True,
        )
        return anomalies

    def invalidate_cache(self) -> None:
        """Clear the historical averages cache."""
        with self._historical_lock:
            self._historical_cache.clear()
            self._historical_cache_time.clear()

    @staticmethod
    def infer_category_type(
        months_active: int,
        months_total: int,
        coefficient_of_variation: float | None = None,
    ) -> str:
        """Infer category type from spending frequency and variance.

        6/6 active + cv < 0.15 → "fixed"
        6/6 active + cv >= 0.15 (or cv unknown) → "variable"
        1-5/6 active → "lumpy"
        0/6 active → "none"
        """
        if months_active == 0:
            return "none"
        if months_active < months_total:
            return "lumpy"
        # reached when every month in the window was active
        if coefficient_of_variation is not None and coefficient_of_variation < 0.15:
            return "fixed"
        return "variable"

    def _write_backup(self, year: int) -> None:
        """Write merged config to data/config/budget_config.json (gitignored)."""
        try:
            targets_item = self.get_targets(year)
            groups_item = self.get_groups(year)

            targets_data = targets_item.get("Data", {}) if targets_item else {}
            groups_data = groups_item.get("Data", {}).get("groups", DEFAULT_GROUPS) if groups_item else DEFAULT_GROUPS

            backup = {
                "year": year,
                "spending_ceiling": targets_data.get("spending_ceiling", 0),
                "categories": targets_data.get("categories", {}),
                "groups": groups_data,
            }

            _PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
            with open(_PERSONAL_DIR / "budget_config.json", "w") as f:
                json.dump(backup, f, indent=2, cls=_DecimalEncoder)
                f.write("\n")
        except Exception:
            logger.exception("Failed to write budget backup")
