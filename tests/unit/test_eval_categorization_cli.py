"""Unit tests for the categorization bake-off harness (dev/cli/eval_categorization.py).

Every test here is offline: the pure helpers take plain dicts, and the two
tests that exercise `RecordingClient` / `run_arm` drive a hand-rolled fake
chat client. No OpenAI call, no database handle, no real transaction data.
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from dev.cli.eval_categorization import (
    ARMS,
    ArmSummary,
    Observation,
    RecordingClient,
    Sample,
    WinnerDecision,
    build_replay_transaction,
    build_report,
    classify_ground_truth,
    collect_samples,
    dedupe_by_company,
    format_markdown,
    parse_arm_names,
    pick_winner,
    run_arm,
    summarize_arm,
)

CATEGORIES = ["Groceries", "Restaurant/Dining", "Miscellaneous"]

#: A merchant string that must never leak into a default-mode report.
SENTINEL_MERCHANT = "Zzyzx Artisanal Sprocket Emporium"


def make_item(**overrides: Any) -> dict[str, Any]:
    """A stored transaction row (PascalCase, DynamoDB-shaped) with an AI audit."""
    item: dict[str, Any] = {
        "ForwardedTo": "user@example.com",
        "DateFileName": "2026.04.03_12.01_rbc.eml",
        "Company": "Corner Market",
        "Amount": Decimal("41.25"),
        "Category": "groceries",
        "CategoryAudit": {"source": "ai", "model": "gpt-5.4-nano", "schema_version": 2},
    }
    item.update(overrides)
    return item


# --------------------------------------------------------------------------- #
# classify_ground_truth — one case per stratum
# --------------------------------------------------------------------------- #


class TestClassifyGroundTruthStrata:
    """Each stratum has exactly one audit signature that produces it."""

    def test_override_at_ingest(self) -> None:
        """An override written by the categorizer at ingestion carries no previous_source."""
        item = make_item(
            CategoryAudit={"source": "override", "tier": "exact", "matched_rule": "Corner Market"},
        )
        assert classify_ground_truth(item, CATEGORIES) == "override_at_ingest"

    def test_override_applied_retroactively_is_excluded(self) -> None:
        """An override stamped over an existing label saw the model's answer first — biased."""
        item = make_item(CategoryAudit={"source": "override", "tier": "exact", "previous_source": "ai"})
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_corrected(self) -> None:
        """A manual edit whose previous_source was the AI is a correction."""
        item = make_item(
            CategoryAudit={"source": "manual", "previous_source": "ai", "previous_category": "restaurant/dining"}
        )
        assert classify_ground_truth(item, CATEGORIES) == "corrected"

    def test_confirmed(self) -> None:
        """mark_category_reviewed writes a manual source with no previous_source."""
        item = make_item(CategoryAudit={"source": "manual", "schema_version": 2})
        assert classify_ground_truth(item, CATEGORIES) == "confirmed"

    def test_ai_unreviewed(self) -> None:
        item = make_item()
        assert classify_ground_truth(item, CATEGORIES) == "ai_unreviewed"

    def test_manual_over_a_non_ai_source_is_excluded(self) -> None:
        """A manual edit over a statement import tells us nothing about the model."""
        item = make_item(CategoryAudit={"source": "manual_edit", "previous_source": "statement_import"})
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_legacy_override_shape_normalizes_to_override_at_ingest(self) -> None:
        """normalize_audit collapses source='override_alias' onto override/tier=alias."""
        item = make_item(CategoryAudit={"source": "override_alias"})
        assert classify_ground_truth(item, CATEGORIES) == "override_at_ingest"


class TestClassifyGroundTruthExclusions:
    """Every exclusion reason, one test each."""

    @pytest.mark.parametrize("source", ["ai_fallback", "statement_import", "statement_enrich", "category_rename"])
    def test_untrustworthy_sources(self, source: str) -> None:
        item = make_item(CategoryAudit={"source": source})
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_soft_deleted_row(self) -> None:
        item = make_item(DeletedAt="2026-04-05T10:00:00-07:00")
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_ignored_row(self) -> None:
        item = make_item(Ignored=True)
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_missing_company(self) -> None:
        item = make_item(Company="   ")
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_missing_amount(self) -> None:
        item = make_item(Amount=None)
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_missing_category(self) -> None:
        item = make_item(Category="")
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_category_outside_current_vocabulary(self) -> None:
        item = make_item(Category="pet supplies")
        assert classify_ground_truth(item, CATEGORIES) == "excluded"

    def test_vocabulary_comparison_is_case_insensitive(self) -> None:
        """Storage lowercases categories; the vocabulary is title-cased."""
        item = make_item(Category="restaurant/dining")
        assert classify_ground_truth(item, CATEGORIES) == "ai_unreviewed"

    def test_missing_audit_entirely_is_excluded(self) -> None:
        item = make_item(CategoryAudit=None)
        assert classify_ground_truth(item, CATEGORIES) == "excluded"


