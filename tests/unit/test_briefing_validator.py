"""Unit tests for the briefing figure validator.

Covers extraction across every real figure format, the documented rounding /
sign-dropping / percentage matching rules, and the deliberate blind spots
(multipliers, bare numbers, code fences).
"""

from __future__ import annotations

from src.finance.briefing_validator import (
    collect_context_numbers,
    extract_figures,
    validate_briefing,
)


class TestExtractFigures:
    def test_extracts_all_dollar_formats(self) -> None:
        md = "Spending reached $12,480, with $2,950.00 to the mortgage and $96 on Amazon."
        raws = [f.raw for f in extract_figures(md) if f.kind == "dollar"]
        assert raws == ["$12,480", "$2,950.00", "$96"]

    def test_parses_dollar_values(self) -> None:
        md = "totals: $12,480 and $2,950.00 and $1,240.00"
        by_raw = {f.raw: f.value for f in extract_figures(md)}
        assert by_raw["$12,480"] == 12480.0
        assert by_raw["$2,950.00"] == 2950.0
        assert by_raw["$1,240.00"] == 1240.0

    def test_extracts_percentages(self) -> None:
        md = "up 12.0% from April, 132.4% over budget, and 19.6% ahead of pace"
        pcts = [(f.raw, f.value) for f in extract_figures(md) if f.kind == "percent"]
        assert pcts == [("12.0%", 12.0), ("132.4%", 132.4), ("19.6%", 19.6)]

    def test_figures_in_document_order(self) -> None:
        md = "5.0% then $10 then 2.0% then $20"
        raws = [f.raw for f in extract_figures(md)]
        assert raws == ["5.0%", "$10", "2.0%", "$20"]

    def test_snippet_surrounds_figure(self) -> None:
        md = "Groceries reached $1,540 this month, up sharply from the prior baseline."
        fig = next(f for f in extract_figures(md) if f.raw == "$1,540")
        assert "$1,540" in fig.snippet
        assert "Groceries reached" in fig.snippet
        assert "\n" not in fig.snippet

    def test_multipliers_not_extracted(self) -> None:
        # 6x uses the multiplication-sign glyph real briefings print (\u00d7).
        md = "Miscellaneous is nearly 6\u00d7 the $150 monthly target, roughly 10x normal."
        figs = extract_figures(md)
        assert [f.raw for f in figs] == ["$150"]

    def test_bare_numbers_years_dates_not_extracted(self) -> None:
        md = "In 2026-2027, across 9 transactions on May 14, you spent $500."
        assert [f.raw for f in extract_figures(md)] == ["$500"]

    def test_figures_inside_code_fence_skipped(self) -> None:
        md = "Real total $1,000.\n```\ncode literal $9,999 and 88.8%\n```\nAnd 5.0% real."
        raws = [f.raw for f in extract_figures(md)]
        assert raws == ["$1,000", "5.0%"]

    def test_empty_briefing(self) -> None:
        assert extract_figures("") == []


class TestCollectContextNumbers:
    def test_collects_nested_numeric_leaves(self) -> None:
        ctx = {"a": 10, "b": {"c": 20.0}, "d": [30, {"e": 40.5}]}
        forms = collect_context_numbers(ctx)
        assert "10.00" in forms
        assert "20.00" in forms
        assert "30.00" in forms
        assert "40.50" in forms

    def test_booleans_excluded(self) -> None:
        # True/False are int subclasses but must not register as 1/0 figures.
        forms = collect_context_numbers({"flag": True, "other": False})
        assert "1.00" not in forms
        assert "0.00" not in forms

    def test_absolute_value_form_present(self) -> None:
        forms = collect_context_numbers({"delta": -1320.0})
        assert "1320.00" in forms

    def test_rounding_forms_present(self) -> None:
        forms = collect_context_numbers({"total": 12480.09})
        assert "12480.09" in forms  # 2dp
        assert "12480.00" in forms  # 0dp — briefing prints $12,480

    def test_figures_inside_string_leaves_count_as_data(self) -> None:
        # Anomaly reason strings carry figures the model is encouraged to quote —
        # a "57%" that appears only inside a reason string must still register as data.
        ctx = {"anomalies": [{"reason": "roughly 57% below the 6-month average of $445"}]}
        forms = collect_context_numbers(ctx)
        assert "57.00" in forms
        assert "445.00" in forms

    def test_plain_prose_words_do_not_register(self) -> None:
        forms = collect_context_numbers({"note": "no figures here, just words"})
        assert forms == set()


