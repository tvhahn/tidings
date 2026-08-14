"""User mapping utilities — load and query ForwardedTo → UserId cache."""

import csv
import logging
from pathlib import Path

user_id_cache: dict[str, str] = {}

__all__ = [
    "LOCAL_FORWARDED_TO_SUFFIX",
    "get_forwarded_to_addresses",
    "get_user_id",
    "load_user_mappings",
    "local_forwarded_to",
    "user_id_cache",
]

logger = logging.getLogger(__name__)

_DEFAULT_MAPPINGS = Path(__file__).resolve().parent / "user_mappings.csv"
_PERSONAL_MAPPINGS = Path(__file__).resolve().parents[2] / "data" / "config" / "user_mappings.csv"

# Locally-originated rows (manual adds, plain-CSV imports) carry no forwarding
# address, so they live in a synthetic `{user_id}@local` partition instead of
# an email one. Writers derive it via `local_forwarded_to()`; readers pick it
# up through `get_forwarded_to_addresses()`.
LOCAL_FORWARDED_TO_SUFFIX = "@local"


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


def local_forwarded_to() -> str:
    """Return the synthetic ForwardedTo partition for locally-entered rows.

    Manual adds and plain-CSV imports have no forwarding address; both key off
    this value so they dedup against each other. Kept here as the single
    derivation so writers and readers cannot drift apart.
    """
    from src.finance.app_config import get_config

    return f"{get_config().get('user_id', 'default')}{LOCAL_FORWARDED_TO_SUFFIX}"


def get_forwarded_to_addresses() -> list[str]:
    """Return every ForwardedTo partition belonging to this user.

    The mapped email partitions from user_mappings.csv, plus the synthetic
    `{user_id}@local` partition holding manually-added and CSV-imported rows.
    The local partition is appended last so callers that treat the first entry
    as the primary write target (e.g. statement ingestion) keep their mapped
    address. Without it, locally-entered transactions are written to a
    partition no read path enumerates and never surface in the UI.
    """
    if not user_id_cache:
        load_user_mappings()
    addresses = list(user_id_cache.keys())
    local = local_forwarded_to()
    if local not in user_id_cache:
        addresses.append(local)
    return addresses
