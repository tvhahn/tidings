"""Restore transaction categories from a backup CSV to DynamoDB.

DynamoDB-backend only. This is the rollback half of the backup/rollback pair
used by the /fix-categories workflow (its partner is
download_transaction_table.py). It reads ForwardedTo, DateFileName, and
Category from a CSV and writes them back to DynamoDB, undoing any category
changes. It has no SQLite equivalent and targets the DynamoDB Transactions
table directly via TransactionsDB.

Region resolves through src.finance.aws_region.get_aws_region (AWS_REGION or
AWS_DEFAULT_REGION, defaulting to us-west-2). The DynamoDB table name is owned
by TransactionsDB ("Transactions").

Usage:
    uv run dev/cli/restore_categories_from_csv.py data/raw/transaction_db_rough/transactions.csv --dry-run
    uv run dev/cli/restore_categories_from_csv.py data/raw/transaction_db_rough/transactions.csv
"""

import argparse
import json
import logging
import sys
from collections import defaultdict

import boto3
import pandas as pd

from src.finance.aws_region import get_aws_region
from src.finance.transaction_db import TransactionsDB

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Restore categories from backup CSV to DynamoDB")
    parser.add_argument("csv_path", help="Path to backup transactions CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DynamoDB")
    args = parser.parse_args()

    df = pd.read_csv(args.csv_path)

    required_cols = ["ForwardedTo", "DateFileName", "Category"]
    for col in required_cols:
        if col not in df.columns:
            logger.error(f"Missing required column: {col}")
            sys.exit(1)

    # Filter to rows that have a category
    rows = df.dropna(subset=["Category"])
    total = len(rows)

    category_counts = defaultdict(int)
    for _, row in rows.iterrows():
        category_counts[str(row["Category"]).lower()] += 1

    summary = {
        "total_rows": total,
        "categories": dict(sorted(category_counts.items())),
        "dry_run": args.dry_run,
    }

    if args.dry_run:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    dynamo_resource = boto3.resource("dynamodb", region_name=get_aws_region())
    db = TransactionsDB(dynamo_resource)

    restored = 0
    for _, row in rows.iterrows():
        category = str(row["Category"])
        db.update_category(
            row["ForwardedTo"],
            row["DateFileName"],
            category,
            source="restore",
        )
        restored += 1
        if restored % 100 == 0:
            logger.info(f"Restored {restored}/{total} categories...")

    summary["restored"] = restored
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
