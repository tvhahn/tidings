"""Email parsing utilities — read, parse, and extract details from raw emails."""

import logging
import re
import traceback
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as default_policy
from email.utils import getaddresses, parseaddr
from html import unescape
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from src.finance.app_timezone import get_app_timezone
from src.finance.user_mapping import get_user_id, load_user_mappings, user_id_cache

__all__ = [
    "extract_basic_details",
    "extract_email_body",
    "extract_forwarded_message_details",
    "finalize_email_details",
    "init_parse_email",
    "read_email_from_file",
]

logger = logging.getLogger(__name__)


def _resolve_forwarded_to(parsed_email: EmailMessage) -> str | None:
    """Pick one clean address from possibly-multi-address forwarding headers.

    Gmail joins destinations into a single comma-separated ``X-Forwarded-To``
    when multiple filter rules fire on the same message. Storing that compound
    string as the DynamoDB partition key makes the row invisible to
    exact-match queries, so we split it and prefer an address that's a known
    key in ``user_mappings.csv``.
    """
    candidates: list[str] = []
    for header in ("X-Forwarded-To", "To"):
        raw = parsed_email.get(header)
        if not raw:
            continue
        for _name, addr in getaddresses([raw]):
            if addr and addr not in candidates:
                candidates.append(addr)

    if not candidates:
        return None

    for addr in candidates:
        if addr in user_id_cache:
            return addr

    fallback = candidates[0]
    # Only warn when the fallback is genuinely a choice between multiple
    # candidates — the single-candidate case is routine (e.g. the shipped
    # default CSV ships with demo addresses only).
    if len(candidates) > 1:
        logger.warning(
            "forwarded_to fallback: no candidate matched user_mappings.csv (candidates=%s, using=%s)",
            candidates,
            fallback,
        )
    return fallback


def read_email_from_file(path: str | Path) -> bytes:
    try:
        raw_email_path = Path(path)
        with raw_email_path.open("rb") as file:
            return file.read()
    except Exception as e:
        logger.exception("Failed to read email file %s", path)
        raise OSError(f"Failed to read email file {path}: {e!s}\n{traceback.format_exc()}") from e


def init_parse_email(raw_email: bytes) -> EmailMessage:
    """
    Parses raw email bytes into a structured email object.

    Parameters:
    raw_email (bytes): Raw email data as bytes.

    Returns:
    EmailMessage: The parsed email object.

    Raises:
    ValueError: If the email data cannot be parsed.
    """
    try:
        logger.info("Parsing email content.")
        parsed_email = BytesParser(policy=default_policy).parsebytes(raw_email)
        logger.info("Email content parsed successfully.")
        return parsed_email
    except Exception as e:
        logger.exception("Failed to parse email")
        raise ValueError(f"Failed to parse email: {e!s}\n{traceback.format_exc()}") from e


def extract_email_body(parsed_email: EmailMessage) -> str:
    """
    Extracts the body from a parsed email object, handling both plain text and HTML contents.

    Parameters:
    parsed_email (EmailMessage): The parsed email object.

    Returns:
    str: The extracted body text of the email, with HTML entities decoded.
    """

    def _decode(message: EmailMessage) -> str:
        # get_payload(decode=True) can return None or a non-bytes payload; guard both.
        payload = message.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return ""
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    body = ""
    try:
        if parsed_email.is_multipart():
            for part in parsed_email.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get("Content-Disposition"))

                if ctype == "text/plain" and "attachment" not in cdispo:
                    body = _decode(part)
                    body = unescape(body)
                    logger.debug("Plain text part found and processed.")
                    break
                if ctype == "text/html" and "attachment" not in cdispo:
                    html_content = _decode(part)
                    soup = BeautifulSoup(html_content, "html.parser")
                    # get_text() drops <br>, so convert them to newlines first.
                    for br in soup.find_all("br"):
                        br.replace_with("\n")
                    body = soup.get_text()
                    body = unescape(body)
                    logger.debug("HTML part found and processed.")
                    break
        else:
            body = _decode(parsed_email)
            if "text/html" in parsed_email.get_content_type():
                soup = BeautifulSoup(body, "html.parser")
                # get_text() drops <br>, so convert them to newlines first.
                for br in soup.find_all("br"):
                    br.replace_with("\n")
                body = soup.get_text()
                body = unescape(body)
                logger.debug("Single-part HTML content processed.")
    except Exception:
        logger.exception("Failed to extract email body")
        body = "An error occurred while processing the email content."

    return body


