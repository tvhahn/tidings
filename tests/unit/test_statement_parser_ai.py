"""Tests for the AI fallback statement parser (src/finance/statement_parser_ai).

All fixtures are synthetic ("Maple Trust Bank") — no real statement data.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from src.finance.ai_cli import DEFAULT_OPENAI_CHAT_MODEL, extract_json
from src.finance.statement_parser_ai import (
    StatementAIError,
    _amount_in_text,
    _sanitize_account_type,
    _sanitize_institution,
    _valid_date,
    _validate_transactions,
    build_prompt,
    parse_statement_with_ai,
    resolve_ai_statement_provider,
)

# Synthetic pdfplumber-style page text for a fictional bank.
FAKE_PAGE_TEXT = """MapleTrustBank
Your account statement
From March 1, 2026 to March 31, 2026
date description withdrawals deposits balance
Mar 3 INTERAC PURCHASE COFFEE CO 4.50 1,995.50
Mar 10 PAYROLL DEPOSIT ACME LTD 2,150.00 4,145.50
Mar 21 E-TRANSFER SENT 300.00 3,845.50
Closing balance 3,845.50
"""

VALID_AI_REPLY = {
    "institution": "Maple Trust Bank",
    "account_type": "chequing",
    "period_start": "2026-03-01",
    "period_end": "2026-03-31",
    "transactions": [
        {
            "date": "2026-03-03",
            "description": "INTERAC PURCHASE COFFEE CO",
            "amount": 4.50,
            "type": "withdrawal",
            "balance": 1995.50,
        },
        {
            "date": "2026-03-10",
            "description": "PAYROLL DEPOSIT ACME LTD",
            "amount": 2150.00,
            "type": "deposit",
            "balance": 4145.50,
        },
        {
            "date": "2026-03-21",
            "description": "E-TRANSFER SENT",
            "amount": 300.00,
            "type": "withdrawal",
            "balance": 3845.50,
        },
    ],
}


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"a": 1}', error_cls=StatementAIError) == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```', error_cls=StatementAIError) == {"a": 1}

    def test_prose_wrapped_json(self):
        assert extract_json('Here you go:\n{"a": 1}\nDone.', error_cls=StatementAIError) == {"a": 1}

    def test_no_json_raises(self):
        with pytest.raises(StatementAIError, match="no JSON object"):
            extract_json("I could not parse this statement.", error_cls=StatementAIError)

    def test_invalid_json_raises(self):
        with pytest.raises(StatementAIError, match="not valid JSON"):
            extract_json('{"a": }', error_cls=StatementAIError)

    def test_json_array_raises(self):
        with pytest.raises(StatementAIError, match="no JSON object"):
            extract_json("[1, 2]", error_cls=StatementAIError)


class TestSanitizers:
    def test_institution_passthrough(self):
        assert _sanitize_institution("Maple Trust Bank") == "Maple Trust Bank"

    def test_institution_strips_path_characters(self):
        assert _sanitize_institution("../etc/passwd") == "etcpasswd"

    def test_institution_non_string(self):
        assert _sanitize_institution(None) == "Unknown"
        assert _sanitize_institution(42) == "Unknown"

    def test_institution_empty_after_cleaning(self):
        assert _sanitize_institution("///") == "Unknown"

    def test_institution_truncates(self):
        assert len(_sanitize_institution("A" * 100)) == 40

    def test_account_type_known(self):
        assert _sanitize_account_type(" Chequing ") == "chequing"
        assert _sanitize_account_type("credit") == "credit"

    def test_account_type_unknown_defaults(self):
        assert _sanitize_account_type("brokerage") == "chequing"
        assert _sanitize_account_type(None) == "chequing"

    def test_valid_date(self):
        assert _valid_date("2026-03-01") == "2026-03-01"
        assert _valid_date("2026-13-01") is None
        assert _valid_date("03/01/2026") is None
        assert _valid_date(20260301) is None


class TestAmountInText:
    def test_plain(self):
        assert _amount_in_text(4.50, "COFFEE 4.50")

    def test_thousands_comma(self):
        assert _amount_in_text(2150.00, "PAYROLL 2,150.00")

    def test_absent(self):
        assert not _amount_in_text(99.99, "COFFEE 4.50")


class TestValidateTransactions:
    def test_happy_path(self):
        txns = _validate_transactions(VALID_AI_REPLY, FAKE_PAGE_TEXT)
        assert len(txns) == 3
        assert txns[0] == {
            "date": "2026-03-03",
            "description": "INTERAC PURCHASE COFFEE CO",
            "amount": 4.50,
            "type": "withdrawal",
            "balance": 1995.50,
        }

    def test_hallucinated_amount_fails_closed(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][1]["amount"] = 9999.99
        with pytest.raises(StatementAIError, match="do not appear in the statement text"):
            _validate_transactions(data, FAKE_PAGE_TEXT)

    def test_hallucinated_balance_dropped_not_fatal(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][0]["balance"] = 123456.78
        txns = _validate_transactions(data, FAKE_PAGE_TEXT)
        assert txns[0]["balance"] is None

    def test_missing_balance_ok(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][0]["balance"] = None
        assert _validate_transactions(data, FAKE_PAGE_TEXT)[0]["balance"] is None

    def test_invalid_type_rejected(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][0]["type"] = "debit"
        with pytest.raises(StatementAIError, match="invalid type"):
            _validate_transactions(data, FAKE_PAGE_TEXT)

    def test_invalid_date_rejected(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][0]["date"] = "Mar 3"
        with pytest.raises(StatementAIError, match="invalid date"):
            _validate_transactions(data, FAKE_PAGE_TEXT)

    def test_non_positive_amount_rejected(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][0]["amount"] = -4.50
        with pytest.raises(StatementAIError, match="non-positive"):
            _validate_transactions(data, FAKE_PAGE_TEXT)

    def test_empty_description_rejected(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][0]["description"] = "  "
        with pytest.raises(StatementAIError, match="no description"):
            _validate_transactions(data, FAKE_PAGE_TEXT)

    def test_no_transactions_rejected(self):
        with pytest.raises(StatementAIError, match="found no transactions"):
            _validate_transactions({"transactions": []}, FAKE_PAGE_TEXT)

    def test_description_whitespace_collapsed(self):
        data = json.loads(json.dumps(VALID_AI_REPLY))
        data["transactions"][0]["description"] = "INTERAC   PURCHASE\nCOFFEE CO"
        txns = _validate_transactions(data, FAKE_PAGE_TEXT)
        assert txns[0]["description"] == "INTERAC PURCHASE COFFEE CO"


class TestBuildPrompt:
    def test_includes_page_markers_and_schema(self):
        prompt = build_prompt(["page one text", "page two text"])
        assert "--- page 1 ---" in prompt
        assert "--- page 2 ---" in prompt
        assert '"transactions"' in prompt


class TestResolveProvider:
    @patch("src.finance.statement_parser_ai.get_config")
    def test_disabled_provider(self, mock_config):
        mock_config.return_value = {"document_parsing_provider": "disabled"}
        assert resolve_ai_statement_provider() is None

    @patch("src.finance.statement_parser_ai.shutil.which", return_value="/usr/bin/claude")
    @patch("src.finance.statement_parser_ai.get_config")
    def test_claude_cli_available(self, mock_config, _which):
        mock_config.return_value = {"document_parsing_provider": "claude_cli"}
        assert resolve_ai_statement_provider() == "claude_cli"

    @patch("src.finance.statement_parser_ai.shutil.which", return_value=None)
    @patch("src.finance.statement_parser_ai.get_config")
    def test_claude_cli_missing_binary(self, mock_config, _which):
        mock_config.return_value = {"document_parsing_provider": "claude_cli"}
        assert resolve_ai_statement_provider() is None


class TestParseStatementWithAI:
    def _run(self, **patches):
        return asyncio.run(parse_statement_with_ai(b"%PDF-fake"))

    @patch("src.finance.statement_parser_ai.resolve_ai_statement_provider", return_value=None)
    def test_no_provider_raises(self, _resolve):
        with pytest.raises(StatementAIError, match="No AI provider is available"):
            self._run()

    @patch("src.finance.statement_parser_ai.get_config", return_value={})
    @patch("src.finance.statement_parser_ai.invoke_text_provider")
    @patch("src.finance.statement_parser_ai._extract_pages_text", return_value=[FAKE_PAGE_TEXT])
    @patch("src.finance.statement_parser_ai.resolve_ai_statement_provider", return_value="claude_cli")
    def test_full_parse(self, _resolve, _extract, mock_invoke, _config):
        async def fake_invoke(provider, prompt, openai_client, **kwargs):
            return json.dumps(VALID_AI_REPLY)

        mock_invoke.side_effect = fake_invoke
        result = self._run()
        assert result.metadata == {
            "institution": "Maple Trust Bank",
            "account_type": "chequing",
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "transaction_count": 3,
            "parsed_with_ai": True,
        }
        assert len(result.transactions) == 3
        assert result.raw_descriptions[0] == "INTERAC PURCHASE COFFEE CO"
        assert len(result.cleaned_descriptions) == 3

    @patch("src.finance.statement_parser_ai._extract_pages_text", return_value=["short"])
    @patch("src.finance.statement_parser_ai.resolve_ai_statement_provider", return_value="claude_cli")
    def test_scanned_pdf_rejected(self, _resolve, _extract):
        with pytest.raises(StatementAIError, match="no extractable text"):
            self._run()

    @patch("src.finance.statement_parser_ai.get_config", return_value={})
    @patch("src.finance.statement_parser_ai._extract_pages_text", return_value=[FAKE_PAGE_TEXT])
    @patch("src.finance.statement_parser_ai.resolve_ai_statement_provider", return_value="openai")
    def test_openai_path_pins_chat_model_not_embeddings(self, _resolve, _extract, _config):
        # Regression: the openai statement path must pin a chat-capable model,
        # not fall back to the injected client's embedding default (which the
        # chat endpoint rejects) — this used to make every openai parse fail.
        client = MagicMock(name="openai_client")
        client.model = "text-embedding-3-small"
        response = MagicMock()
        response.choices[0].message.content = json.dumps(VALID_AI_REPLY)
        client.chat.return_value = response

        result = asyncio.run(parse_statement_with_ai(b"%PDF-fake", client))
        assert len(result.transactions) == 3
        # A concrete chat model is pinned per-call; the embedding default is
        # never used and the instance model is left untouched.
        assert client.chat.call_args.kwargs["model"] == DEFAULT_OPENAI_CHAT_MODEL
        assert client.model == "text-embedding-3-small"
