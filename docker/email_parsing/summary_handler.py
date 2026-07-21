"""Lambda handler for monthly spending summary SMS.

Triggered by EventBridge Scheduler on the 8th of each month.
Queries the previous month's transactions, formats a summary, and dispatches
via the unified notification_service (defaults to SNS when SNS_TOPIC_ARN is set).
"""

import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from src.finance import notification_service
from src.finance.spending_summary import SpendingSummary, format_sms

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    prev_month = (date.today() - relativedelta(months=1)).strftime("%Y-%m")
    logger.info(f"Generating summary for {prev_month}")

    summary = SpendingSummary()
    data = summary.get_summary_with_comparison(prev_month)
    message = format_sms(data)

    logger.info(f"SMS message ({len(message)} chars):\n{message}")
    notification_service.send_raw(title="Monthly Spending Summary", body=message)

    return {
        "statusCode": 200,
        "body": {"month": prev_month, "message_length": len(message)},
    }
