"""Full-data backup export: zip packing.

``build_backup_zip`` produces a single ``.zip`` containing ``manifest.json``,
``transactions.csv`` (backup flavor from
:func:`src.api.routers.search._generate_csv`), ``config/*.json`` blobs for
categories, overrides, merchant aliases, and budgets, and an optional
``parse_failures.json`` dead-letter quarantine dump.

The MANIFEST_* / TRANSACTIONS_FILENAME format constants are shared with the
import side and are imported from :mod:`src.finance.backup_import`.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from src.finance.backup_import import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    TRANSACTIONS_FILENAME,
)
from src.finance.staging_store import now_iso


def build_backup_zip(
    transactions: list[dict[str, Any]],
    categories: list[str] | None,
    overrides: dict[str, Any] | None,
    merchant_aliases: dict[str, str] | None,
    budgets: dict[str, Any] | None,
    *,
    storage_backend: str,
    parse_failures: list[dict[str, Any]] | None = None,
) -> bytes:
    """Produce the backup zip payload as bytes.

    ``transactions`` is a list of PascalCase transaction items in the shape
    returned by ``row_to_item``/DynamoDB. Config blobs are written verbatim.
    """
    # Lazy import: top-leveling this would create an api↔finance circular
    # import (search imports finance services). The layering inversion is
    # intentional-for-now.
    from src.api.routers.search import _generate_csv as generate_csv

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # manifest
        manifest = {
            "version": MANIFEST_VERSION,
            "exported_at": now_iso(),
            "storage_backend": storage_backend,
            "counts": {
                "transactions": len(transactions),
                "categories": len(categories) if categories else 0,
                "overrides": len(overrides) if overrides else 0,
                "merchant_aliases": len(merchant_aliases) if merchant_aliases else 0,
                "budget_years": len(budgets) if budgets else 0,
                "parse_failures": len(parse_failures) if parse_failures else 0,
            },
        }
        zf.writestr(MANIFEST_FILENAME, json.dumps(manifest, indent=2))

        # transactions.csv
        csv_buf = io.StringIO()
        for chunk in generate_csv(transactions, flavor="backup"):
            csv_buf.write(chunk)
        zf.writestr(TRANSACTIONS_FILENAME, csv_buf.getvalue())

        # config/*.json — only write blobs that exist
        if categories is not None:
            zf.writestr("config/categories.json", json.dumps(categories, indent=2))
        if overrides is not None:
            zf.writestr("config/overrides.json", json.dumps(overrides, indent=2, sort_keys=True))
        if merchant_aliases is not None:
            zf.writestr(
                "config/merchant_aliases.json",
                json.dumps(merchant_aliases, indent=2, sort_keys=True),
            )
        if budgets is not None:
            zf.writestr("config/budgets.json", json.dumps(budgets, indent=2, default=str))

        # parse_failures.json — the dead-letter quarantine rows, including the
        # original email body (the one place bodies travel). Import is deferred:
        # the preview/commit path ignores this file (see _parse_zip / _apply_config).
        if parse_failures is not None:
            zf.writestr("parse_failures.json", json.dumps(parse_failures, indent=2, default=str))

    return buf.getvalue()
