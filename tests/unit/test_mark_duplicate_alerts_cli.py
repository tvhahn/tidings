"""History replay in ``dev/cli/mark_duplicate_alerts.py`` (issue #86 backfill)."""

from __future__ import annotations

from typing import Any

from dev.cli.mark_duplicate_alerts import plan_marks

BODY = "You've recently made a purchase with your card ending in [XXXX] for $10.00 at [MERCHANT]."


def _item(key: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "ForwardedTo": "user@example.com",
        "DateFileName": key,
        "Body": BODY,
        "Institution": "CIBC",
        "Amount": 10.0,
        "Company": "[MERCHANT]",
        "TransactionType": "purchase",
    }
    item.update(overrides)
    return item


def _planned(items: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [(item["DateFileName"], original, rule) for item, original, rule in plan_marks(items)]


def test_every_copy_points_at_the_first_alert() -> None:
    items = [_item("2025.05.20_10.08_c"), _item("2025.05.20_07.33_a"), _item("2025.05.20_09.25_b")]
    assert _planned(items) == [
        ("2025.05.20_09.25_b", "2025.05.20_07.33_a", "re-send"),
        ("2025.05.20_10.08_c", "2025.05.20_07.33_a", "re-send"),
    ]


def test_shared_hash_is_reported_as_the_same_email() -> None:
    items = [
        _item("2026.09.26_10.27_a", TransactionHash="h"),
        _item("2026.09.26_10.27_b", TransactionHash="h"),
    ]
    assert _planned(items) == [("2026.09.26_10.27_b", "2026.09.26_10.27_a", "same email")]


def test_rerun_after_apply_plans_nothing() -> None:
    items = [_item("2026.04.20_08.57_a"), _item("2026.04.20_12.29_b", DuplicateOf="2026.04.20_08.57_a")]
    assert _planned(items) == []


def test_next_day_repeat_and_other_partitions_are_left_alone() -> None:
    items = [
        _item("2026.04.20_08.00_a"),
        _item("2026.04.21_07.55_b"),
        _item("2026.04.20_08.30_c", ForwardedTo="other@example.com"),
    ]
    assert _planned(items) == []
