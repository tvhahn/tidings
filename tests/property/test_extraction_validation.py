"""Property tests for the extraction anti-hallucination contract.

`validate_extraction(amount_str, company, body)` must accept an extracted
amount/company pair ONLY when a rendering of the amount is genuinely a
substring of the body (and the company is genuinely present). These properties
generate cases by *deciding* embed/don't-embed up front, then assert that
acceptance follows iff the value was embedded.

Conventions follow tests/property/test_parser_invariants.py — `@given`,
`assume`, the `dev` profile (100 examples, 500ms deadline) from
tests/property/conftest.py. The helper under test is pure and fast.
"""

from __future__ import annotations

import string

from hypothesis import assume, given
from hypothesis import strategies as st

from src.finance.extractor import validate_extraction

# A "filler" alphabet for synthetic bodies that contains NO digits, no "$", and
# no ".", so a generated body never accidentally contains a rendering of the
# amount. This lets the don't-embed branch assert a guaranteed-absent amount.
_FILLER_ALPHABET = string.ascii_letters + " \t\n,()@/-"

# Company string for the embedded cases — kept simple and guaranteed-present.
_COMPANY = "TEST MERCHANT"


def _renderings(value: float, raw: str) -> set[str]:
    """All amount renderings validate_extraction will accept — mirrors the
    helper's candidate set, used to embed a guaranteed-matching string."""
    candidates: set[str] = {raw, f"{value:,.2f}", f"{value:.2f}"}
    if value == int(value):
        candidates.add(f"{int(value):,}")
        candidates.add(str(int(value)))
    rendered = {c for c in candidates if c}
    rendered |= {f"${c}" for c in list(rendered)}
    return rendered


# Positive decimal amounts as the model would emit them: digits with an optional
# 2-place decimal. Kept positive (the contract rejects <= 0 independently).
_amount_strings = st.builds(
    lambda whole, cents: f"{whole}.{cents:02d}",
    whole=st.integers(min_value=1, max_value=9_999_999),
    cents=st.integers(min_value=0, max_value=99),
)

_filler = st.text(alphabet=_FILLER_ALPHABET, max_size=200)


@given(amount_str=_amount_strings, prefix=_filler, suffix=_filler)
def test_embedded_amount_accepted(amount_str: str, prefix: str, suffix: str) -> None:
    """When a real rendering of the amount AND the company are present, accept."""
    body = f"{prefix} a purchase of ${amount_str} at {_COMPANY} {suffix}"
    assert validate_extraction(amount_str, _COMPANY, body) is True


@given(amount_str=_amount_strings, prefix=_filler, suffix=_filler)
def test_absent_amount_rejected(amount_str: str, prefix: str, suffix: str) -> None:
    """When NO rendering of the amount appears in the body, reject — even though
    the company is present."""
    body = f"{prefix} a purchase at {_COMPANY} {suffix}"
    # The filler alphabet has no digits/$/'.', so no rendering can sneak in.
    for rendering in _renderings(float(amount_str.lstrip("$").replace(",", "")), amount_str):
        assume(rendering not in body)
    assert validate_extraction(amount_str, _COMPANY, body) is False


@given(amount_str=_amount_strings, prefix=_filler, suffix=_filler)
def test_absent_company_rejected(amount_str: str, prefix: str, suffix: str) -> None:
    """Amount present, company absent → reject."""
    body = f"{prefix} a purchase of ${amount_str} was made {suffix}"
    assume(_COMPANY.casefold() not in " ".join(body.split()).casefold())
    assert validate_extraction(amount_str, _COMPANY, body) is False


@given(
    amount_str=_amount_strings,
    embed=st.booleans(),
    prefix=_filler,
    suffix=_filler,
)
def test_accept_iff_amount_embedded(amount_str: str, embed: bool, prefix: str, suffix: str) -> None:
    """The core invariant: accept iff a rendering of the amount is genuinely a
    substring (company always present)."""
    value = float(amount_str.lstrip("$").replace(",", ""))
    if embed:
        body = f"{prefix} of ${amount_str} at {_COMPANY} {suffix}"
        expected = True
    else:
        body = f"{prefix} at {_COMPANY} {suffix}"
        for rendering in _renderings(value, amount_str):
            assume(rendering not in body)
        expected = False
    assert validate_extraction(amount_str, _COMPANY, body) is expected


@given(
    amount_str=_amount_strings,
    company=st.text(alphabet=string.ascii_letters + " ", min_size=0, max_size=10),
)
def test_empty_or_whitespace_company_rejected(amount_str: str, company: str) -> None:
    """A company that collapses to empty is always rejected, regardless of amount."""
    assume(not company.strip())
    body = f"a purchase of ${amount_str} happened"
    assert validate_extraction(amount_str, company, body) is False
