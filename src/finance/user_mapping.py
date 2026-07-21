"""User mapping utilities — load and query ForwardedTo → UserId cache."""

import csv
import logging
from pathlib import Path

user_id_cache: dict[str, str] = {}

__all__ = [
    "get_forwarded_to_addresses",
    "get_user_id",
    "load_user_mappings",
    "user_id_cache",
]

logger = logging.getLogger(__name__)

_DEFAULT_MAPPINGS = Path(__file__).resolve().parent / "user_mappings.csv"
_PERSONAL_MAPPINGS = Path(__file__).resolve().parents[2] / "data" / "config" / "user_mappings.csv"


def load_user_mappings() -> None:
    """Loads user mappings from a CSV file into a dictionary.

    Checks data/config/user_mappings.csv first (personal, gitignored),
    falls back to src/finance/user_mappings.csv (tracked safe default).

    Mutates ``user_id_cache`` in place — rebinding would desynchronize any
    module that imported the reference via ``from … import user_id_cache``.
    """
    csv_file_path = _PERSONAL_MAPPINGS if _PERSONAL_MAPPINGS.exists() else _DEFAULT_MAPPINGS

    try:
        with open(csv_file_path) as infile:
            reader = csv.DictReader(infile)
            user_id_cache.clear()
            user_id_cache.update({row["ForwardedTo"]: row["UserId"] for row in reader})
        logger.info("User mappings loaded successfully.")
    except FileNotFoundError:
        logger.exception("CSV file %s not found.", csv_file_path)
    except Exception:
        logger.exception("Error loading user mappings from CSV")


def get_user_id(forwarded_to: str) -> str | None:
    """Retrieve UserId from the in-memory cache."""
    return user_id_cache.get(forwarded_to)


def get_forwarded_to_addresses() -> list[str]:
    """Return all ForwardedTo partition keys from user_mappings.csv."""
    if not user_id_cache:
        load_user_mappings()
    return list(user_id_cache.keys())
