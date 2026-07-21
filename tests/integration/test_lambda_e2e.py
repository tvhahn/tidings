"""End-to-end AWS Lambda round-trip integration test.

Exercises the full AWS ingestion path with a fictitious test transaction:
uploads a `.eml` fixture to S3, invokes the email-parser Lambda with a synthetic
S3 event, then verifies the resulting DynamoDB record — parsed fields
(Company/Amount/Institution/Category) *and* ``TransactionContext`` enrichment
(category month total, merchant month count, budget target/pct). A temporary
budget target marked ``_e2e_test`` is created so the budget-enrichment fields
have something to resolve against; it is torn down afterwards, and it is only
ever deleted when the marker is present so a real budget is never touched.

The test is fully self-contained: it cleans stale records before running and
removes both the DynamoDB record and the temporary budget in fixture teardown,
so cleanup runs even when an assertion fails.

Required environment (test SKIPS cleanly if either is missing):
    E2E_EMAIL_BUCKET     S3 bucket the Lambda watches for inbound emails
    E2E_USER_ID          user id used to build the budget partition key

Optional environment (with defaults):
    E2E_LAMBDA_FUNCTION      Lambda function name         (default: email-parser)
    E2E_TRANSACTIONS_TABLE   DynamoDB transactions table  (default: Transactions)
    E2E_BUDGET_TABLE         DynamoDB budget table        (default: BudgetConfig)
    AWS_REGION               AWS region                   (default: us-west-2)

Example invocation (against a real, disposable AWS account):
    E2E_EMAIL_BUCKET=my-inbound-bucket E2E_USER_ID=demo-user \\
        uv run pytest tests/integration/test_lambda_e2e.py -m integration
"""

import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env gating — read (never construct clients) at import time so collection with
# no env skips cleanly instead of erroring.
# ---------------------------------------------------------------------------
E2E_EMAIL_BUCKET = os.environ.get("E2E_EMAIL_BUCKET")
E2E_USER_ID = os.environ.get("E2E_USER_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (E2E_EMAIL_BUCKET and E2E_USER_ID),
        reason="E2E_EMAIL_BUCKET and E2E_USER_ID must be set for the Lambda e2e test",
    ),
]

# Fixture path resolved relative to this test file (robust to CWD).
FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "e2e_test_email.eml"

# S3 key the fixture is uploaded under.
TEST_S3_KEY = "test-fixtures/e2e-test-email"

# Expected values baked into the fictitious fixture.
EXPECTED_COMPANY = "E2E TEST CAFE"
EXPECTED_AMOUNT = "1.23"
EXPECTED_INSTITUTION = "CIBC"
EXPECTED_CATEGORY = "restaurant/dining"

E2E_TEST_MARKER = "_e2e_test"


# ---------------------------------------------------------------------------
# Configuration helpers (evaluated lazily, inside fixtures/tests)
# ---------------------------------------------------------------------------
def _region() -> str:
    return os.environ.get("AWS_REGION", "us-west-2")


def _lambda_function_name() -> str:
    return os.environ.get("E2E_LAMBDA_FUNCTION", "email-parser")


def _transactions_table_name() -> str:
    return os.environ.get("E2E_TRANSACTIONS_TABLE", "Transactions")


def _budget_table_name() -> str:
    return os.environ.get("E2E_BUDGET_TABLE", "BudgetConfig")


def _budget_pk() -> str:
    return f"USER#{os.environ['E2E_USER_ID']}"


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------
def _find_transaction_keys(table, s3_key: str) -> list[tuple[str, str]]:
    """Scan for items whose FileName matches *s3_key*; return composite keys."""
    from boto3.dynamodb.conditions import Attr

    keys: list[tuple[str, str]] = []
    scan_kwargs = {
        "FilterExpression": Attr("FileName").eq(s3_key),
        "ProjectionExpression": "ForwardedTo, DateFileName",
    }
    response = table.scan(**scan_kwargs)
    keys.extend((item["ForwardedTo"], item["DateFileName"]) for item in response["Items"])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **scan_kwargs)
        keys.extend((item["ForwardedTo"], item["DateFileName"]) for item in response["Items"])
    return keys


