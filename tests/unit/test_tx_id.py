"""Tests for the tx_id surrogate-id helpers."""

from __future__ import annotations

import pytest

from src.finance.tx_id import composite_from_tx_id, tx_id_from_composite


class TestRoundTrip:
    @pytest.mark.parametrize(
        ("fwd", "dfn"),
        [
            ("alerts@example.com", "2026.04.15_14.32_rbc-purchase.eml"),
            ("user.with+plus@gmail.com", "2026.01.01_00.00_first.eml"),
            ("a@b.co", "x.eml"),
            (
                "very-long-address-to-test-encoding@subdomain.tidings.example.com",
                "2026.04.30_23.59_extra-long-filename-with-dashes.eml",
            ),
        ],
    )
    def test_round_trip(self, fwd: str, dfn: str) -> None:
        tx_id = tx_id_from_composite(fwd, dfn)
        assert composite_from_tx_id(tx_id) == (fwd, dfn)

    def test_id_is_url_safe(self) -> None:
        tx_id = tx_id_from_composite("alerts@example.com", "2026.04.15_14.32_rbc.eml")
        assert all(c.isalnum() or c in "-_" for c in tx_id)
        assert "/" not in tx_id
        assert "+" not in tx_id
        assert "=" not in tx_id

    def test_deterministic(self) -> None:
        a = tx_id_from_composite("alerts@example.com", "2026.04.15_14.32_rbc.eml")
        b = tx_id_from_composite("alerts@example.com", "2026.04.15_14.32_rbc.eml")
        assert a == b

    def test_distinct_inputs_distinct_ids(self) -> None:
        a = tx_id_from_composite("alerts@example.com", "2026.04.15_14.32_rbc.eml")
        b = tx_id_from_composite("alerts@example.com", "2026.04.15_14.33_rbc.eml")
        assert a != b


class TestDecodeFailures:
    def test_garbage_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid tx_id"):
            composite_from_tx_id("!!!not-base64!!!")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid tx_id"):
            composite_from_tx_id("")

    def test_decoded_without_separator_raises(self) -> None:
        # Encoded "no-separator" → no `|` in the decoded bytes.
        import base64 as _b64

        bad = _b64.urlsafe_b64encode(b"no-separator-here").rstrip(b"=").decode()
        with pytest.raises(ValueError, match="separator"):
            composite_from_tx_id(bad)

    def test_decoded_with_empty_part_raises(self) -> None:
        import base64 as _b64

        bad = _b64.urlsafe_b64encode(b"|missing-fwd").rstrip(b"=").decode()
        with pytest.raises(ValueError, match="invalid tx_id"):
            composite_from_tx_id(bad)
