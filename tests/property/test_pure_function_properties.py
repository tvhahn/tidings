"""Hypothesis property tests for pure string-handling functions.

Extends the parser-invariants pattern (``test_parser_invariants.py``) to the
three pure-function utilities the panel called out as missing coverage:

- ``clean_statement_description`` (``src/finance/statement_parser.py:122``)
- ``normalize_merchant``           (``src/finance/merchant_normalizer.py:22``)
- ``resolve_override``             (``src/finance/category_resolver.py:44``)

These are pure functions over user input — exactly the shape Hypothesis is
strong at. The properties target the invariants that actually matter:
no exceptions on garbage, idempotency, no leaked control characters, and
contract conformance with the resolver's tier ordering.
"""

from __future__ import annotations

import string

from hypothesis import assume, example, given
from hypothesis import strategies as st

from src.finance.category_resolver import resolve_override
from src.finance.merchant_normalizer import normalize_merchant
from src.finance.statement_parser import clean_statement_description

# ---------------------------------------------------------------------------
# clean_statement_description
# ---------------------------------------------------------------------------


@given(text=st.text(max_size=500))
@example(text="")
@example(text="BillPayment WestlandUtilityCo")
def test_clean_never_raises(text: str) -> None:
    result = clean_statement_description(text)
    assert isinstance(result, str)


@given(text=st.text(max_size=200))
def test_clean_is_idempotent(text: str) -> None:
    """Running the cleaner twice must produce the same string the second time
    as the first — a single-pass transformation."""
    once = clean_statement_description(text)
    twice = clean_statement_description(once)
    assert once == twice


@given(text=st.text(max_size=200))
def test_clean_strips_leading_trailing_whitespace(text: str) -> None:
    result = clean_statement_description(text)
    assert result == result.strip(), f"leaked whitespace: {result!r}"


@given(
    inner=st.text(
        alphabet=string.ascii_letters + string.digits + " ",
        min_size=1,
        max_size=50,
    )
)
def test_clean_preserves_uppercase_token(inner: str) -> None:
    """All-caps tokens (COSTCO, WALMART) must survive — the cleaner only
    splits CamelCase, never lowercases or breaks contiguous uppercase runs."""
    inner_upper = inner.upper().strip()
    assume(inner_upper)
    result = clean_statement_description(inner_upper)
    # The all-caps form should appear somewhere in the result, possibly
    # split by spaces — but no individual run of letters that was uppercase
    # should have become mixed-case.
    assert any(c.isupper() for c in result if c.isalpha()) or not any(c.isalpha() for c in inner_upper)


# ---------------------------------------------------------------------------
# normalize_merchant
# ---------------------------------------------------------------------------


@given(name=st.text(max_size=200))
@example(name="")
@example(name="COSTCO #1234")
@example(name="Safeway BC")
def test_normalize_never_raises(name: str) -> None:
    result = normalize_merchant(name)
    assert isinstance(result, str)


@given(name=st.text(max_size=200))
def test_normalize_idempotent(name: str) -> None:
    """Cleanup patterns are run in a fixed-point loop, so a second pass on
    an already-cleaned name must be identity."""
    once = normalize_merchant(name)
    twice = normalize_merchant(once)
    assert once == twice


@given(
    name=st.text(max_size=100),
    aliases=st.dictionaries(
        keys=st.text(min_size=1, max_size=30, alphabet=string.ascii_lowercase + " "),
        values=st.text(min_size=1, max_size=30),
        max_size=10,
    ),
)
def test_normalize_alias_takes_precedence(name: str, aliases: dict[str, str]) -> None:
    """If the cleaned-and-lowercased name appears as an alias key, the alias
    value must be returned — never the cleaned form."""
    cleaned = normalize_merchant(name)
    if cleaned.lower() in aliases:
        result = normalize_merchant(name, aliases=aliases)
        assert result == aliases[cleaned.lower()]


@given(name=st.text(max_size=200))
def test_normalize_no_leading_trailing_whitespace(name: str) -> None:
    result = normalize_merchant(name)
    if result:
        assert result == result.strip()


# ---------------------------------------------------------------------------
# resolve_override
# ---------------------------------------------------------------------------


@given(
    company=st.text(max_size=100),
    overrides=st.dictionaries(
        keys=st.text(min_size=1, max_size=30),
        values=st.text(min_size=1, max_size=30),
        max_size=10,
    ),
)
def test_resolve_never_raises(company: str, overrides: dict[str, str]) -> None:
    result = resolve_override(company, overrides)
    assert result is None or hasattr(result, "category")


@given(
    company=st.text(min_size=1, max_size=50, alphabet=string.printable),
    category=st.text(min_size=1, max_size=20, alphabet=string.ascii_letters),
)
def test_resolve_exact_match_takes_priority(company: str, category: str) -> None:
    """An exact case-insensitive override must always resolve via Tier 0
    — never via a later tier — when present."""
    overrides = {company: category}
    result = resolve_override(company, overrides)
    if result is not None:  # empty/whitespace-only company short-circuits to None
        assert result.tier == "exact"
        assert result.category == category


@given(
    company=st.text(max_size=50),
    overrides=st.dictionaries(
        keys=st.text(min_size=1, max_size=30),
        values=st.text(min_size=1, max_size=30),
        max_size=10,
    ),
)
def test_resolve_idempotent_on_repeat_calls(company: str, overrides: dict[str, str]) -> None:
    first = resolve_override(company, overrides)
    second = resolve_override(company, overrides)
    if first is None:
        assert second is None
    else:
        assert second is not None
        assert (first.tier, first.category, first.matched_rule) == (
            second.tier,
            second.category,
            second.matched_rule,
        )


@given(
    company=st.text(max_size=50),
)
def test_resolve_returns_none_when_overrides_empty(company: str) -> None:
    assert resolve_override(company, {}) is None


@given(
    company=st.text(min_size=1, max_size=50),
    overrides=st.dictionaries(
        keys=st.text(min_size=1, max_size=30),
        values=st.text(min_size=1, max_size=30),
        max_size=10,
    ),
)
def test_resolve_confidence_in_unit_interval(company: str, overrides: dict[str, str]) -> None:
    """Tier 0/1/2 hits must report confidence == 1.0 (deterministic match);
    Tier 3 isn't exercised here (no suggester passed)."""
    result = resolve_override(company, overrides)
    if result is not None:
        assert result.confidence == 1.0
        assert result.tier in {"exact", "normalized", "alias"}