# --------------------------------------------------------------------------- #
# build_replay_transaction
# --------------------------------------------------------------------------- #


class TestBuildReplayTransaction:
    """The replay dict must match src/finance/email_pipeline.py exactly."""

    def test_exact_key_set(self) -> None:
        txn = build_replay_transaction(make_item())
        assert set(txn) == {"amount", "company"}

    def test_decimal_amount_becomes_float(self) -> None:
        txn = build_replay_transaction(make_item(Amount=Decimal("41.25")))
        assert txn["amount"] == 41.25
        assert isinstance(txn["amount"], float)

    def test_company_is_a_string(self) -> None:
        txn = build_replay_transaction(make_item(Company="Corner Market"))
        assert txn["company"] == "Corner Market"

    def test_prompt_repr_matches_production_shape(self) -> None:
        """The prompt interpolates str(transaction) — a Decimal repr would change it."""
        txn = build_replay_transaction(make_item())
        assert str(txn) == "{'amount': 41.25, 'company': 'Corner Market'}"


# --------------------------------------------------------------------------- #
# dedupe_by_company
# --------------------------------------------------------------------------- #


def make_sample(index: int, **overrides: Any) -> Sample:
    fields: dict[str, Any] = {
        "index": index,
        "sample_id": f"id{index:04d}",
        "stratum": "ai_unreviewed",
        "expected": "groceries",
        "company": "Corner Market",
        "amount": 41.25,
        "date_file_name": f"2026.04.{index + 1:02d}_12.00_rbc.eml",
    }
    fields.update(overrides)
    return Sample(**fields)


class TestDedupeByCompany:
    def test_keeps_one_row_per_company_per_stratum_most_recent_wins(self) -> None:
        samples = [
            make_sample(0, company="CORNER MARKET #221", date_file_name="2026.01.02_09.00_a.eml"),
            make_sample(1, company="Corner Market #998", date_file_name="2026.05.02_09.00_b.eml"),
        ]
        kept = dedupe_by_company(samples)
        assert len(kept) == 1
        assert kept[0].date_file_name == "2026.05.02_09.00_b.eml"

    def test_same_company_in_two_strata_is_kept_twice(self) -> None:
        samples = [
            make_sample(0, stratum="ai_unreviewed"),
            make_sample(1, stratum="corrected"),
        ]
        assert len(dedupe_by_company(samples)) == 2


# --------------------------------------------------------------------------- #
# collect_samples
# --------------------------------------------------------------------------- #


class TestCollectSamples:
    def test_limit_caps_ai_unreviewed_only(self) -> None:
        """Human-verified rows are never dropped; the agreement stratum is trimmed."""
        items = [
            make_item(Company=f"AI Merchant {i}", DateFileName=f"2026.04.{i + 1:02d}_09.00_a.eml") for i in range(5)
        ]
        items += [
            make_item(
                Company=f"Override Merchant {i}",
                DateFileName=f"2026.03.{i + 1:02d}_09.00_b.eml",
                CategoryAudit={"source": "override", "tier": "exact"},
            )
            for i in range(4)
        ]
        samples, found, replayed = collect_samples(items, CATEGORIES, limit=2)
        assert found["ai_unreviewed"] == 5
        assert replayed["ai_unreviewed"] == 2
        assert replayed["override_at_ingest"] == 4
        assert [s.index for s in samples] == list(range(len(samples)))

    def test_excluded_rows_are_counted_but_not_replayed(self) -> None:
        items = [make_item(), make_item(Company="Ghost", Ignored=True)]
        _samples, found, replayed = collect_samples(items, CATEGORIES, limit=10)
        assert found["excluded"] == 1
        assert replayed["excluded"] == 0


# --------------------------------------------------------------------------- #
# RecordingClient
# --------------------------------------------------------------------------- #


