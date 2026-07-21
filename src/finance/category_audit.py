"""CategoryAudit (v2) — build and normalize the audit dict stored on each row.

Schema v2 fields:

- `source` — one of `override`, `ai`, `ai_fallback`, `manual`, `manual_edit`,
  `manual_bulk`, `audit`, `statement_import`, `statement_enrich`.
- `tier` — only when `source == "override"`: `exact`/`normalized`/`alias`/`fuzzy`.
- `matched_rule`, `confidence` — only for `source == "override"`.
- `reviewed_at` — ISO-8601 with the app-timezone offset, e.g.
  `2026-02-15T13:38:22.621498-08:00`. Matches the local zone used by the
  `Date` column.
- `previous_category`, `previous_source` — set when an update overwrote a
  previously-set category.
- `model` — set when `source == "ai"`.
- `fallback_reason` — set when `source == "ai_fallback"`. Intentional:
  `disabled`, `no_client`. Provider/transport errors: `quota_exceeded`,
  `rate_limited`, `auth_error`, `api_error`, `codex_error`, `codex_timeout`.
  Soft model hiccups: `empty_completion`, `parse_error`.
- `schema_version` — always `2` for writes. Absent = legacy (v1).

`normalize_audit` is the read-side shim that maps legacy shapes (e.g.
`source="override_normalized"`) onto the v2 fields. Storage is never
rewritten — only API responses see the normalized form.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.finance.app_timezone import now_local

if TYPE_CHECKING:
    from decimal import Decimal

SCHEMA_VERSION = 2

# Audit sources that represent explicit user intent — a user set or confirmed
# the category. Manual categorization must survive statement enrichment.
MANUAL_SOURCES: tuple[str, ...] = ("manual", "manual_edit", "manual_bulk", "audit")

# Legacy `source` values created before tier became its own field.
_LEGACY_SOURCE_TO_TIER = {
    "override_normalized": "normalized",
    "override_alias": "alias",
    "override_fuzzy": "fuzzy",
}

_VALID_TIERS = {"exact", "normalized", "alias", "fuzzy"}


def now_local_iso() -> str:
    """ISO-8601 timestamp in the app-configured timezone, with offset."""
    return now_local().isoformat()


def build_audit(
    source: str,
    *,
    tier: str | None = None,
    matched_rule: str | None = None,
    confidence: float | Decimal | None = None,
    model: str | None = None,
    fallback_reason: str | None = None,
    previous_category: str | None = None,
    previous_source: str | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Construct a v2 CategoryAudit dict. Omits absent optional fields."""
    audit: dict[str, Any] = {
        "source": source,
        "reviewed_at": reviewed_at or now_local_iso(),
        "schema_version": SCHEMA_VERSION,
    }
    if tier is not None:
        audit["tier"] = tier
    if matched_rule is not None:
        audit["matched_rule"] = matched_rule
    if confidence is not None:
        audit["confidence"] = confidence
    if model is not None:
        audit["model"] = model
    if fallback_reason is not None:
        audit["fallback_reason"] = fallback_reason
    if previous_category is not None:
        audit["previous_category"] = previous_category
    if previous_source is not None:
        audit["previous_source"] = previous_source
    return audit


def build_extraction_audit(model: str | None) -> dict[str, Any]:
    """Construct an ExtractionAudit provenance dict for an AI-recovered row.

    Stamped on transactions recovered via the AI extraction fallback (the
    parse-failure-quarantine path). ``validated`` is always ``True`` here —
    the row only reaches storage after the verbatim-validation guardrails
    pass; a failed validation never produces a transaction.
    """
    return {
        "method": "ai_fallback",
        "model": model,
        "validated": True,
        "extracted_at": now_local_iso(),
        "schema_version": 1,
    }


def normalize_audit(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map any persisted audit shape onto the canonical v2 shape.

    - `source ∈ {override_normalized, override_alias, override_fuzzy}` collapses
      to `source="override"` with the corresponding `tier`.
    - A bare legacy `source="override"` without `tier` gets `tier="exact"`
      (the only tier that existed when the legacy shape was the only shape).
    - Unknown sources are passed through untouched.
    - Confidence is left in whatever numeric form was stored (Decimal from
      DynamoDB, float from SQLite) — callers coerce as needed.
    """
    if not raw:
        return raw

    out: dict[str, Any] = dict(raw)
    src = out.get("source")

    if src in _LEGACY_SOURCE_TO_TIER:
        out["source"] = "override"
        out.setdefault("tier", _LEGACY_SOURCE_TO_TIER[src])

    # Drop a bogus tier before the "bare override → exact" backfill so the
    # backfill still applies.
    if "tier" in out and out["tier"] not in _VALID_TIERS:
        out.pop("tier")

    if out.get("source") == "override" and "tier" not in out:
        out["tier"] = "exact"

    return out
