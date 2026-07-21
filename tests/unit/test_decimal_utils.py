"""Unit tests for the shared Decimal <-> float marshalling helpers."""

from decimal import Decimal

import pytest

from src.finance.decimal_utils import (
    decimals_to_floats,
    floats_to_decimals,
    to_decimal,
)


class TestToDecimal:
    """Scalar float->Decimal boundary guard used by DynamoDB writers."""

    def test_float_becomes_decimal_via_str(self) -> None:
        result = to_decimal(0.1)
        assert result == Decimal("0.1")
        assert isinstance(result, Decimal)
        # str()-based construction avoids the binary-float artifact that
        # Decimal(0.1) would produce.
        assert result == Decimal(str(0.1))

    @pytest.mark.parametrize(
        "value",
        [7, "text", None, True, Decimal("3.5"), [1.0], {"a": 1.0}],
    )
    def test_non_float_passes_through_unchanged(self, value: object) -> None:
        # Identity for non-floats: containers are NOT recursed by the scalar guard.
        assert to_decimal(value) is value

    def test_bool_is_not_treated_as_float(self) -> None:
        assert to_decimal(True) is True


class TestFloatsToDecimals:
    """Recursive float->Decimal conversion for DynamoDB payloads."""

    def test_scalar_float(self) -> None:
        result = floats_to_decimals(99.99)
        assert result == Decimal("99.99")
        assert result == Decimal(str(99.99))
        assert isinstance(result, Decimal)

    def test_nested_dict_and_list(self) -> None:
        obj = {"a": 1.5, "b": {"c": [2.5, 3.0]}, "d": "x", "e": 4}
        result = floats_to_decimals(obj)
        assert result == {
            "a": Decimal(str(1.5)),
            "b": {"c": [Decimal(str(2.5)), Decimal(str(3.0))]},
            "d": "x",
            "e": 4,
        }
        assert isinstance(result["b"]["c"][0], Decimal)

    def test_non_float_scalars_pass_through(self) -> None:
        assert floats_to_decimals("s") == "s"
        assert floats_to_decimals(7) == 7
        assert floats_to_decimals(None) is None

    def test_empty_containers(self) -> None:
        assert floats_to_decimals({}) == {}
        assert floats_to_decimals([]) == []

    def test_str_based_construction(self) -> None:
        # Confirms floats route through str() rather than Decimal(float),
        # which is the load-bearing money-precision boundary.
        flt = 4.5
        assert floats_to_decimals(flt) == Decimal(str(flt))


class TestDecimalsToFloats:
    """Recursive Decimal->float conversion for JSON-safe output."""

    def test_scalar_decimal(self) -> None:
        result = decimals_to_floats(Decimal("4.50"))
        assert result == 4.5
        assert isinstance(result, float)

    def test_nested_dict_list_and_tuple(self) -> None:
        out = decimals_to_floats({"a": [Decimal(1)], "b": (Decimal(2), 3)})
        assert out == {"a": [1.0], "b": (2.0, 3)}
        # Tuple identity is preserved (not coerced to a list).
        assert isinstance(out["b"], tuple)
        assert isinstance(out["a"], list)

    def test_tuple_stays_tuple(self) -> None:
        out = decimals_to_floats((Decimal(1), Decimal(2)))
        assert out == (1.0, 2.0)
        assert isinstance(out, tuple)

    def test_non_decimal_passes_through(self) -> None:
        assert decimals_to_floats("x") == "x"
        assert decimals_to_floats(7) == 7
        assert decimals_to_floats(None) is None

    def test_empty_containers(self) -> None:
        assert decimals_to_floats({}) == {}
        assert decimals_to_floats([]) == []


class TestRoundTrip:
    """The two recursive helpers are inverse operations on numeric leaves."""

    def test_floats_to_decimals_then_back(self) -> None:
        original = {"total": 12.5, "items": [1.25, 2.75], "label": "food"}
        as_decimal = floats_to_decimals(original)
        assert decimals_to_floats(as_decimal) == original