def extract_basic_details(parsed_email: EmailMessage) -> dict[str, Any]:
    """
    Extracts basic details from a parsed email object, including sender, recipient, subject, and date.

    Parameters:
    parsed_email (EmailMessage): The parsed email object.

    Returns:
    dict: A dictionary containing the basic details of the email.
    """

    # Ensure user mappings are loaded before proceeding
    if not user_id_cache:
        load_user_mappings()

    forwarded_to = _resolve_forwarded_to(parsed_email)

    email_details = {
        "from_name": parseaddr(parsed_email.get("From") or "")[0],
        "from_email": parseaddr(parsed_email.get("From") or "")[1],
        "to_name": parseaddr(parsed_email.get("To") or "")[0],
        "to_email": parseaddr(parsed_email.get("To") or "")[1],
        "forwarded_to": forwarded_to,
        "subject": parsed_email.get("Subject"),
        "date": parsed_email.get("Date"),
        "body": "",
        "user_id": get_user_id(forwarded_to) if forwarded_to else None,
    }

    try:
        if email_details["date"]:
            # Parse the date and automatically account for timezone offsets provided in the string
            parsed_date = parse_date(email_details["date"])

            # Convert to the configured app timezone, respecting DST changes
            local_time = parsed_date.astimezone(get_app_timezone())
            email_details["date"] = local_time.strftime("%m/%d/%Y %H:%M %Z")
    except ValueError as e:
        logger.warning("Date parsing failed for %s: %s\n%s", email_details["date"], e, traceback.format_exc())
        email_details["date"] = None

    return email_details


def extract_forwarded_message_details(body: str) -> dict[str, Any]:
    """
    Extracts details from the forwarded section of an email body, if present, and converts dates to PST.

    Parameters:
    body (str): The body text of the email.

    Returns:
    dict: A dictionary containing details extracted from the forwarded message.
    """
    forwarded_details = {}
    # Identify the start of a forwarded message
    forward_index = body.find("---------- Forwarded message ---------")
    if forward_index != -1:
        logger.debug("Forwarded message section identified.")
        patterns = {
            "from_name": r"From: (.+?) <",
            "from_email": r"From: .+? <(.+?)>",
            "to_email": r"To: <(.+?)>",
            "to_name": "",  # Assuming no name information for 'to'
            "date": r"Date: (.+)",
            "subject": r"Subject: (.+)",
        }
        # Process each pattern and extract information
        for key, pattern in patterns.items():
            if key != "to_name":  # Skip 'to_name' as there's no pattern for it
                match = re.search(pattern, body[forward_index:])
                if match:
                    if key == "date":
                        date_str = match.group(1).strip()
                        try:
                            parsed_date = parse_date(date_str)
                            if parsed_date.tzinfo is None:
                                # Assume naive dates are in the configured app timezone.
                                parsed_date = parsed_date.replace(tzinfo=get_app_timezone())
                            # Format in the parsed timezone without converting.
                            forwarded_details[key] = parsed_date.strftime("%m/%d/%Y %H:%M %Z")
                            logger.debug("Date parsed and converted for forwarded message: %s", forwarded_details[key])
                        except ValueError:
                            logger.exception("Error parsing forwarded date: %s", date_str)
                            forwarded_details[key] = None
                    else:
                        forwarded_details[key] = match.group(1).strip()
                        logger.debug("Extracted %s: %s", key, forwarded_details[key])
    else:
        logger.debug("No forwarded message section found in the email.")
    return forwarded_details


def finalize_email_details(
    basic_details: dict[str, Any], body: str, forwarded_details: dict[str, Any]
) -> dict[str, Any]:
    """
    Combines basic email details, body, and forwarded message details into a final dictionary.

    Parameters:
    basic_details (dict): The basic details extracted from the email headers.
    body (str): The extracted body text of the email.
    forwarded_details (dict): Details extracted from the forwarded message section, if any.

    Returns:
    dict: A comprehensive dictionary containing all email details.
    """
    basic_details["body"] = body

    basic_details.update(forwarded_details)

    return basic_details
