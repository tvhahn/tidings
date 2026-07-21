"""Characterization tests for `src/finance/versioned_update.py`.

The optimistic-lock read-modify-write primitive behind budget, category-cascade,
override, alias, ignore-rule, and icon writes. Its retry/skip branches are
concurrency-critical and otherwise exercised only indirectly through service
tests. These pin the contract directly: the assertions target *call counts and
arguments* (especially the retry re-planning semantics), not just return values.
"""

from __future__ import annotations

import pytest

from src.finance.exceptions import VersionConflictError
from src.finance.versioned_update import Update, item_version, versioned_update


class RecordingPlan:
    """A ``plan`` fake that yields a scripted sequence of results.

    Each call pops the next item from ``results`` and records that it ran, so a
    test can assert exactly how many times ``plan`` was re-run.
    """

    def __init__(self, *results: Update[dict[str, int]] | None) -> None:
        self._results = list(results)
        self.calls = 0

    def __call__(self) -> Update[dict[str, int]] | None:
        result = self._results[self.calls]
        self.calls += 1
        return result


class RecordingPut:
    """A ``put`` fake recording every ``(data, version)`` it received.

    ``conflict_on`` lists the zero-based attempt indexes that should raise
    :class:`VersionConflictError`; all other attempts return ``return_value``.
    """

    def __init__(
        self,
        *,
        return_value: str = "ok",
        conflict_on: tuple[int, ...] = (),
    ) -> None:
        self.return_value = return_value
        self._conflict_on = conflict_on
        self.calls: list[tuple[dict[str, int], int | None]] = []

    def __call__(self, data: dict[str, int], version: int | None) -> str:
        attempt = len(self.calls)
        self.calls.append((data, version))
        if attempt in self._conflict_on:
            raise VersionConflictError
        return self.return_value


def test_happy_path_returns_put_result_and_calls_each_once() -> None:
    plan = RecordingPlan(Update(data={"a": 1}, version=3))
    put = RecordingPut(return_value="written")

    result = versioned_update(plan, put)

    assert result == "written"
    assert plan.calls == 1
    assert put.calls == [({"a": 1}, 3)]


def test_create_path_passes_version_none_to_put() -> None:
    plan = RecordingPlan(Update(data={"a": 1}, version=None))
    put = RecordingPut()

    result = versioned_update(plan, put)

    assert result == "ok"
    assert put.calls == [({"a": 1}, None)]


def test_skip_when_plan_returns_none_never_calls_put() -> None:
    plan = RecordingPlan(None)
    put = RecordingPut()

    result = versioned_update(plan, put)

    assert result is None
    assert plan.calls == 1
    assert put.calls == []


def test_conflict_without_retry_propagates_after_single_attempt() -> None:
    plan = RecordingPlan(Update(data={"a": 1}, version=3))
    put = RecordingPut(conflict_on=(0,))

    with pytest.raises(VersionConflictError):
        versioned_update(plan, put)

    assert plan.calls == 1
    assert len(put.calls) == 1


def test_retry_replans_with_fresh_version_on_second_attempt() -> None:
    plan = RecordingPlan(
        Update(data={"a": 1}, version=3),
        Update(data={"a": 1}, version=4),
    )
    put = RecordingPut(return_value="second-write", conflict_on=(0,))

    result = versioned_update(plan, put, retry_on_conflict=True)

    assert result == "second-write"
    assert plan.calls == 2
    # Second put must see the re-read version 4, not the stale 3.
    assert put.calls == [({"a": 1}, 3), ({"a": 1}, 4)]


def test_double_conflict_with_retry_propagates_after_two_attempts() -> None:
    plan = RecordingPlan(
        Update(data={"a": 1}, version=3),
        Update(data={"a": 1}, version=4),
    )
    put = RecordingPut(conflict_on=(0, 1))

    with pytest.raises(VersionConflictError):
        versioned_update(plan, put, retry_on_conflict=True)

    assert plan.calls == 2
    assert len(put.calls) == 2


def test_skip_on_retry_when_replan_returns_none() -> None:
    plan = RecordingPlan(Update(data={"a": 1}, version=3), None)
    put = RecordingPut(conflict_on=(0,))

    result = versioned_update(plan, put, retry_on_conflict=True)

    assert result is None
    assert plan.calls == 2
    assert len(put.calls) == 1


def test_item_version_coerces_string_and_defaults_to_zero() -> None:
    assert item_version({"Version": "7"}) == 7
    assert item_version({}) == 0
