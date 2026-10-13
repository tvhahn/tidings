"""Mark repeated bank alerts already in storage as duplicates (issue #86 backfill).

Ingestion now stores a re-sent or twice-delivered alert Ignored with
``DuplicateOf`` naming the original (see ``src/finance/duplicate_alerts.py``).
This replays the same rules over existing history, oldest first, so copies
stored before the fix get the same treatment. Nothing is deleted: a marked row
is set Ignored and gains ``DuplicateOf``, and the restore control brings it
back if it was a genuine second purchase.

Dry run by default — prints every row it would mark and the row it repeats.
Pass ``--apply`` to write. Safe to rerun: rows already carrying DuplicateOf are
skipped, so a second run reports nothing new.

Usage:
    uv run dev/cli/mark_duplicate_alerts.py
    uv run dev/cli/mark_duplicate_alerts.py --apply
"""

import argparse
import bisect
import logging
from collections import defaultdict
from dataclasses import replace
from typing import Any

from src.finance.duplicate_alerts import AlertRow, alert_row, find_duplicate_marks, window_bounds
from src.finance.storage import create_transactions_db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def plan_marks(items: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, str]]:
    """Replay duplicate detection over history.

    Returns ``(item, original DateFileName, rule)`` for each row to mark, where
    ``rule`` is ``"same email"`` (shared TransactionHash) or ``"re-send"``.
    """
    partitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        partitions[item["ForwardedTo"]].append(item)

    planned: list[tuple[dict[str, Any], str, str]] = []
    for partition in partitions.values():
        partition.sort(key=lambda item: item["DateFileName"])
        keys: list[str] = []
        rows: list[AlertRow] = []
        for item in partition:
            row = alert_row(item)
            keys.append(row.date_file_name)
            rows.append(row)
            bounds = window_bounds(row.date_file_name)
            if row.duplicate_of is not None or bounds is None:
                continue
            start = bisect.bisect_left(keys, bounds[0])
            marks = find_duplicate_marks(row.date_file_name, rows[start:])
            original = marks.get(row.date_file_name)
            if original is None:
                continue
            same_email = any(
                r.date_file_name == original and r.transaction_hash and r.transaction_hash == row.transaction_hash
                for r in rows[start:]
            )
            planned.append((item, original, "same email" if same_email else "re-send"))
            # Later rows must see this one as already marked, as live ingestion would.
            rows[-1] = replace(row, duplicate_of=original)
    return planned


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the marks (default: dry run)")
    args = parser.parse_args()

    db = create_transactions_db()
    items = [dict(item) for item in db.scan_all_transactions()]
    planned = plan_marks(items)

    for item, original, rule in planned:
        state = "already ignored" if item.get("Ignored") else "will be ignored"
        print(
            f"{item['DateFileName'][:16]}  {item.get('Institution') or '-':<8} "
            f"{item.get('Company') or '-':<32.32} {item.get('Amount') or '':>10}  "
            f"{rule:<10}  repeats {original[:16]}  ({state})"
        )
    newly_hidden = sum(1 for item, _, _ in planned if not item.get("Ignored"))
    print(f"\n{len(planned)} repeated alert(s); {newly_hidden} counted in totals today.")

    if not args.apply:
        print("Dry run — nothing written. Rerun with --apply to mark them.")
        return
    for item, original, _ in planned:
        db.mark_duplicate_alert(item["ForwardedTo"], item["DateFileName"], original)
    print(f"Marked {len(planned)} row(s).")


if __name__ == "__main__":
    main()
