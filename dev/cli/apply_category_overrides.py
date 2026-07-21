"""Apply category overrides from the resolver to existing transactions.

Default source is a live `TransactionsDB` scan across the last N months; pass
`--offline PATH` to read a CSV export instead. Matches each transaction through
the tiered resolver (Tiers 0/1/2 — fuzzy is intentionally out of scope here),
groups the resulting changes by tier for the `--dry-run` preview, and writes
CategoryAudit only on rows whose resolver output differs from the stored
category. Rows that already match are reported but left untouched.

Usage:
    uv run dev/cli/apply_category_overrides.py --dry-run
    uv run dev/cli/apply_category_overrides.py --months 6
    uv run dev/cli/apply_category_overrides.py --offline data/raw/transaction_db_rough/transactions.csv
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.finance.category_resolver import Tier, get_blacklisted_keys, resolve_override
from src.finance.config_loader import get_override_context
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.storage import create_transactions_db
from src.finance.user_mapping import get_forwarded_to_addresses

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


_TIERS: tuple[Tier, ...] = ("exact", "normalized", "alias", "fuzzy")


def _load_live_transactions(db, months: int) -> pd.DataFrame:
    """Scan the last `months` months across every ForwardedTo partition."""
    addresses = get_forwarded_to_addresses()
    today = datetime.now()
    rows: list[dict] = []
    for i in range(months):
        ym = (today - relativedelta(months=i)).strftime("%Y-%m")
        for addr in addresses:
            rows.extend(db.query_month_partition(addr, ym))
    if not rows:
        return pd.DataFrame(columns=["ForwardedTo", "DateFileName", "Company", "Category"])
    df = pd.DataFrame(rows)
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    if "Ignored" in df.columns:
        df = df[df["Ignored"] != True]  # noqa: E712 — avoid converting NaN to False
    return df


def find_mismatches(df: pd.DataFrame, overrides: dict, aliases: dict | None = None):
    """Classify every row in `df` against the resolver.

    Returns (to_update, already_correct, blacklisted) where each list carries
    the per-row `tier` field. Rows with no resolver hit and no blacklist match
    are dropped (they'd fall through to OpenAI at Lambda/webapp insert time).
    """
    to_update: list[dict] = []
    already_correct: list[dict] = []
    blacklisted: list[dict] = []

    # Union of Tier-1 and Tier-2 blacklists so a blacklisted group in either
    # tier is flagged in the breakdown.
    bl_tier1 = get_blacklisted_keys(overrides, aliases=None)
    bl_tier2 = get_blacklisted_keys(overrides, aliases=aliases) if aliases else {}

    for _, row in df.iterrows():
        company = row.get("Company")
        if pd.isna(company) or not company:
            continue
        company_str = str(company)

        match = resolve_override(company_str, overrides, aliases=aliases or None)
        if match is None:
            norm = normalize_merchant(company_str).lower()
            conflict = bl_tier1.get(norm)
            if not conflict and aliases:
                alias_norm = normalize_merchant(company_str, aliases=aliases).lower()
                conflict = bl_tier2.get(alias_norm)
            if conflict:
                blacklisted.append(
                    {
                        "ForwardedTo": row.get("ForwardedTo"),
                        "DateFileName": row.get("DateFileName"),
                        "Company": company_str,
                        "current_category": str(row.get("Category", "")).lower(),
                        "conflicting_keys": [k for k, _ in conflict],
                        "categories": [v for _, v in conflict],
                    }
                )
            continue

        expected_category = match.category.lower()
        current_category = str(row.get("Category", "")).lower()

        entry = {
            "ForwardedTo": row.get("ForwardedTo"),
            "DateFileName": row.get("DateFileName"),
            "Company": company_str,
            "current_category": current_category,
            "new_category": expected_category,
            "tier": match.tier,
            "matched_rule": match.matched_rule,
            "confidence": match.confidence,
        }

        if current_category == expected_category:
            already_correct.append(entry)
        else:
            to_update.append(entry)

    return to_update, already_correct, blacklisted


def apply_updates(to_update: list, db) -> None:
    """Apply category updates to the transactions backend."""
    for entry in to_update:
        db.update_category(
            entry["ForwardedTo"],
            entry["DateFileName"],
            entry["new_category"],
            source="override",
        )


def _tier_example(entry: dict) -> dict:
    """Render a single representative row for the tier-breakdown table."""
    example = {
        "company": entry["Company"],
        "matched_rule": entry.get("matched_rule"),
        "old": entry.get("current_category"),
        "new": entry.get("new_category"),
    }
    if entry.get("tier") == "fuzzy" and entry.get("confidence") is not None:
        example["confidence"] = round(float(entry["confidence"]), 3)
    return example


def _blacklist_example(entry: dict) -> dict:
    return {
        "company": entry["Company"],
        "conflicting_keys": entry["conflicting_keys"],
        "categories": entry["categories"],
    }


def build_summary(to_update: list, already_correct: list, blacklisted: list) -> dict:
    """Build a JSON-serializable summary grouped by company and by tier."""
    updated_by_company: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "old_category": None, "new_category": None, "tier": None}
    )
    for entry in to_update:
        key = entry["Company"].upper()
        info = updated_by_company[key]
        info["count"] += 1
        info["old_category"] = entry["current_category"]
        info["new_category"] = entry["new_category"]
        info["tier"] = entry["tier"]

    correct_by_company: dict[str, dict] = defaultdict(lambda: {"count": 0, "category": None, "tier": None})
    for entry in already_correct:
        key = entry["Company"].upper()
        info = correct_by_company[key]
        info["count"] += 1
        info["category"] = entry["current_category"]
        info["tier"] = entry["tier"]

    # Per-tier breakdown: prefer an update row for the example (more illustrative
    # than an already-correct row), fall back to an already-correct row.
    tier_updates: dict[str, list[dict]] = defaultdict(list)
    tier_correct: dict[str, list[dict]] = defaultdict(list)
    for entry in to_update:
        tier_updates[entry["tier"]].append(entry)
    for entry in already_correct:
        tier_correct[entry["tier"]].append(entry)

    tier_breakdown: dict[str, dict] = {}
    for tier in _TIERS:
        updates = tier_updates.get(tier, [])
        correct = tier_correct.get(tier, [])
        rows = len(updates) + len(correct)
        if rows == 0:
            continue
        example_source = updates[0] if updates else correct[0]
        tier_breakdown[tier] = {
            "rows": rows,
            "updates": len(updates),
            "skipped_due_to_match": len(correct),
            "example": _tier_example(example_source),
        }
    if blacklisted:
        tier_breakdown["blacklisted"] = {
            "rows": len(blacklisted),
            "updates": 0,
            "skipped_due_to_match": 0,
            "example": _blacklist_example(blacklisted[0]),
        }

    return {
        "tier_breakdown": tier_breakdown,
        "updated": [
            {
                "company": company,
                "count": info["count"],
                "old_category": info["old_category"],
                "new_category": info["new_category"],
                "tier": info["tier"],
            }
            for company, info in sorted(updated_by_company.items())
        ],
        "already_correct": [
            {
                "company": company,
                "count": info["count"],
                "category": info["category"],
                "tier": info["tier"],
            }
            for company, info in sorted(correct_by_company.items())
        ],
        "total_updated": len(to_update),
        "total_already_correct": len(already_correct),
        "total_blacklisted": len(blacklisted),
        "scope_note": (
            "CategoryAudit is written only for rows in `updated`. Rows in "
            "`already_correct` and `tier_breakdown.blacklisted` are left untouched."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Apply category overrides to transaction records")
    parser.add_argument(
        "--offline",
        metavar="PATH",
        help="Read transactions from a CSV export instead of the live store",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=12,
        help="Trailing months to scan when reading live (default: 12)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    overrides, aliases = get_override_context()

    db = create_transactions_db()
    if args.offline:
        df = pd.read_csv(args.offline)
    else:
        df = _load_live_transactions(db, args.months)

    to_update, already_correct, blacklisted = find_mismatches(df, overrides, aliases=aliases)
    summary = build_summary(to_update, already_correct, blacklisted)

    if args.dry_run:
        summary["dry_run"] = True
        json.dump(summary, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    apply_updates(to_update, db)
    summary["dry_run"] = False
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