class TestValidateBriefing:
    def test_matched_figures_across_formats(self) -> None:
        ctx = {
            "current_month": {"total_spending": 12480.09},
            "pace": {"categories": [{"month_actual": 2950.00}]},
            "delta": {"percent": 12.0},
        }
        md = "You spent $12,480, mortgage $2,950.00, up 12.0%."
        result = validate_briefing(md, ctx)
        assert result.ok is True
        assert result.total == 3
        assert result.matched_count == 3
        assert result.unmatched_count == 0

    def test_hallucinated_figure_flagged(self) -> None:
        ctx = {"total_spending": 12480.09}
        md = "You spent $12,480, of which $9,999 went to a category that never existed."
        result = validate_briefing(md, ctx)
        assert result.ok is False
        assert result.unmatched_count == 1
        assert [v.figure.raw for v in result.unmatched] == ["$9,999"]

    def test_sign_dropped_variance_matches(self) -> None:
        # Context carries a signed negative variance; briefing prints it unsigned.
        ctx = {"pace": {"categories": [{"variance_amount": -1320.0}]}}
        result = validate_briefing("Groceries came in $1,320 under target.", ctx)
        assert result.ok is True

    def test_integer_rounded_presentation_matches(self) -> None:
        ctx = {"total": 12480.09}
        assert validate_briefing("Total was $12,480.", ctx).ok is True

    def test_percentage_rounds_to_one_decimal(self) -> None:
        # A context 11.95 rounds to the printed 12.0%.
        ctx = {"delta": {"percent": 11.95}}
        assert validate_briefing("Spending rose 12.0%.", ctx).ok is True

    def test_percentage_exact_match(self) -> None:
        ctx = {"pace": {"categories": [{"variance_pct": 132.4}]}}
        assert validate_briefing("Dining is 132.4% over budget.", ctx).ok is True

    def test_figure_reported_with_snippet(self) -> None:
        ctx = {"total": 100.0}
        result = validate_briefing("An invented $8,888 appears in this sentence.", ctx)
        (verdict,) = result.unmatched
        assert verdict.figure.raw == "$8,888"
        assert "invented $8,888 appears" in verdict.figure.snippet

    def test_empty_briefing_is_ok(self) -> None:
        result = validate_briefing("", {"total": 100.0})
        assert result.ok is True
        assert result.total == 0

    def test_multiplier_not_validated(self) -> None:
        # A multiplier ("6x", glyph \u00d7) is not a figure, so it never counts as
        # matching context leaf.
        ctx = {"target": 150.0}
        result = validate_briefing("Miscellaneous is nearly 6\u00d7 the $150 target.", ctx)
        assert result.ok is True
        assert result.total == 1

    def test_sidecar_dict_shape(self) -> None:
        ctx = {"total": 12480.09}
        result = validate_briefing("Real $12,480 and fake $1.", ctx)
        payload = result.to_sidecar_dict()
        assert payload["ok"] is False
        assert payload["summary"] == {"total": 2, "matched": 1, "unmatched": 1}
        assert len(payload["figures"]) == 2
        fake = next(f for f in payload["figures"] if f["raw"] == "$1")
        assert fake["matched"] is False
        assert fake["kind"] == "dollar"
        assert fake["value"] == 1.0

    def test_zero_variance_matches_zero_figure(self) -> None:
        # -0.00 canonicalisation: a 0.0 leaf matches a printed $0.
        ctx = {"pace": {"categories": [{"variance_amount": 0.0}]}}
        assert validate_briefing("Taxes are $0 this month.", ctx).ok is True
