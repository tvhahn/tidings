# src/finance/parsers/rbc_parser.py

import logging
import re
from typing import Any

from src.finance.config_loader import get_card_name_mappings
from src.finance.parser_base import AMOUNT_PATTERN, TransactionParser, merge_details, parse_amount
from src.finance.parsers.etransfer_parser import parse_e_transfer

logger = logging.getLogger(__name__)


class RBCParser(TransactionParser):
    def parse_purchase(self, email_body_text: str) -> dict[str, Any]:
        logger.debug("Starting to parse purchase.")
        amount_pattern = rf"purchase of \$({AMOUNT_PATTERN})"
        company_pattern = r"towards (.+?)\."
        amount_match = re.search(amount_pattern, email_body_text)
        company_match = re.search(company_pattern, email_body_text)

        if amount_match:
            logger.debug("Amount found: %s", amount_match.group(1))
        if company_match:
            logger.debug("Company found: %s", company_match.group(1))

        amount = amount_match.group(1) if amount_match else None
        company = company_match.group(1) if company_match else None
        name = None
        for fragment, mapped_name in get_card_name_mappings().get("RBC", {}).items():
            if fragment in email_body_text:
                name = mapped_name
                break

        transaction = {
            "name": name,
            "amount": parse_amount(amount),
            "company": company,
            "transaction_type": "purchase",
        }

        logger.info("Parsed purchase transaction: %s", transaction)
        return transaction

    def parse_withdrawal(self, email_body_text: str) -> dict[str, Any]:
        logger.debug("Starting to parse withdrawal.")
        amount_pattern = rf"withdrawal of \$({AMOUNT_PATTERN})"
        amount_match = re.search(amount_pattern, email_body_text)
        amount = amount_match.group(1) if amount_match else None

        if amount_match:
            logger.debug("Amount found: %s", amount_match.group(1))

        transaction = {
            "name": None,
            "amount": parse_amount(amount),
            "company": None,
            "transaction_type": "withdrawal",
        }
        logger.info("Parsed withdrawal transaction: %s", transaction)
        return transaction

    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        if "purchase of" in email_body_text:
            parsed_data = self.parse_purchase(email_body_text)
        elif "withdrawal of" in email_body_text:
            parsed_data = self.parse_withdrawal(email_body_text)
        elif "e-Transfer" in email_body_text and "successfully deposited" in email_body_text:
            parsed_data = parse_e_transfer(email_body_text)
        else:
            parsed_data = None

        email_details["institution"] = "RBC"
        return merge_details(email_details, parsed_data)
