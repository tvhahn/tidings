import re
from typing import Any

from src.finance.config_loader import get_card_name_mappings
from src.finance.parser_base import AMOUNT_PATTERN, TransactionParser, merge_details, parse_amount


class MBNAParser(TransactionParser):
    def parse_purchase(self, email_body_text: str) -> dict[str, Any]:
        amount_pattern = rf"A purchase of \$({AMOUNT_PATTERN})"
        company_pattern = r"from (.+?) was made"
        amount_match = re.search(amount_pattern, email_body_text)
        company_match = re.search(company_pattern, email_body_text)
        amount = amount_match.group(1) if amount_match else None
        company = company_match.group(1) if company_match else None
        name = None
        for fragment, mapped_name in get_card_name_mappings().get("MBNA", {}).items():
            if f"card ending in {fragment}" in email_body_text:
                name = mapped_name
                break
        return {
            "name": name,
            "amount": parse_amount(amount),
            "company": company,
            "transaction_type": "purchase",
        }

    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        if "purchase of" in email_body_text:
            parsed_data = self.parse_purchase(email_body_text)
        else:
            parsed_data = None

        email_details["institution"] = "MBNA"
        return merge_details(email_details, parsed_data)
