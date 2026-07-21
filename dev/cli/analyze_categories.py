"""Analyze transaction categories from a DynamoDB export CSV.

Reads the transactions CSV produced by download_transaction_table.py,
aggregates company+category data, and outputs structured JSON to stdout
for Claude to review and populate category_overrides.json.
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Repo layout: dev/cli/<this file> -> repo root is three parents up. Config
# lives under src/finance/config (renamed from the old src/emails/config).
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "finance" / "config"


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze transaction categories from CSV export")
    parser.add_argument("csv_path", type=Path, help="Path to the transactions CSV file")
    parser.add_argument("--months", type=int, default=3, help="Number of months to analyze (default: 3)")
    return parser.parse_args()


def parse_date(date_str: str) -> datetime | None:
    """Parse date string from CSV. Format: 'MM/DD/YYYY HH:MM' (PDT/PST already stripped)."""
    if not date_str or not isinstance(date_str, str):
        return None
    cleaned = date_str.strip().replace(" PDT", "").replace(" PST", "")
    try:
        return datetime.strptime(cleaned, "%m/%d/%Y %H:%M")
    except ValueError:
        return None


def load_csv(csv_path: Path) -> list[dict]:
    """Load CSV into a list of dicts without requiring pandas."""
    import csv

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_existing_overrides() -> dict:
    """Load existing category overrides from config."""
    overrides_path = CONFIG_DIR / "category_overrides.json"
    try:
        with open(overrides_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def analyze(rows: list[dict], months: int) -> dict:
    """Analyze transactions and return structured JSON summary."""
    now = datetime.now()
    cutoff = now - timedelta(days=months * 30)

    # Filter by date window
    filtered = []
    for row in rows:
        dt = parse_date(row.get("Date", ""))
        if dt and dt >= cutoff:
            filtered.append(row)

    logger.info(f"Filtered to {len(filtered)} transactions in the last {months} months (from {len(rows)} total)")

    # Group by company (case-insensitive), aggregate category counts
    company_data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in filtered:
        company = (row.get("Company") or "").strip()
        category = (row.get("Category") or "").strip()
        if company and category:
            company_key = company.upper()
            company_data[company_key][category] += 1

    # Build output
    companies = []
    for company, categories in company_data.items():
        total = sum(categories.values())
        dominant = max(categories, key=categories.get)
        companies.append(
            {
                "company": company,
                "categories": dict(categories),
                "total_count": total,
                "is_inconsistent": len(categories) >= 2,
                "is_miscellaneous": dominant == "Miscellaneous",
            }
        )

    # Sort by total_count descending
    companies.sort(key=lambda c: c["total_count"], reverse=True)

    existing_overrides = load_existing_overrides()

    return {
        "analysis_window": {
            "from": cutoff.strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
            "months": months,
        },
        "total_transactions": len(filtered),
        "unique_companies": len(companies),
        "companies": companies,
        "existing_overrides": existing_overrides,
    }


def main():
    args = parse_args()

    if not args.csv_path.exists():
        logger.error(f"CSV file not found: {args.csv_path}")
        sys.exit(1)

    rows = load_csv(args.csv_path)
    logger.info(f"Loaded {len(rows)} rows from {args.csv_path}")

    result = analyze(rows, args.months)

    # Output JSON to stdout (logging goes to stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
