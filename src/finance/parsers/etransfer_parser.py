# src/finance/parsers/etransfer_parser.py

import logging
import re
from typing import Any

from src.finance.parser_base import parse_amount

logger = logging.getLogger(__name__)


def parse_e_transfer(email_body_text: str) -> dict[str, Any]:
    logger.debug("Starting to parse e-Transfer.")

    name_pattern = r"Hi ([\w\s]+),"
    amount_pattern = r"\$([0-9,]+\.\d{2})\s*\(CAD\)"
    recipient_pattern = r"sent to (.*?) has been"
    message_pattern = r"Message:\s*(.*?)(?=\r?\n\r?\n)"
    reference_num_pattern = r"Reference Number: (\w+)"

    name_match = re.search(name_pattern, email_body_text)
    amount_match = re.search(amount_pattern, email_body_text)
    recipient_match = re.search(recipient_pattern, email_body_text)
    message_match = re.search(message_pattern, email_body_text)
    reference_num_match = re.search(reference_num_pattern, email_body_text)

    name = name_match.group(1).split()[0].capitalize() if name_match else None
    amount = amount_match.group(1).strip() if amount_match else None
    recipient = recipient_match.group(1).strip() if recipient_match else None
    message = message_match.group(1).strip() if message_match else None
    reference_num = reference_num_match.group(1).strip() if reference_num_match else None

    amount = parse_amount(amount)

    company_details = []
    if recipient:
        company_details.append(recipient)
    if message:
        company_details.append(message)
    if reference_num:
        company_details.append(reference_num)
    company_info = " | ".join(company_details)

    transaction_data = {
        "name": name,
        "amount": amount,
        "company": company_info,
        "transaction_type": "e-transfer",
    }
    logger.info("Parsed e-Transfer transaction: %s", transaction_data)
    return transaction_data