def _find_transaction_details(table, s3_key: str) -> list[dict[str, Any]]:
    """Scan for items whose FileName matches *s3_key*; return the full items."""
    from boto3.dynamodb.conditions import Attr

    items: list[dict[str, Any]] = []
    scan_kwargs = {"FilterExpression": Attr("FileName").eq(s3_key)}
    response = table.scan(**scan_kwargs)
    items.extend(response["Items"])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **scan_kwargs)
        items.extend(response["Items"])
    return items


def _delete_transactions(table, s3_key: str) -> None:
    """Delete every DynamoDB item whose FileName matches *s3_key*."""
    for forwarded_to, date_file_name in _find_transaction_keys(table, s3_key):
        table.delete_item(Key={"ForwardedTo": forwarded_to, "DateFileName": date_file_name})
        logger.info("Deleted transaction ForwardedTo=%s DateFileName=%s", forwarded_to, date_file_name)


def _floats_to_decimals(obj: Any) -> Any:
    """Recursively convert float/int values to Decimal for DynamoDB."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimals(v) for v in obj]
    return obj


def _setup_test_budget(budget_table, year: int) -> tuple[float | None, bool]:
    """Create a temporary restaurant/dining budget target.

    Uses a ConditionExpression so a real budget is never overwritten. Returns
    ``(monthly_target, created)`` where ``created`` indicates whether this call
    put a marked test item (and is therefore responsible for cleaning it up).
    """
    from botocore.exceptions import ClientError

    test_budget = {
        "spending_ceiling": 5000,
        "categories": {
            "restaurant/dining": {
                "target": 6000,
                "input_mode": "annual",
                "monthly_amount": 500,
                "category_type": "variable",
            }
        },
        E2E_TEST_MARKER: True,
    }
    try:
        budget_table.put_item(
            Item={
                "PK": _budget_pk(),
                "SK": f"BUDGET#targets#{year}",
                "Data": _floats_to_decimals(test_budget),
                "Version": 1,
                "UpdatedAt": datetime.now(UTC).isoformat(),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        logger.info("Created temporary budget target for %d (restaurant/dining: $500/month)", year)
        return 500.0, True
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # A real budget already exists — read its target and leave it untouched.
        response = budget_table.get_item(Key={"PK": _budget_pk(), "SK": f"BUDGET#targets#{year}"})
        data = response.get("Item", {}).get("Data", {})
        cat = data.get("categories", {}).get("restaurant/dining", {})
        target = float(cat.get("monthly_amount", 0))
        logger.info("Real budget exists for %d — using existing target $%.0f/month", year, target)
        return (target if target > 0 else None), False


def _cleanup_test_budget(budget_table, year: int) -> None:
    """Delete the budget item ONLY if it carries the e2e test marker."""
    from botocore.exceptions import ClientError

    try:
        response = budget_table.get_item(Key={"PK": _budget_pk(), "SK": f"BUDGET#targets#{year}"})
        data = response.get("Item", {}).get("Data", {})
        if data.get(E2E_TEST_MARKER):
            budget_table.delete_item(Key={"PK": _budget_pk(), "SK": f"BUDGET#targets#{year}"})
            logger.info("Cleaned up temporary budget target for %d", year)
        else:
            logger.info("Budget item for %d is real data — skipping cleanup", year)
    except ClientError:
        logger.exception("Failed to clean up budget for %d", year)


# ---------------------------------------------------------------------------
# S3 + Lambda helpers
# ---------------------------------------------------------------------------
def _upload_test_fixture(s3_client) -> None:
    """Read the fixture, inject the current date, and upload it to S3."""
    template = FIXTURE_PATH.read_text()
    rfc2822_date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    body = template.replace("{{DATE_PLACEHOLDER}}", rfc2822_date)
    s3_client.put_object(Bucket=E2E_EMAIL_BUCKET, Key=TEST_S3_KEY, Body=body.encode("utf-8"))
    logger.info("Uploaded fixture to s3://%s/%s (Date: %s)", E2E_EMAIL_BUCKET, TEST_S3_KEY, rfc2822_date)


def _invoke_lambda(lambda_client, bucket_name: str, s3_key: str) -> dict[str, Any]:
    """Invoke the Lambda with a minimal synthetic S3 event."""
    event = {
        "Records": [
            {
                "eventVersion": "2.0",
                "eventSource": "aws:s3",
                "awsRegion": _region(),
                "eventName": "ObjectCreated:Put",
                "s3": {"bucket": {"name": bucket_name}, "object": {"key": s3_key}},
            }
        ]
    }
    response = lambda_client.invoke(
        FunctionName=_lambda_function_name(),
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )
    return {
        "StatusCode": response["StatusCode"],
        "Payload": json.loads(response["Payload"].read().decode("utf-8")),
    }


# ---------------------------------------------------------------------------
# Fixture — AWS resources + budget setup/teardown (cleanup guaranteed)
# ---------------------------------------------------------------------------
class _AwsContext:
    def __init__(self, s3_client, table, budget_table, lambda_client, budget_target):
        self.s3_client = s3_client
        self.table = table
        self.budget_table = budget_table
        self.lambda_client = lambda_client
        self.budget_target = budget_target


@pytest.fixture
def aws_context():
    """Provision AWS clients, purge stale records, set up a temporary budget.

    Teardown deletes the test DynamoDB record and the temporary budget marker —
    it runs whether the test passes or an assertion fails.
    """
    if not FIXTURE_PATH.exists():
        pytest.skip(f"fixture not found: {FIXTURE_PATH}")

    import boto3

    region = _region()
    s3_client = boto3.client("s3", region_name=region)
    dynamo = boto3.resource("dynamodb", region_name=region)
    table = dynamo.Table(_transactions_table_name())
    budget_table = dynamo.Table(_budget_table_name())
    lambda_client = boto3.client("lambda", region_name=region)

    year = datetime.now(UTC).year
    budget_created = False
    try:
        _delete_transactions(table, TEST_S3_KEY)  # clear stale records from prior runs
        budget_target, budget_created = _setup_test_budget(budget_table, year)
        yield _AwsContext(s3_client, table, budget_table, lambda_client, budget_target)
    finally:
        _delete_transactions(table, TEST_S3_KEY)
        if budget_created:
            _cleanup_test_budget(budget_table, year)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
def test_lambda_round_trip_creates_enriched_transaction(aws_context: _AwsContext) -> None:
    """Upload → invoke Lambda → verify parsed fields + TransactionContext."""
    # --- Act: upload the fixture and invoke the Lambda ---
    _upload_test_fixture(aws_context.s3_client)
    result = _invoke_lambda(aws_context.lambda_client, E2E_EMAIL_BUCKET, TEST_S3_KEY)
    assert result["StatusCode"] == 200, f"Lambda returned {result['StatusCode']}: {result['Payload']}"

    # --- Verify: the DynamoDB record was created ---
    items = _find_transaction_details(aws_context.table, TEST_S3_KEY)
    assert items, "no DynamoDB record found — transaction was not created"
    item = items[0]

    assert item.get("Company") == EXPECTED_COMPANY
    assert str(item.get("Amount")) == EXPECTED_AMOUNT
    assert item.get("Institution") == EXPECTED_INSTITUTION
    assert item.get("Category") == EXPECTED_CATEGORY

    # --- Verify: TransactionContext enrichment ---
    ctx = item.get("TransactionContext")
    assert ctx, "TransactionContext attribute missing from DynamoDB record"

    month_total = ctx.get("category_month_total")
    assert month_total is not None, "category_month_total missing"
    assert float(month_total) >= float(EXPECTED_AMOUNT), (
        f"category_month_total: got {month_total}, expected >= {EXPECTED_AMOUNT}"
    )

    month_count = ctx.get("merchant_month_count")
    assert month_count is not None, "merchant_month_count missing"
    assert int(month_count) >= 1, f"merchant_month_count: got {month_count}, expected >= 1"

    if aws_context.budget_target:
        assert ctx.get("category_budget_target") is not None, "category_budget_target missing"
        budget_pct = ctx.get("category_budget_pct")
        assert budget_pct is not None, "category_budget_pct missing"
        assert float(budget_pct) > 0, f"category_budget_pct: got {budget_pct}, expected > 0"
