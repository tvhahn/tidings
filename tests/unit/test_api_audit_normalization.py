"""API-layer behavior for CategoryAudit v2.

Two seams:

1. ``_to_response`` runs every raw audit through ``normalize_audit`` so legacy
   shapes (e.g. ``source="override_normalized"``) surface as the canonical v2
   shape on the wire.
2. ``_is_attention`` keeps AI-fallback rows in the attention queue even
   though they now carry a (machine-stamped) audit.
"""

from __future__ import annotations

from src.api.serializers import is_attention as _is_attention
from src.api.serializers import to_transaction_response as _to_response
from tests.factories import make_transaction_item


def _make_item(**overrides: object) -> dict[str, object]:
    """Stored transaction item for the audit-normalization seams.

    Thin wrapper over the shared ``make_transaction_item`` factory; each test
    layers on the ``CategoryAudit`` (and attention flags) it exercises. The
    endpoints under test read only Category/CategoryAudit/Ignored/DeletedAt, so
    the factory's superset shape is harmless here.
    """
    return make_transaction_item(**overrides)


class TestToResponseNormalizesAudit:
    def test_legacy_override_normalized_surfaces_as_tier(self) -> None:
        item = _make_item(
            CategoryAudit={
                "source": "override_normalized",
                "matched_rule": "GROCERY MART #123",
                "reviewed_at": "2026-04-18T18:37:42+00:00",
            }
        )
        response = _to_response(item)
        assert response.category_audit is not None
        assert response.category_audit.source == "override"
        assert response.category_audit.tier == "normalized"
        assert response.category_audit.matched_rule == "GROCERY MART #123"

    def test_legacy_bare_override_gets_exact_tier(self) -> None:
        item = _make_item(
            CategoryAudit={
                "source": "override",
                "reviewed_at": "2026-04-18T18:37:42+00:00",
            }
        )
        response = _to_response(item)
        assert response.category_audit is not None
        assert response.category_audit.tier == "exact"

    def test_canonical_v2_passes_through_untouched(self) -> None:
        item = _make_item(
            CategoryAudit={
                "source": "ai_fallback",
                "fallback_reason": "api_error",
                "model": "gpt-5.4-nano",
                "reviewed_at": "2026-05-15T12:00:00-07:00",
                "schema_version": 2,
            }
        )
        response = _to_response(item)
        assert response.category_audit is not None
        assert response.category_audit.source == "ai_fallback"
        assert response.category_audit.fallback_reason == "api_error"
        assert response.category_audit.model == "gpt-5.4-nano"
        assert response.category_audit.schema_version == 2


class TestIsAttention:
    def test_misc_without_audit_is_attention(self) -> None:
        assert _is_attention(_make_item(Category="miscellaneous"))

    def test_misc_with_ai_fallback_is_attention(self) -> None:
        item = _make_item(
            Category="miscellaneous",
            CategoryAudit={"source": "ai_fallback", "fallback_reason": "api_error"},
        )
        assert _is_attention(item)

    def test_misc_with_ai_success_is_not_attention(self) -> None:
        item = _make_item(
            Category="miscellaneous",
            CategoryAudit={"source": "ai", "model": "gpt-5.4-nano"},
        )
        assert not _is_attention(item)

    def test_misc_with_manual_audit_is_not_attention(self) -> None:
        item = _make_item(
            Category="miscellaneous",
            CategoryAudit={"source": "manual", "reviewed_at": "2026-05-15T12:00:00-07:00"},
        )
        assert not _is_attention(item)

    def test_non_misc_is_not_attention(self) -> None:
        assert not _is_attention(_make_item(Category="groceries"))

    def test_ignored_is_not_attention(self) -> None:
        item = _make_item(Category="miscellaneous", Ignored=True)
        assert not _is_attention(item)

    def test_deleted_is_not_attention(self) -> None:
        item = _make_item(Category="miscellaneous", DeletedAt="2026-05-15T12:00:00-07:00")
        assert not _is_attention(item)
