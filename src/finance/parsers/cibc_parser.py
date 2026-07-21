import re
from typing import Any

from src.finance.parser_base import AMOUNT_PATTERN, TransactionParser, merge_details, parse_amount


class CIBCParser(TransactionParser):
    def parse_purchase(self, email_body_text: str) -> dict[str, Any] | None:
        pattern = rf"Dear\s+(\w+),.*?made a purchase.*?\$({AMOUNT_PATTERN}).*?at\s+(.+?)\s+You can sign"
        match = re.search(pattern, email_body_text, re.DOTALL)
        if match:
            name, amount, company = match.groups()
            return {
                "name": name,
                "amount": parse_amount(amount),
                "company": company.rstrip("."),
                "transaction_type": "purchase",
            }
        return None

    def parse_preauth_payment(self, email_body_text: str) -> dict[str, Any] | None:
        pattern = rf"Dear\s+(\w+),.*?preauthorized payment.*?\$({AMOUNT_PATTERN}).*?to\s+(.+?)\s+on"
        match = re.search(pattern, email_body_text, re.DOTALL)
        if match:
            name, amount, company = match.groups()
            return {
                "name": name,
                "amount": parse_amount(amount),
                "company": company,
                "transaction_type": "preauth",
            }
        return None

    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        if "made a purchase" in email_body_text:
            parsed_data = self.parse_purchase(email_body_text)
        elif "preauthorized payment" in email_body_text:
            parsed_data = self.parse_preauth_payment(email_body_text)
        else:
            parsed_data = None

        email_details["institution"] = "CIBC"
        return merge_details(email_details, parsed_data)
