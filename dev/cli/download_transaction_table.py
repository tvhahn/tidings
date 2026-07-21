"""Download the full Transactions table from DynamoDB to a CSV export.

DynamoDB-backend only. This is the backup half of the backup/rollback pair
used by the /fix-categories workflow (its partner is
restore_categories_from_csv.py). It scans the live DynamoDB table and writes a
flat CSV snapshot; it has no SQLite equivalent and does nothing useful on the
self-hosted SQLite backend.

Region resolves through src.finance.aws_region.get_aws_region (AWS_REGION or
AWS_DEFAULT_REGION, defaulting to us-west-2). The table name comes from the
TRANSACTIONS_TABLE env var (default "Transactions").
"""

import argparse
import csv
import logging
import os
from decimal import Decimal
from pathlib import Path

import boto3
import pandas as pd

from src.finance.aws_region import get_aws_region

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def create_arg_parser():
    parser = argparse.ArgumentParser(description="Arguments for downloading emails from S3 bucket")

    parser.add_argument("-p", "--proj_dir", type=str, help="Location of project folder")

    parser.add_argument(
        "--path_data_dir",
        type=str,
        help="Location of the data folder, containing the raw, interim, and processed folders",
    )

    parser.add_argument(
        "--save_dir_name",
        type=str,
        default="transaction_db_rough",
        help="Name of the folder to save the transaction csv file to",
    )

    return parser.parse_args()


def set_directories(proj_dir: str | None = None, path_data_dir: str | None = None) -> tuple[Path, Path]:
    proj_dir = Path(proj_dir) if proj_dir else Path().cwd()
    path_data_dir = Path(path_data_dir) if path_data_dir else proj_dir / "data"

    return proj_dir, path_data_dir


def download_transactions_table(save_dir: Path):
    # Initialize the DynamoDB resource
    table_name = os.environ.get("TRANSACTIONS_TABLE", "Transactions")
    dynamo_resource = boto3.resource("dynamodb", region_name=get_aws_region())
    table = dynamo_resource.Table(table_name)

    # Scan the table to get all items
    response = table.scan()
    data = response["Items"]

    # Continue scanning if there are more items
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        data.extend(response["Items"])

    logger.info(f"Retrieved {len(data)} items from the {table_name} table.")

    # Convert data to a pandas DataFrame
    df = pd.DataFrame(data)

    # Convert Decimal objects to float
    for column in df.columns:
        if df[column].dtype == object and any(isinstance(val, Decimal) for val in df[column]):
            df[column] = df[column].apply(lambda x: float(x) if isinstance(x, Decimal) else x)

    # Remove PDT from Date column
    df["Date"] = df["Date"].str.replace(" PDT", "")

    # Arrange columns in a stable order
    columns = [
        "ForwardedTo",
        "DateFileName",
        "FileName",
        "Date",
        "UserId",
        "FromName",
        "FromEmail",
        "ToName",
        "ToEmail",
        "Institution",
        "Subject",
        "Body",
        "Name",
        "Amount",
        "Company",
        "TransactionType",
        "Category",
    ]
    # Include CategoryAudit if any rows have it
    if "CategoryAudit" in df.columns:
        columns.append("CategoryAudit")
    df = df[columns]

    # Save the DataFrame to a CSV file
    csv_file_path = save_dir / "transactions.csv"
    # Collapse newlines in Body to prevent LibreOffice row-splitting
    df["Body"] = df["Body"].str.replace(r"\r?\n", " ", regex=True)
    df.to_csv(csv_file_path, index=False, quoting=csv.QUOTE_ALL)
    logger.info(f"Data saved to {csv_file_path}")


if __name__ == "__main__":
    args = create_arg_parser()

    proj_dir, path_data_dir = set_directories(
        proj_dir=args.proj_dir,
        path_data_dir=args.path_data_dir,
    )

    save_dir_name = args.save_dir_name
    save_dir = path_data_dir / "raw" / save_dir_name
    save_dir.mkdir(parents=True, exist_ok=True)

    download_transactions_table(save_dir)
