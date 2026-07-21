"""Query DynamoDB transactions by month and aggregate spending."""

import logging
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import boto3
from boto3.dynamodb.conditions import Key

from src.finance.aws_region import get_aws_region
from src.finance.spending_summary_base import SpendingSummaryBase
from src.finance.user_mapping import get_forwarded_to_addresses

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

    from src.finance.protocols import TransactionItem

logger = logging.getLogger(__name__)

SPENDING_TYPES = {"purchase", "withdrawal", "preauth", "e-transfer"}
DEPOSIT_TYPES = {"deposit"}


class SpendingSummary(SpendingSummaryBase):
    """Query and aggregate monthly transaction data from DynamoDB."""

    def __init__(self, dyn_resource: "DynamoDBServiceResource | None" = None):
        if dyn_resource is None:
            dyn_resource = boto3.resource("dynamodb", region_name=get_aws_region())
        self.table: Table = dyn_resource.Table("Transactions")

    def _query_partition(
        self,
        addr: str,
        prefix: str,
        projection: str | None = None,
        expression_names: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Query a single ForwardedTo partition for a given sort-key prefix.

        Args:
            addr: ForwardedTo partition key value.
            prefix: DateFileName begins_with prefix (e.g. "2026.02").
            projection: Optional ProjectionExpression to limit returned
                attributes (reduces DynamoDB read bandwidth).
            expression_names: Optional ExpressionAttributeNames for reserved
                words in the projection (e.g. {"#n": "Name"}).
        """
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("ForwardedTo").eq(addr) & Key("DateFileName").begins_with(prefix),
        }
        if projection:
            kwargs["ProjectionExpression"] = projection
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    def query_month(
        self,
        year_month: str,
        projection: str | None = None,
        expression_names: dict[str, str] | None = None,
    ) -> "list[TransactionItem]":
        """Query all transactions for a given YYYY-MM month across all partitions.

        Uses begins_with on the DateFileName sort key (stored as YYYY.MM.DD_...).
        Queries partitions concurrently when there are multiple addresses.

        Args:
            year_month: Month in YYYY-MM format.
            projection: Optional ProjectionExpression to limit returned
                attributes.
            expression_names: Optional ExpressionAttributeNames for reserved
                words in the projection.
        """
        prefix = year_month.replace("-", ".")
        addresses = get_forwarded_to_addresses()

        # Sequential partition queries — query_month is already called from a
        # thread pool worker (via run_sync), so spawning a nested thread pool
        # creates contention without meaningful speedup for 2 partitions.
        items: list[dict[str, Any]] = []
        for addr in addresses:
            items.extend(self._query_partition(addr, prefix, projection, expression_names))
        # boto3 boundary: month rows in their stored shape.
        return cast("list[TransactionItem]", items)

    # aggregate, get_summary, get_summary_with_comparison inherited from SpendingSummaryBase


# ---------------------------------------------------------------------------
# SMS formatting
# ---------------------------------------------------------------------------

CATEGORY_EMOJI = {
    "groceries": "\U0001f6d2",
    "restaurant/dining": "\U0001f37d\ufe0f",
    "gasoline": "\u26fd",
    "rent": "\U0001f3e0",
    "subscriptions": "\U0001f4b3",
    "entertainment": "\U0001f3ac",
    "technology": "\U0001f4bb",
    "utilities": "\U0001f4a1",
    "travel": "\u2708\ufe0f",
    "clothing": "\U0001f455",
    "health care": "\U0001f3e5",
    "insurance": "\U0001f6e1\ufe0f",
    "education": "\U0001f393",
    "automotive maintenance": "\U0001f527",
    "sports and recreation": "\U0001f3c3",
}


def _month_label(year_month: str) -> str:
    """Convert '2026-01' to 'January 2026'."""
    parts = year_month.split("-")
    d = date(int(parts[0]), int(parts[1]), 1)
    return d.strftime("%B %Y")


def _fmt_amount(amount: float | Decimal) -> str:
    return f"${float(amount):,.2f}"


def format_sms(data: dict[str, Any]) -> str:
    """Build a short SMS message (~250 chars) from summary data."""
    current = data["current"]
    label = _month_label(current["year_month"])
    total = current["total_spending"]
    total_count = current["spending_count"] + current["deposit_count"]
    delta_amount = data["delta_amount"]
    arrow = "\u2191" if delta_amount >= 0 else "\u2193"

    lines = [
        f"\U0001f4ca {label} Summary \U0001f4ca",
        f"\U0001f4b0 Total: {_fmt_amount(total)} ({arrow}{_fmt_amount(abs(delta_amount))})",
        f"\U0001f4e6 {total_count} transactions",
        "",
        "Top categories:",
    ]

    for cat_name, info in current["top_categories"]:
        emoji = CATEGORY_EMOJI.get(cat_name, "\U0001f4c2")
        lines.append(f"{emoji} {cat_name.title()}: {_fmt_amount(info['amount'])}")

    return "\n".join(lines)
