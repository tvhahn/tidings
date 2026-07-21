import logging
import re
from typing import Any

from src.finance.parser_base import AMOUNT_PATTERN, TransactionParser, merge_details, parse_amount

logger = logging.getLogger(__name__)


class PCFinancialParser(TransactionParser):
    def parse_purchase(self, email_body_text: str) -> dict[str, Any]:
        logger.debug("Starting to parse PC Financial purchase.")

        # Extract amount from "A purchase of $202.99 was made"
        amount_pattern = rf"purchase of \$({AMOUNT_PATTERN})"
        amount_match = re.search(amount_pattern, email_body_text)

        # Extract merchant from "Merchant: GROCERY MART #123"
        merchant_pattern = r"Merchant:\s*(.+?)(?:\n|$)"
        merchant_match = re.search(merchant_pattern, email_body_text)

        # Extract card holder name from "Hi [CARDHOLDER_NAME],"
        name_pattern = r"Hi\s+([^,]+),"
        name_match = re.search(name_pattern, email_body_text)

        # Extract card number ending from "card ending in 8804"
        card_pattern = r"card ending in (\d+)"
        card_match = re.search(card_pattern, email_body_text)

        if amount_match:
            logger.debug("Amount found: %s", amount_match.group(1))
        if merchant_match:
            logger.debug("Merchant found: %s", merchant_match.group(1))
        if name_match:
            logger.debug("Name found: %s", name_match.group(1))
        if card_match:
            logger.debug("Card ending found: %s", card_match.group(1))

        amount = amount_match.group(1) if amount_match else None
        company = merchant_match.group(1) if merchant_match else None
        name = name_match.group(1) if name_match else None

        transaction = {
            "name": name,
            "amount": parse_amount(amount),
            "company": company,
            "transaction_type": "purchase",
        }

        logger.info("Parsed PC Financial purchase transaction: %s", transaction)
        return transaction

    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        if "purchase of" in email_body_text and "PC ® Mastercard" in email_body_text:
            parsed_data = self.parse_purchase(email_body_text)
        else:
            parsed_data = None

        email_details["institution"] = "PC Financial"
        return merge_details(email_details, parsed_data)
