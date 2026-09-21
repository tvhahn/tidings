import logging
import os

import boto3

from src.finance import notification_service
from src.finance.ai_client import coerce_reasoning_effort, resolve_openai_categorization_settings
from src.finance.aws_region import get_aws_region
from src.finance.budget_service import BudgetService
from src.finance.email_pipeline import parse_email
from src.finance.openai_client import OpenAIClient
from src.finance.parse_failure_store import ParseFailureStore
from src.finance.parse_recovery import (
    downgrade_to_quarantined,
    mark_recovered,
    quarantine_db_invalid,
    recover_or_quarantine,
)
from src.finance.secrets import get_openai_api_key
from src.finance.transaction_context import TransactionContextEnricher
from src.finance.transaction_db import TransactionsDB

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3", region_name=get_aws_region())

dynamo_resource = boto3.resource("dynamodb", region_name=get_aws_region())
transactions_db = TransactionsDB(dynamo_resource)
budget_service = BudgetService(dynamo_resource, user_id=os.environ.get("USER_ID", "default"))
context_enricher = TransactionContextEnricher(transactions_db, budget_service)
# Lambda is always DynamoDB-backed; build the dead-letter store directly.
# The user_id is not optional here: the dashboard reads quarantined emails
# through `storage.create_parse_failure_store()`, which keys off
# `USER#<USER_ID>`. Left at the "default" fallback, every quarantined email
# lands in a partition no read path queries and "Needs review" stays empty.
parse_failure_store = ParseFailureStore(dyn_resource=dynamo_resource, user_id=os.environ.get("USER_ID", "default"))


def _categorization_settings() -> tuple[str, str | None]:
    """Resolve the categorization model + reasoning effort for this invocation.

    The Lambda ships no `data/config.json`, so the config-driven
    `get_ai_client()` path is unreachable here and environment variables are
    its override channel — set with
    `docker/email_parsing/11_set_function_env.sh`, which *merges* into
    the function's env map rather than replacing it. Missing or blank values
    fall back to the shared code defaults; an invalid effort is logged and
    dropped (never a crash — a typo in an env var must not stop ingestion).
    Both go through the same resolver as the config path so the two cannot
    drift.

    Read at invocation time, not import time, so an env-map update takes
    effect on the next invocation without waiting for a cold start.
    """
    model = (os.environ.get("CATEGORIZATION_MODEL") or "").strip() or None
    effort = coerce_reasoning_effort(os.environ.get("CATEGORIZATION_REASONING_EFFORT"))
    return resolve_openai_categorization_settings(model, effort)


def handler(event, context):

    try:
        api_key = get_openai_api_key()
    except RuntimeError as e:
        logger.error(str(e))
        return {"statusCode": 500, "body": "OpenAI credentials unavailable"}

    # Propagate the SSM-loaded key into the environment so app_config's
    # _has_openai_key() returns True and ai_categorization_enabled flips on.
    # Without this, categorize_transactions() short-circuits every row to
    # "Miscellaneous" even though the client below is fully functional.
    os.environ["OPENAI_API_KEY"] = api_key

    # This client also serves the relevance gate and the extraction-recovery
    # calls below, so the resolved effort applies to those too — intended.
    model, effort = _categorization_settings()
    logger.info("Categorization model=%s reasoning_effort=%s", model, effort)

    client = OpenAIClient(
        model=model,
        api_key=api_key,
        reasoning_effort=effort,
    )

    # Per-record isolation: one poison email must not abort the rest of the
    # batch. Failures are collected and re-raised at the end so S3's async
    # retry (and the on-failure DLQ, see 4_establish_lambda_func.sh) see the
    # invocation fail — already-written records are idempotent on retry via
    # the TransactionHash dedup.
    failed_keys = []
    for record in event["Records"]:
        bucket_name = record["s3"]["bucket"]["name"]
        object_key = record["s3"]["object"]["key"]

        logger.info(f"Received event for bucket: {bucket_name}, key: {object_key}")

        try:
            file_content = get_s3_file(bucket_name, object_key)
            if not file_content:
                # Empty object: permanent — retrying cannot help. Log loudly and move on.
                logger.error(f"Empty S3 object, skipping: s3://{bucket_name}/{object_key}")
                continue

            result = parse_email(file_content, object_key, client)
            logger.info(f"Parsed email details: {result}")

            # No transaction_type means no sub-parser extracted a transaction.
            # Hand it to the recovery gate BEFORE the DB round-trip (mirrors the
            # IMAP poller's skipped branch): relevant emails are captured for
            # review, irrelevant ones are dropped.
            recovered_failure_id = None
            if not result.get("transaction_type"):
                outcome = recover_or_quarantine(result, parse_failure_store, client)
                if outcome.status == "quarantined":
                    logger.info("Parse failed but captured for review (failure_id=%s)", outcome.failure_id)
                    continue
                if outcome.status == "recovered" and outcome.result is not None:
                    result = outcome.result
                    recovered_failure_id = outcome.failure_id
                else:
                    logger.info("No parser matched and email not relevant; skipping.")
                    continue

            # Pop BOTH provenance keys — neither may reach the DB as a literal field.
            extraction_audit = result.pop("_extraction_audit", None)
            category_audit = result.pop("_category_audit", None)
            date_file_name = transactions_db.add_transaction(
                result, category_audit=category_audit, extraction_audit=extraction_audit
            )
            if date_file_name is None:
                if recovered_failure_id is not None:
                    # Extraction recovered a transaction but the DB rejected it —
                    # downgrade the pre-marked "recovered" row rather than lose it.
                    logger.info("Recovered transaction failed DB validation; downgrading to quarantined.")
                    downgrade_to_quarantined(parse_failure_store, recovered_failure_id)
                else:
                    # Parsed fields present but the DB rejected them (e.g. a required
                    # field was missing) — capture for review rather than drop.
                    logger.info("Validation failure (missing required fields); capturing for review.")
                    quarantine_db_invalid(parse_failure_store, result, client)
            elif date_file_name is False:
                logger.info("Duplicate transaction detected. SMS not sent.")
            else:
                if recovered_failure_id is not None:
                    mark_recovered(parse_failure_store, recovered_failure_id, date_file_name)
                context = context_enricher.enrich(result)
                if context:
                    transactions_db.update_context(result["forwarded_to"], date_file_name, context)
                notification_service.send(result, context=context)
        except Exception:
            logger.exception(f"Record failed: s3://{bucket_name}/{object_key}")
            failed_keys.append(object_key)

    if failed_keys:
        raise RuntimeError(f"{len(failed_keys)} of {len(event['Records'])} record(s) failed: {failed_keys}")


def get_s3_file(bucket, key):
    # Raises on fetch errors (transient S3 issues must fail the record so the
    # event is retried, not silently logged-and-dropped). Returns the raw bytes.
    response = s3_client.get_object(Bucket=bucket, Key=key)
    logger.info(f"Successfully fetched file from S3: {key}, bucket: {bucket}")
    return response["Body"].read()