class FakeChatClient:
    """Minimal AIProviderClient-shaped fake — no network, no SDK."""

    def __init__(self, completion: Any = None, last_error: Exception | None = None) -> None:
        self.model = "fake-model"
        self.completion = completion
        self.last_error = last_error
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        return self.completion


def make_completion(category: str, *, usage: Any = None) -> SimpleNamespace:
    """A chat completion carrying one forced `categorize_transaction` tool call."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="categorize_transaction",
                                arguments=json.dumps({"category": category}),
                            )
                        )
                    ]
                )
            )
        ],
        usage=usage,
    )


class TestRecordingClient:
    def test_records_latency_and_token_counters_from_a_completion(self) -> None:
        usage = SimpleNamespace(
            prompt_tokens=137,
            completion_tokens=9,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=64),
            prompt_tokens_details=SimpleNamespace(cached_tokens=128),
        )
        inner = FakeChatClient(completion=make_completion("Groceries", usage=usage))
        client = RecordingClient(inner)

        result = client.chat([{"role": "user", "content": "x"}], tools=[], tool_choice="auto")

        assert result is inner.completion
        assert client.model == "fake-model"
        assert len(client.records) == 1
        record = client.records[0]
        assert record.prompt_tokens == 137
        assert record.completion_tokens == 9
        assert record.reasoning_tokens == 64
        assert record.cached_tokens == 128
        assert record.error is None
        assert record.latency_s >= 0.0

    def test_none_completion_records_error_and_null_counters(self) -> None:
        boom = RuntimeError("provider said no")
        inner = FakeChatClient(completion=None, last_error=boom)
        client = RecordingClient(inner)

        assert client.chat([{"role": "user", "content": "x"}]) is None
        record = client.records[0]
        assert record.prompt_tokens is None
        assert record.completion_tokens is None
        assert record.reasoning_tokens is None
        assert record.cached_tokens is None
        assert record.error == "RuntimeError"
        assert client.last_error is boom

    def test_usage_without_detail_objects_is_tolerated(self) -> None:
        inner = FakeChatClient(completion=make_completion("Groceries", usage=SimpleNamespace(prompt_tokens=10)))
        client = RecordingClient(inner)
        client.chat([{"role": "user", "content": "x"}])
        record = client.records[0]
        assert record.prompt_tokens == 10
        assert record.reasoning_tokens is None
        assert record.cached_tokens is None


# --------------------------------------------------------------------------- #
# run_arm
# --------------------------------------------------------------------------- #


class TestRunArm:
    def test_scores_each_sample_and_captures_the_audit_source(self) -> None:
        inner = FakeChatClient(completion=make_completion("Groceries"))
        client = RecordingClient(inner)
        samples = [make_sample(0, expected="groceries"), make_sample(1, expected="restaurant/dining")]

        observations = run_arm(samples, client, CATEGORIES)

        assert [obs.predicted for obs in observations] == ["groceries", "groceries"]
        assert [obs.correct for obs in observations] == [True, False]
        assert {obs.audit_source for obs in observations} == {"ai"}
        assert len(inner.calls) == 2

    def test_silent_fallback_is_surfaced_not_swallowed(self) -> None:
        """A rejected effort/tool_choice combo returns Miscellaneous, not an exception."""
        inner = FakeChatClient(completion=None, last_error=RuntimeError("bad request"))
        client = RecordingClient(inner)

        observations = run_arm([make_sample(0)], client, CATEGORIES)

        assert observations[0].predicted == "miscellaneous"
        assert observations[0].audit_source == "ai_fallback"
        assert observations[0].fallback_reason == "api_error"


# --------------------------------------------------------------------------- #
# pick_winner
# --------------------------------------------------------------------------- #


def make_summary(
    arm_name: str,
    *,
    hv_correct: int = 100,
    hv_total: int = 100,
    agreement_correct: int = 95,
    agreement_total: int = 100,
    fallback_rate: float = 0.0,
    p95: float = 1.0,
) -> ArmSummary:
    arm = ARMS[arm_name]
    summary = ArmSummary(
        name=arm.name,
        model=arm.model,
        effort=arm.effort_label,
        is_luna=arm.is_luna,
        n=hv_total + agreement_total,
    )
    summary.stratum_totals = {"override_at_ingest": hv_total, "ai_unreviewed": agreement_total}
    summary.stratum_correct = {"override_at_ingest": hv_correct, "ai_unreviewed": agreement_correct}
    summary.human_verified_total = hv_total
    summary.human_verified_correct = hv_correct
    summary.fallback_rate = fallback_rate
    summary.p95_latency_s = p95
    return summary


class TestPickWinner:
    def test_high_fallback_rate_disqualifies(self) -> None:
        summaries = [
            make_summary("luna/none", hv_correct=100, fallback_rate=0.12),
            make_summary("luna/low", hv_correct=98),
        ]
        decision = pick_winner(summaries)
        assert decision.winner == "luna/low"
        assert any("disqualified" in r and "fallback rate" in r for r in decision.reasons["luna/none"])

    def test_margin_rule_accepts_a_slightly_worse_cheaper_arm(self) -> None:
        """Within max(2 rows, 2%) of the best luna arm counts as a tie."""
        summaries = [
            make_summary("luna/none", hv_correct=98),
            make_summary("luna/medium", hv_correct=100),
        ]
        assert pick_winner(summaries).winner == "luna/none"

    def test_margin_rule_rejects_a_clearly_worse_cheaper_arm(self) -> None:
        summaries = [
            make_summary("luna/none", hv_correct=80),
            make_summary("luna/low", hv_correct=100),
        ]
        decision = pick_winner(summaries)
        assert decision.winner == "luna/low"
        assert any("human-verified correct 80/100" in r for r in decision.reasons["luna/none"])

    def test_agreement_gate_rejects_an_arm_that_drifts(self) -> None:
        summaries = [
            make_summary("luna/none", hv_correct=100, agreement_correct=80),
            make_summary("luna/low", hv_correct=100, agreement_correct=95),
        ]
        decision = pick_winner(summaries)
        assert decision.winner == "luna/low"
        assert any("agreement" in r and "below the best luna arm" in r for r in decision.reasons["luna/none"])

    def test_latency_gate_rejects_a_slow_arm(self) -> None:
        summaries = [
            make_summary("luna/none", p95=9.5),
            make_summary("luna/low", p95=2.0),
        ]
        decision = pick_winner(summaries)
        assert decision.winner == "luna/low"
        assert any("p95 latency 9.50s > 8.0s" in r for r in decision.reasons["luna/none"])

    def test_tie_breaks_toward_the_lower_effort(self) -> None:
        summaries = [
            make_summary("luna/low"),
            make_summary("luna/none"),
            make_summary("luna/medium"),
        ]
        assert pick_winner(summaries).winner == "luna/none"

    def test_default_effort_never_wins(self) -> None:
        """luna/default ties the best arm on every metric and still loses to a pinnable effort."""
        summaries = [
            make_summary("luna/default", hv_correct=100, agreement_correct=95, p95=0.1),
            make_summary("luna/medium", hv_correct=100, agreement_correct=95, p95=2.0),
        ]
        decision = pick_winner(summaries)
        assert decision.winner == "luna/medium"
        assert any("never wins" in r for r in decision.reasons["luna/default"])

    def test_default_arm_still_sets_the_baseline_it_cannot_win(self) -> None:
        """`default` is a luna arm: an eligible effort must keep pace with it."""
        summaries = [
            make_summary("luna/default", hv_correct=100, agreement_correct=100),
            make_summary("luna/medium", hv_correct=60, agreement_correct=60),
        ]
        assert pick_winner(summaries).winner is None

    def test_nano_is_context_only(self) -> None:
        summaries = [make_summary("nano/default", hv_correct=100, agreement_correct=100, p95=0.1)]
        decision = pick_winner(summaries)
        assert decision.winner is None
        assert any("incumbent labeler" in r for r in decision.reasons["nano/default"])

    def test_no_winner_when_every_luna_arm_is_disqualified(self) -> None:
        summaries = [
            make_summary("luna/none", fallback_rate=0.5),
            make_summary("luna/low", fallback_rate=0.5),
        ]
        assert pick_winner(summaries).winner is None


# --------------------------------------------------------------------------- #
# summarize_arm
# --------------------------------------------------------------------------- #


def make_observation(index: int, predicted: str, **overrides: Any) -> Observation:
    fields: dict[str, Any] = {
        "index": index,
        "sample_id": f"id{index:04d}",
        "stratum": "override_at_ingest",
        "expected": "groceries",
        "predicted": predicted,
        "correct": predicted == "groceries",
        "audit_source": "ai",
        "fallback_reason": None,
        "latency_s": 1.0,
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "reasoning_tokens": 20,
        "cached_tokens": 0,
        "error": None,
    }
    fields.update(overrides)
    return Observation(**fields)


class TestSummarizeArm:
    def test_scores_strata_and_fallback_rate(self) -> None:
        run = [
            make_observation(0, "groceries"),
            make_observation(1, "miscellaneous", audit_source="ai_fallback", fallback_reason="api_error"),
        ]
        summary = summarize_arm(ARMS["luna/low"], [run])
        assert summary.human_verified_total == 2
        assert summary.human_verified_correct == 1
        assert summary.fallback_rate == 0.5
        assert summary.fallback_reasons == {"api_error": 1}
        assert summary.flip_rate is None

    def test_flip_rate_counts_samples_that_changed_answer_between_repeats(self) -> None:
        run_a = [make_observation(0, "groceries"), make_observation(1, "groceries")]
        run_b = [make_observation(0, "groceries"), make_observation(1, "miscellaneous")]
        summary = summarize_arm(ARMS["luna/low"], [run_a, run_b])
        assert summary.flip_rate == 0.5


# --------------------------------------------------------------------------- #
# parse_arm_names
# --------------------------------------------------------------------------- #


class TestParseArmNames:
    def test_default_is_every_arm_in_canonical_order(self) -> None:
        assert parse_arm_names(None) == list(ARMS)

    def test_comma_and_space_separated_subsets_resolve_in_canonical_order(self) -> None:
        assert parse_arm_names(["luna/low,luna/none"]) == ["luna/none", "luna/low"]

    def test_unknown_arm_is_rejected(self) -> None:
        with pytest.raises(SystemExit, match="Unknown arm"):
            parse_arm_names(["luna/xhigh"])


# --------------------------------------------------------------------------- #
# PII — merchant data must not leak into the default report
# --------------------------------------------------------------------------- #


def build_pii_fixture() -> tuple[list[Sample], list[ArmSummary], dict[str, list[list[Observation]]], WinnerDecision]:
    samples = [make_sample(0, company=SENTINEL_MERCHANT, amount=1234.56, stratum="override_at_ingest")]
    runs = {"luna/low": [[make_observation(0, "groceries")]]}
    summaries = [summarize_arm(ARMS["luna/low"], runs["luna/low"])]
    return samples, summaries, runs, pick_winner(summaries)


class TestNoMerchantDataByDefault:
    def test_markdown_omits_merchant_and_amount_by_default(self) -> None:
        samples, summaries, _runs, decision = build_pii_fixture()
        markdown = format_markdown(
            summaries,
            decision,
            backend="sqlite (data/finance.db)",
            stratum_counts={"override_at_ingest": 1},
            selected_counts={"override_at_ingest": 1},
            samples=samples,
        )
        assert SENTINEL_MERCHANT not in markdown
        assert "1234.56" not in markdown

    def test_markdown_includes_merchant_with_show_rows(self) -> None:
        samples, summaries, _runs, decision = build_pii_fixture()
        markdown = format_markdown(
            summaries,
            decision,
            backend="sqlite (data/finance.db)",
            stratum_counts={"override_at_ingest": 1},
            selected_counts={"override_at_ingest": 1},
            samples=samples,
            show_rows=True,
        )
        assert SENTINEL_MERCHANT in markdown
        assert "1234.56" in markdown

    def test_json_report_omits_merchant_and_amount_by_default(self) -> None:
        samples, summaries, runs, decision = build_pii_fixture()
        report = build_report(
            summaries,
            runs,
            decision,
            backend="sqlite (data/finance.db)",
            stratum_counts={"override_at_ingest": 1},
            selected_counts={"override_at_ingest": 1},
            months=6,
            repeats=1,
            samples=samples,
        )
        serialized = json.dumps(report, default=str)
        assert SENTINEL_MERCHANT not in serialized
        assert "1234.56" not in serialized
        assert "rows" not in report
        # Rows are still addressable — by opaque handle only.
        assert report["observations"]["luna/low"][0][0]["sample_id"] == "id0000"

    def test_json_report_includes_merchant_with_show_rows(self) -> None:
        samples, summaries, runs, decision = build_pii_fixture()
        report = build_report(
            summaries,
            runs,
            decision,
            backend="sqlite (data/finance.db)",
            stratum_counts={"override_at_ingest": 1},
            selected_counts={"override_at_ingest": 1},
            months=6,
            repeats=1,
            samples=samples,
            show_rows=True,
        )
        assert report["rows"][0]["company"] == SENTINEL_MERCHANT
        assert report["rows"][0]["amount"] == 1234.56
