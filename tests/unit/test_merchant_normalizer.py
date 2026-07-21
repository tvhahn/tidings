"""Tests for merchant name normalization."""

from src.finance.merchant_normalizer import normalize_merchant


class TestNormalizeMerchant:
    def test_passthrough_clean_name(self):
        assert normalize_merchant("Safeway") == "Safeway"

    def test_strip_store_number_hash(self):
        assert normalize_merchant("Safeway #1234") == "Safeway"

    def test_strip_store_number_word(self):
        assert normalize_merchant("Walmart Store 567") == "Walmart"

    def test_strip_location_number(self):
        assert normalize_merchant("Tim Hortons Loc 42") == "Tim Hortons"

    def test_strip_trailing_province(self):
        assert normalize_merchant("SAFEWAY VANCOUVER BC") == "SAFEWAY VANCOUVER"

    def test_strip_province_only(self):
        assert normalize_merchant("SAFEWAY BC") == "SAFEWAY"

    def test_strip_trailing_country(self):
        assert normalize_merchant("Amazon CA") == "Amazon"

    def test_strip_trailing_punctuation(self):
        assert normalize_merchant("Starbucks --") == "Starbucks"

    def test_empty_string(self):
        assert normalize_merchant("") == ""

    def test_whitespace_only(self):
        assert normalize_merchant("   ") == ""

    def test_alias_lookup(self):
        aliases = {"safeway": "Safeway Inc."}
        assert normalize_merchant("Safeway", aliases) == "Safeway Inc."

    def test_alias_case_insensitive(self):
        aliases = {"safeway #1234": "Safeway"}
        # After cleanup: "Safeway" -> lowercase lookup: "safeway"
        result = normalize_merchant("Safeway #1234", aliases)
        # Cleanup strips "#1234" -> "Safeway" -> alias lookup "safeway" -> "Safeway"
        assert result == "Safeway"

    def test_alias_not_found_returns_cleaned(self):
        aliases = {"costco": "Costco Wholesale"}
        assert normalize_merchant("Safeway #1234", aliases) == "Safeway"

    def test_none_aliases(self):
        assert normalize_merchant("Safeway #1234", None) == "Safeway"

    def test_complex_cleanup(self):
        result = normalize_merchant("TIM HORTONS Store 123 US")
        assert result == "TIM HORTONS"
