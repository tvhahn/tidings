"""Tests for BudgetService — CRUD, type inference, and historical averages."""

import threading
import time
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.finance.budget_service import BudgetService, _floats_to_decimals
from src.finance.exceptions import VersionConflictError
from tests.factories import make_budget_service as _make_service

# ---------------------------------------------------------------------------
# _floats_to_decimals
# ---------------------------------------------------------------------------


class TestFloatsToDecimals:
    """Recursive float -> Decimal conversion for DynamoDB compatibility."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Flat dict of floats
            ({"a": 1.5, "b": 2.25}, {"a": Decimal("1.5"), "b": Decimal("2.25")}),
            # Nested dicts
            (
                {"outer": {"inner": 3.5, "deep": {"x": 0.1}}},
                {"outer": {"inner": Decimal("3.5"), "deep": {"x": Decimal("0.1")}}},
            ),
            # Lists of floats
            ([1.1, 2.2, 3.3], [Decimal("1.1"), Decimal("2.2"), Decimal("3.3")]),
            # Lists of dicts
            (
                [{"amount": 10.5}, {"amount": 20.75}],
                [{"amount": Decimal("10.5")}, {"amount": Decimal("20.75")}],
            ),
            # Mixed dict: ints / Decimal / str / None pass through unchanged; floats convert
            (
                {"i": 5, "f": 2.5, "d": Decimal("9.99"), "s": "text", "n": None},
                {"i": 5, "f": Decimal("2.5"), "d": Decimal("9.99"), "s": "text", "n": None},
            ),
            # Mixed list with nested floats inside dicts
            (
                [1, 2.5, "x", None, {"f": 3.5}],
                [1, Decimal("2.5"), "x", None, {"f": Decimal("3.5")}],
            ),
            # Dict and list nested together with floats at the leaves
            (
                {"categories": [{"target": 18000.0}], "ceiling": 100000},
                {"categories": [{"target": Decimal("18000.0")}], "ceiling": 100000},
            ),
        ],
    )
    def test_converts_structures(self, value: Any, expected: Any) -> None:
        assert _floats_to_decimals(value) == expected

    @pytest.mark.parametrize(
        "scalar",
        [5, 0, -3, "string", None, True, Decimal("1.23")],
    )
    def test_non_float_scalars_pass_through_unchanged(self, scalar: Any) -> None:
        result = _floats_to_decimals(scalar)
        assert result == scalar
        # Same object identity for pass-through (no copy made)
        assert result is scalar

    @pytest.mark.parametrize("flt", [1.5, 2.25, 0.1, 99.99])
    def test_float_becomes_decimal_type(self, flt: float) -> None:
        result = _floats_to_decimals(flt)
        assert isinstance(result, Decimal)
        assert not isinstance(result, float)

    def test_precision_uses_str_not_binary_drift(self) -> None:
        """99.99 must convert via str() to avoid float binary-repr drift."""
        result = _floats_to_decimals(99.99)
        assert result == Decimal("99.99")
        # The buggy alternative — Decimal() straight from the float — carries
        # binary drift; ensure the helper's str()-based conversion does not.
        drifted = Decimal(99.99)  # noqa: RUF032 - intentionally demonstrating binary drift
        assert result != drifted
        assert str(result) == "99.99"

    @pytest.mark.parametrize("flt", [0.1, 0.2, 0.3, 19.99, 1234.567])
    def test_decimal_string_matches_repr(self, flt: float) -> None:
        assert _floats_to_decimals(flt) == Decimal(str(flt))

    def test_empty_containers_pass_through(self) -> None:
        assert _floats_to_decimals({}) == {}
        assert _floats_to_decimals([]) == []


# ---------------------------------------------------------------------------
# get_targets / get_groups
# ---------------------------------------------------------------------------


class TestGetTargets:
    def test_returns_none_when_not_configured(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        assert svc.get_targets(2026) is None

    def test_returns_data_when_configured(self):
        item = {
            "PK": "USER#default",
            "SK": "BUDGET#targets#2026",
            "Data": {"spending_ceiling": 96000, "categories": {}},
            "Version": 1,
        }
        svc = _make_service()
        svc.table.get_item.return_value = {"Item": item}
        result = svc.get_targets(2026)
        assert result is not None
        assert result["Version"] == 1
        assert result["Data"]["spending_ceiling"] == 96000

    def test_uses_correct_key(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        svc.get_targets(2026)
        svc.table.get_item.assert_called_once_with(Key={"PK": "USER#default", "SK": "BUDGET#targets#2026"})


# ---------------------------------------------------------------------------
# put_targets
# ---------------------------------------------------------------------------


class TestPutTargets:
    def test_writes_with_version(self):
        svc = _make_service()
        svc.table.put_item.return_value = {}
        # Stub get_targets/get_groups for _write_backup
        svc.get_targets = MagicMock(return_value=None)
        svc.get_groups = MagicMock(return_value=None)

        data = {"spending_ceiling": 100000, "categories": {"rent": {"target": 36000}}}
        new_version = svc.put_targets(2026, data, expected_version=1)

        assert new_version == 2
        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "Version = :expected"
        assert call_kwargs["ExpressionAttributeValues"] == {":expected": 1}

    def test_raises_on_version_conflict(self):
        svc = _make_service()
        # error_response: Any sidesteps botocore's private _ClientErrorResponseTypeDef
        # TypedDict invariance — the plain dict is correct at runtime.
        error_response: Any = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}}
        svc.table.put_item.side_effect = ClientError(error_response, "PutItem")

        with pytest.raises(VersionConflictError):
            svc.put_targets(2026, {"spending_ceiling": 100000, "categories": {}}, expected_version=1)

    def test_derives_monthly_amount(self):
        svc = _make_service()
        svc.table.put_item.return_value = {}
        svc.get_targets = MagicMock(return_value=None)
        svc.get_groups = MagicMock(return_value=None)

        data = {
            "spending_ceiling": 100000,
            "categories": {
                "groceries": {"target": 18000, "input_mode": "monthly", "category_type": "variable"},
            },
        }
        svc.put_targets(2026, data, expected_version=None)

        put_item = svc.table.put_item.call_args[1]["Item"]
        assert put_item["Data"]["categories"]["groceries"]["monthly_amount"] == 1500.0

    def test_creates_new_with_none_version(self):
        svc = _make_service()
        svc.table.put_item.return_value = {}
        svc.get_targets = MagicMock(return_value=None)
        svc.get_groups = MagicMock(return_value=None)

        new_version = svc.put_targets(2026, {"spending_ceiling": 50000, "categories": {}}, expected_version=None)

        assert new_version == 1
        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(Version)"
        assert "ExpressionAttributeValues" not in call_kwargs


# ---------------------------------------------------------------------------
# put_groups
# ---------------------------------------------------------------------------


class TestPutGroups:
    def test_writes_with_version(self):
        svc = _make_service()
        svc.table.put_item.return_value = {}
        svc.get_targets = MagicMock(return_value=None)
        svc.get_groups = MagicMock(return_value=None)

        data = {"groups": [{"name": "Food", "categories": ["groceries"]}]}
        new_version = svc.put_groups(2026, data, expected_version=1)

        assert new_version == 2
        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "Version = :expected"
        assert call_kwargs["ExpressionAttributeValues"] == {":expected": 1}

    def test_raises_on_version_conflict(self):
        svc = _make_service()
        error_response: Any = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}}
        svc.table.put_item.side_effect = ClientError(error_response, "PutItem")

        with pytest.raises(VersionConflictError):
            svc.put_groups(2026, {"groups": []}, expected_version=1)

    def test_creates_new_with_none_version(self):
        svc = _make_service()
        svc.table.put_item.return_value = {}
        svc.get_targets = MagicMock(return_value=None)
        svc.get_groups = MagicMock(return_value=None)

        new_version = svc.put_groups(2026, {"groups": []}, expected_version=None)

        assert new_version == 1
        call_kwargs = svc.table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(Version)"


# ---------------------------------------------------------------------------
# get_groups
# ---------------------------------------------------------------------------


class TestGetGroups:
    def test_returns_none_when_not_configured(self):
        svc = _make_service()
        svc.table.get_item.return_value = {}
        assert svc.get_groups(2026) is None

    def test_returns_data_when_configured(self):
        item = {
            "PK": "USER#default",
            "SK": "BUDGET#groups#2026",
            "Data": {"groups": [{"name": "Food", "categories": ["groceries"]}]},
            "Version": 1,
        }
        svc = _make_service()
        svc.table.get_item.return_value = {"Item": item}
        result = svc.get_groups(2026)
        assert result is not None
        assert result["Version"] == 1
        assert result["Data"]["groups"][0]["name"] == "Food"


# ---------------------------------------------------------------------------
# _write_backup error handling
# ---------------------------------------------------------------------------


class TestWriteBackup:
    @patch("src.finance.budget_service._CONFIG_DIR")
    def test_backup_failure_is_swallowed(self, mock_config_dir: MagicMock) -> None:
        """_write_backup catches exceptions and logs them."""
        mock_config_dir.mkdir.side_effect = OSError("Permission denied")
        svc = _make_service()
        svc.get_targets = MagicMock(return_value=None)
        svc.get_groups = MagicMock(return_value=None)
        # Should not raise
        svc._write_backup(2026)


# ---------------------------------------------------------------------------
# infer_category_type
# ---------------------------------------------------------------------------


class TestInferType:
    def test_fixed(self):
        assert BudgetService.infer_category_type(6, 6, 0.10) == "fixed"

    def test_variable(self):
        assert BudgetService.infer_category_type(6, 6, 0.25) == "variable"

    def test_variable_no_cv(self):
        assert BudgetService.infer_category_type(6, 6, None) == "variable"

    def test_lumpy(self):
        assert BudgetService.infer_category_type(3, 6) == "lumpy"

    def test_none(self):
        assert BudgetService.infer_category_type(0, 6) == "none"


# ---------------------------------------------------------------------------
# get_historical_averages
# ---------------------------------------------------------------------------


class TestHistorical:
    def _mock_spending_summary(self, months_data: list[dict[str, Any]]) -> MagicMock:
        """Create a mock SpendingSummary that returns data for each month."""
        ss = MagicMock(name="spending_summary")
        call_count = 0

        def get_summary(ym: str) -> dict[str, Any]:
            nonlocal call_count
            idx = min(call_count, len(months_data) - 1)
            call_count += 1
            return months_data[idx]

        ss.get_summary.side_effect = get_summary
        return ss

    def test_aggregates_correctly(self):
        svc = _make_service()
        months_data = [
            {
                "by_category": {
                    "groceries": {"amount": Decimal(1000), "count": 10},
                    "rent": {"amount": Decimal(2950), "count": 1},
                },
            }
            for _ in range(6)
        ]

        ss = self._mock_spending_summary(months_data)
        result = svc.get_historical_averages(ss, months=6)

        assert result["months_analyzed"] == 6
        assert "groceries" in result["categories"]
        cat = result["categories"]["groceries"]
        assert cat["monthly_avg"] == pytest.approx(1000.0)
        assert cat["months_active"] == 6
        assert cat["total"] == pytest.approx(6000.0)

    def test_caches_result(self):
        svc = _make_service()
        months_data = [{"by_category": {"groceries": {"amount": Decimal(100), "count": 1}}} for _ in range(6)]
        ss = self._mock_spending_summary(months_data)

        result1 = svc.get_historical_averages(ss, months=6)
        result2 = svc.get_historical_averages(ss, months=6)

        assert result1 is result2
        # Only called 6 times (first call), not 12
        assert ss.get_summary.call_count == 6

    def test_invalidate_cache_forces_refresh(self):
        svc = _make_service()
        months_data = [{"by_category": {"groceries": {"amount": Decimal(100), "count": 1}}} for _ in range(6)]
        ss = self._mock_spending_summary(months_data)

        svc.get_historical_averages(ss, months=6)
        assert ss.get_summary.call_count == 6

        svc.invalidate_cache()
        # Need fresh mock data for second call
        ss.get_summary.call_count = 0
        months_data2 = [{"by_category": {"groceries": {"amount": Decimal(200), "count": 2}}} for _ in range(6)]
        call_count2 = 0

        def get_summary2(ym: str) -> dict[str, Any]:
            nonlocal call_count2
            idx = min(call_count2, len(months_data2) - 1)
            call_count2 += 1
            return months_data2[idx]

        ss.get_summary.side_effect = get_summary2
        svc.get_historical_averages(ss, months=6)
        assert call_count2 == 6


class TestCategoryAnomalies:
    """Tests for BudgetServiceBase.get_category_anomalies()."""

    def _ss_with_history(self, per_month: dict[str, dict[str, Decimal]]) -> MagicMock:
        """Build a SpendingSummary mock keyed by year_month."""
        ss = MagicMock()

        def get_summary(ym: str) -> dict[str, Any]:
            month = per_month.get(ym, {})
            by_category = {cat: {"amount": amt, "count": 1} for cat, amt in month.items()}
            return {"by_category": by_category}

        ss.get_summary.side_effect = get_summary
        return ss

    def test_no_anomalies_when_stable(self):
        svc = _make_service()
        # 6 baseline months at $300, current also $300
        per_month = {f"2026-{m:02d}": {"groceries": Decimal(300)} for m in range(1, 8)}
        ss = self._ss_with_history(per_month)
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6)
        assert anomalies == []

    def test_flags_spike_above_threshold(self):
        svc = _make_service()
        # 6 baseline months at $300 (stdev = 0 → skipped). Use a small spread.
        per_month = {
            "2026-01": {"groceries": Decimal(280)},
            "2026-02": {"groceries": Decimal(310)},
            "2026-03": {"groceries": Decimal(290)},
            "2026-04": {"groceries": Decimal(305)},
            "2026-05": {"groceries": Decimal(295)},
            "2026-06": {"groceries": Decimal(320)},
            "2026-07": {"groceries": Decimal(600)},  # spike
        }
        ss = self._ss_with_history(per_month)
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6)
        assert len(anomalies) == 1
        a = anomalies[0]
        assert a["category"] == "groceries"
        assert a["current"] == 600.0
        assert a["severity"] in {"medium", "high"}
        assert "above" in a["reason"]

    def test_flags_unexpected_zero(self):
        svc = _make_service()
        # Active 6/6 in baseline, then zero
        per_month = {f"2026-{m:02d}": {"netflix-cat": Decimal(16)} for m in range(1, 7)}
        per_month["2026-07"] = {}  # category absent
        ss = self._ss_with_history(per_month)
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6)
        assert any(a["category"] == "netflix-cat" and a["current"] == 0.0 for a in anomalies)

    def test_ignores_zero_when_baseline_was_sparse(self):
        svc = _make_service()
        # Only 3/6 months active in baseline — current zero is not a quiet anomaly
        per_month = {
            "2026-01": {"hobbies": Decimal(50)},
            "2026-03": {"hobbies": Decimal(30)},
            "2026-05": {"hobbies": Decimal(70)},
            "2026-07": {},
        }
        ss = self._ss_with_history(per_month)
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6)
        assert all(a["category"] != "hobbies" for a in anomalies)

    def test_severity_grading(self):
        svc = _make_service()
        # mean=300, stdev=~10. current=400 → ~10 stdevs → high
        per_month = {
            "2026-01": {"x": Decimal(295)},
            "2026-02": {"x": Decimal(300)},
            "2026-03": {"x": Decimal(305)},
            "2026-04": {"x": Decimal(298)},
            "2026-05": {"x": Decimal(302)},
            "2026-06": {"x": Decimal(300)},
            "2026-07": {"x": Decimal(400)},
        }
        ss = self._ss_with_history(per_month)
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6)
        assert anomalies[0]["severity"] == "high"

    def test_reason_phrasing_is_calm(self):
        svc = _make_service()
        per_month = {
            "2026-01": {"dining": Decimal(280)},
            "2026-02": {"dining": Decimal(310)},
            "2026-03": {"dining": Decimal(290)},
            "2026-04": {"dining": Decimal(305)},
            "2026-05": {"dining": Decimal(295)},
            "2026-06": {"dining": Decimal(320)},
            "2026-07": {"dining": Decimal(100)},
        }
        ss = self._ss_with_history(per_month)
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6)
        for a in anomalies:
            for banned in ("alert", "warning", "critical", "danger", "spike", "surge", "!"):
                assert banned.lower() not in a["reason"].lower()


class TestProportionalCommentHandling:
    """annotated_amounts re-tests each spike against the un-annotated remainder."""

    def _ss_with_history(self, per_month: dict[str, dict[str, Decimal]]) -> MagicMock:
        ss = MagicMock()

        def get_summary(ym: str) -> dict[str, Any]:
            month = per_month.get(ym, {})
            return {"by_category": {cat: {"amount": amt, "count": 1} for cat, amt in month.items()}}

        ss.get_summary.side_effect = get_summary
        return ss

    def _misc_history(self) -> dict[str, dict[str, Decimal]]:
        # Baseline ~$150/month, target month spikes to $745.
        return {
            "2026-01": {"miscellaneous": Decimal(140)},
            "2026-02": {"miscellaneous": Decimal(160)},
            "2026-03": {"miscellaneous": Decimal(150)},
            "2026-04": {"miscellaneous": Decimal(155)},
            "2026-05": {"miscellaneous": Decimal(145)},
            "2026-06": {"miscellaneous": Decimal(150)},
            "2026-07": {"miscellaneous": Decimal(745)},
        }

    def test_partially_explained_spike_is_kept_and_annotated(self):
        svc = _make_service()
        ss = self._ss_with_history(self._misc_history())
        # $85 of the $745 is annotated — the remainder ($660) is still a spike.
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6, annotated_amounts={"miscellaneous": 84.99})
        misc = next(a for a in anomalies if a["category"] == "miscellaneous")
        assert misc["current"] == 745.0  # original value preserved
        assert misc["annotated_amount"] == 84.99
        assert "annotated" in misc["reason"]
        assert "$85 of $745 annotated" in misc["reason"]

    def test_fully_explained_spike_is_dropped(self):
        svc = _make_service()
        ss = self._ss_with_history(self._misc_history())
        # The spike above baseline is annotated back into the baseline band
        # ($745 minus $595 is $150, at the ~$150 mean) so it is no longer anomalous.
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6, annotated_amounts={"miscellaneous": 595.0})
        assert all(a["category"] != "miscellaneous" for a in anomalies)

    def test_annotation_exceeding_the_whole_spike_is_dropped_not_resurrected(self):
        svc = _make_service()
        ss = self._ss_with_history(self._misc_history())
        # $700 annotated of a $745 spike leaves a $45 remainder — far *below*
        # the ~$150 mean. The one-sided re-test must drop the anomaly rather
        # than keep it because |z| of the remainder is still >= 1.5.
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6, annotated_amounts={"miscellaneous": 700.0})
        assert all(a["category"] != "miscellaneous" for a in anomalies)

    def test_no_annotation_leaves_spike_untouched(self):
        svc = _make_service()
        ss = self._ss_with_history(self._misc_history())
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6)
        misc = next(a for a in anomalies if a["category"] == "miscellaneous")
        assert "annotated_amount" not in misc  # defaults to 0 via the model
        assert "annotated" not in misc["reason"]

    def test_zero_anomaly_unaffected_by_annotation(self):
        svc = _make_service()
        # Active every baseline month, then zero this month — annotation cannot apply.
        per_month = {f"2026-{m:02d}": {"netflix-cat": Decimal(16)} for m in range(1, 7)}
        per_month["2026-07"] = {}
        ss = self._ss_with_history(per_month)
        anomalies = svc.get_category_anomalies(ss, "2026-07", months=6, annotated_amounts={"netflix-cat": 16.0})
        zero = next(a for a in anomalies if a["category"] == "netflix-cat")
        assert zero["current"] == 0.0
        assert "annotated_amount" not in zero


class TestHistoricalAveragesConcurrency:
    """Single-flight: concurrent cold-cache callers aggregate at most once."""

    def test_single_flight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = _make_service()
        ss = MagicMock(name="spending_summary")
        barrier = threading.Barrier(8)
        calls = 0
        calls_lock = threading.Lock()
        sentinel: dict[str, Any] = {"months_analyzed": 6, "period": {}, "categories": {}}

        def fake_compute(spending_summary: Any, months: int) -> dict[str, Any]:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)  # hold the miss long enough for all threads to pile on
            return sentinel

        monkeypatch.setattr(svc, "_compute_historical_averages", fake_compute)

        results: list[dict[str, Any]] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = svc.get_historical_averages(ss, months=6)
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert all(not t.is_alive() for t in threads)
        assert calls == 1
        assert len(results) == 8
        assert all(r is sentinel for r in results)
