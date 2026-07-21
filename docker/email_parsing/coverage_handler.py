"""Lambda handler for the daily ingestion-coverage quiet check.

Triggered by EventBridge Scheduler once a day (see
``10_create_coverage_schedule.sh``; the function itself is created by
``9_establish_coverage_lambda.sh``). Builds the coverage service from the storage
factories and runs the quiet-transition check, which dispatches one calm
notification per institution that just went quiet via the unified
notification_service (SNS on the AWS path).

Uses the same image as the email-parser Lambda with ``coverage_handler.handler``
as the entry point (mirrors ``summary_handler.py``).

Note on throttling: each Lambda invocation is a fresh cold process, so the
in-memory per-institution 24h suppression in ``coverage_notifier`` is inert
here — it never persists between daily runs. That is by design (zero-ledger, no
persisted notification state): the transition-window condition
(``threshold < days_quiet ≤ threshold + 2``) alone bounds re-notification. On
the DynamoDB path there is no statement store, so ``statement_store=None`` is
correct and the capture rate is simply absent.
"""

import logging

from src.finance.coverage_notifier import check_quiet_notifications
from src.finance.coverage_service import CoverageService
from src.finance.storage import create_parse_failure_store, create_spending_summary

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    service = CoverageService(
        create_spending_summary(),
        create_parse_failure_store(),
        statement_store=None,  # SQLite-only ledger; not present on the DynamoDB path
    )
    notified = check_quiet_notifications(service)
    logger.info("Coverage quiet-check notified %d institution(s): %s", len(notified), ", ".join(notified))

    return {
        "statusCode": 200,
        "body": {"notified": notified, "count": len(notified)},
    }
