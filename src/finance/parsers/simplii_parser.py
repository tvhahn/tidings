import logging
from typing import Any

from src.finance.parser_base import TransactionParser, merge_details
from src.finance.parsers.etransfer_parser import parse_e_transfer

logger = logging.getLogger(__name__)


class SimpliiParser(TransactionParser):
    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        if "e-Transfer" in email_body_text and "successfully deposited" in email_body_text:
            parsed_data = parse_e_transfer(email_body_text)
        else:
            parsed_data = None

        email_details["institution"] = "Simplii"
        return merge_details(email_details, parsed_data)
