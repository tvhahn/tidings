"""AI receipt parser — src/finance/receipt_parser_ai.py.

``validate_receipt_parse`` is pure and enumerable — its table is the contract.
Provider routing is exercised with mocks (no real AI, no real files where a byte
oracle isn't needed).
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.finance.ai_cli import DEFAULT_OPENAI_CHAT_MODEL
from src.finance.receipt_parser_ai import (
    LINE_ITEM_SUM_TOL,
    ReceiptAIError,
    parse_receipt,
    validate_receipt_parse,
)

# Text long enough to clear _MIN_TEXT_CHARS (200) and carry the verbatim total.
_PDF_TEXT = "BOOSTER JUICE\n" + ("filler line to pad the receipt text oracle\n" * 8) + "TOTAL 42.50\n"


def _valid() -> dict[str, Any]:
    return {"merchant": "Booster Juice", "date": "2026-02-15", "total": 42.50}


class TestValidateHardFailures:
    def test_missing_merchant_raises(self) -> None:
        data = _valid()
        data["merchant"] = "  "
        with pytest.raises(ReceiptAIError, match="merchant"):
            validate_receipt_parse(data, None)

    def test_bad_date_raises(self) -> None:
        data = _valid()
        data["date"] = "15/02/2026"
        with pytest.raises(ReceiptAIError, match="YYYY-MM-DD"):
            validate_receipt_parse(data, None)

    def test_impossible_date_raises(self) -> None:
        data = _valid()
        data["date"] = "2026-02-30"
        with pytest.raises(ReceiptAIError, match="real date"):
            validate_receipt_parse(data, None)

    def test_zero_total_raises(self) -> None:
        data = _valid()
        data["total"] = 0
        with pytest.raises(ReceiptAIError, match="positive"):
            validate_receipt_parse(data, None)

    def test_nonnumeric_total_raises(self) -> None:
        data = _valid()
        data["total"] = "free"
        with pytest.raises(ReceiptAIError, match="not a number"):
            validate_receipt_parse(data, None)


class TestValidateLineItems:
    def test_line_items_reconcile_kept(self) -> None:
        data = _valid()
        data["tax"] = 2.50
        data["line_items"] = [
            {"description": "Smoothie", "amount": 20.00},
            {"description": "Bowl", "amount": 20.00},
        ]  # 20 + 20 + tax 2.50 = 42.50
        result = validate_receipt_parse(data, None)
        assert len(result["line_items"]) == 2

    def test_line_items_off_by_more_than_tol_dropped(self) -> None:
        data = _valid()
        data["line_items"] = [
            {"description": "Smoothie", "amount": 20.00},
            {"description": "Bowl", "amount": 20.00},
        ]  # 40.00 vs 42.50, off by 2.50 > tol -> dropped
        result = validate_receipt_parse(data, None)
        assert "line_items" not in result
        # merchant/date/total survive.
        assert result["merchant"] == "Booster Juice"
        assert result["total"] == 42.50

    def test_tax_and_tip_included_in_sum(self) -> None:
        data = _valid()
        data["tax"] = 1.00
        data["tip"] = 1.50
        data["line_items"] = [{"description": "Meal", "amount": 40.00}]  # 40 + 1 + 1.5 = 42.50
        result = validate_receipt_parse(data, None)
        assert "line_items" in result

    def test_within_tol_boundary_kept(self) -> None:
        data = _valid()
        # 42.50 target; items sum to 42.46, off by 0.04 < 0.05 tol.
        data["line_items"] = [{"description": "Meal", "amount": 42.46}]
        result = validate_receipt_parse(data, None)
        assert "line_items" in result
        assert LINE_ITEM_SUM_TOL == 0.05

    def test_malformed_item_drops_all(self) -> None:
        data = _valid()
        data["line_items"] = [{"description": "Meal", "amount": "n/a"}]
        result = validate_receipt_parse(data, None)
        assert "line_items" not in result


class TestTextOracle:
    def test_text_pdf_requires_verbatim_total(self) -> None:
        data = _valid()
        data["total"] = 99.99  # not in the text
        with pytest.raises(ReceiptAIError, match="does not appear"):
            validate_receipt_parse(data, _PDF_TEXT)

    def test_text_pdf_total_present_passes(self) -> None:
        result = validate_receipt_parse(_valid(), _PDF_TEXT)
        assert result["total"] == 42.50

    def test_image_path_skips_text_oracle(self) -> None:
        data = _valid()
        data["total"] = 99.99  # no oracle for images
        result = validate_receipt_parse(data, None)
        assert result["total"] == 99.99


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------


def _reply(total: float = 42.50) -> str:
    return '{"merchant": "Booster Juice", "date": "2026-02-15", "total": ' + f"{total}" + "}"


def _image_file(tmp_path: Any) -> str:
    path = tmp_path / "receipt.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())
    return str(path)


class TestProviderRouting:
    @pytest.fixture(autouse=True)
    def _stub_config(self) -> Any:
        # parse_receipt reads document_parsing_model / _reasoning_effort from
        # config; stub it so routing tests don't touch the real data/config.json
        # (empty dict → both None → openai falls back to the default chat model).
        with patch("src.finance.receipt_parser_ai.get_config", return_value={}):
            yield

    def test_openai_image_builds_multimodal_message(self, tmp_path: Any) -> None:
        path = _image_file(tmp_path)
        client = MagicMock(name="api_client")
        client.model = "text-embedding-3-small"
        response = MagicMock()
        response.choices[0].message.content = _reply()
        client.chat.return_value = response

        with patch(
            "src.finance.receipt_parser_ai.resolve_ai_statement_provider",
            return_value="openai",
        ):
            import asyncio

            result = asyncio.run(parse_receipt(path, "image/jpeg", client))

        messages = client.chat.call_args.args[0]
        content = messages[0]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert result["provenance"]["model"] == DEFAULT_OPENAI_CHAT_MODEL
        assert result["provenance"]["provider"] == "openai"
        # The chat model is pinned per-call via kwarg, not by mutating the client.
        assert client.chat.call_args.kwargs["model"] == DEFAULT_OPENAI_CHAT_MODEL
        assert client.model == "text-embedding-3-small"

    def test_openai_text_pins_chat_model(self, tmp_path: Any) -> None:
        # Regression: the text-PDF path must pin a chat-capable model, not fall
        # back to the injected client's default (an embedding model the chat
        # endpoint rejects, which used to make every text-PDF parse fail).
        path = tmp_path / "receipt.pdf"
        path.write_bytes(b"%PDF-1.4 pretend")
        client = MagicMock(name="api_client")
        client.model = "text-embedding-3-small"
        response = MagicMock()
        response.choices[0].message.content = _reply()
        client.chat.return_value = response

        with (
            patch(
                "src.finance.receipt_parser_ai.resolve_ai_statement_provider",
                return_value="openai",
            ),
            patch(
                "src.finance.receipt_parser_ai._extract_pdf_text",
                return_value=_PDF_TEXT,
            ),
        ):
            import asyncio

            result = asyncio.run(parse_receipt(str(path), "application/pdf", client))

        assert client.chat.call_args.kwargs["model"] == DEFAULT_OPENAI_CHAT_MODEL
        # The default embedding model was never used and never mutated.
        assert client.model == "text-embedding-3-small"
        assert result["provenance"]["model"] == DEFAULT_OPENAI_CHAT_MODEL

    def test_codex_image_passes_image_paths(self, tmp_path: Any) -> None:
        path = _image_file(tmp_path)
        with (
            patch(
                "src.finance.receipt_parser_ai.resolve_ai_statement_provider",
                return_value="codex",
            ),
            patch(
                "src.finance.receipt_parser_ai.run_cli_provider",
                new=AsyncMock(name="run_cli_provider", return_value=_reply()),
            ) as mock_cli,
        ):
            import asyncio

            asyncio.run(parse_receipt(path, "image/jpeg", None))
        assert mock_cli.call_args.kwargs["image_paths"] == [path]

    def test_gemini_image_raises(self, tmp_path: Any) -> None:
        path = _image_file(tmp_path)
        with patch(
            "src.finance.receipt_parser_ai.resolve_ai_statement_provider",
            return_value="gemini_cli",
        ):
            import asyncio

            with pytest.raises(ReceiptAIError, match="Gemini"):
                asyncio.run(parse_receipt(path, "image/jpeg", None))

    def test_scanned_pdf_advises_photo(self, tmp_path: Any) -> None:
        # A PDF whose extracted text is below _MIN_TEXT_CHARS.
        path = tmp_path / "scan.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        with (
            patch(
                "src.finance.receipt_parser_ai.resolve_ai_statement_provider",
                return_value="openai",
            ),
            patch(
                "src.finance.receipt_parser_ai._extract_pdf_text",
                return_value="too short",
            ),
        ):
            import asyncio

            with pytest.raises(ReceiptAIError, match="take a photo"):
                asyncio.run(parse_receipt(str(path), "application/pdf", MagicMock()))

    def test_no_provider_raises(self, tmp_path: Any) -> None:
        path = _image_file(tmp_path)
        with patch(
            "src.finance.receipt_parser_ai.resolve_ai_statement_provider",
            return_value=None,
        ):
            import asyncio

            with pytest.raises(ReceiptAIError, match="No AI provider"):
                asyncio.run(parse_receipt(path, "image/jpeg", None))

    def test_provenance_stamp_fields(self, tmp_path: Any) -> None:
        path = _image_file(tmp_path)
        with (
            patch(
                "src.finance.receipt_parser_ai.resolve_ai_statement_provider",
                return_value="codex",
            ),
            patch(
                "src.finance.receipt_parser_ai.run_cli_provider",
                new=AsyncMock(return_value=_reply()),
            ),
        ):
            import asyncio

            result = asyncio.run(parse_receipt(path, "image/jpeg", None))
        prov = result["provenance"]
        assert prov["method"] == "ai_receipt"
        assert prov["provider"] == "codex"
        assert prov["schema_version"] == 1
        assert "parsed_at" in prov


class TestChatModelOverride:
    def test_model_override_does_not_mutate_client(self) -> None:
        # The per-call model override must reach the chat endpoint without
        # touching instance state, so a shared client (whose default is an
        # embedding model) is safe for concurrent callers.
        from src.finance.openai_client import OpenAIClient

        client = OpenAIClient(model="text-embedding-3-small", api_key="test-key")
        client.client = MagicMock(name="openai_sdk")  # avoid any real network call

        client.chat([{"role": "user", "content": "hi"}], model="gpt-5.4-nano")

        create = client.client.chat.completions.create
        assert create.call_args.kwargs["model"] == "gpt-5.4-nano"
        # Instance default is untouched — no mutate/restore.
        assert client.model == "text-embedding-3-small"

    def test_chat_defaults_to_instance_model(self) -> None:
        from src.finance.openai_client import OpenAIClient

        client = OpenAIClient(model="gpt-5.4-nano", api_key="test-key")
        client.client = MagicMock(name="openai_sdk")

        client.chat([{"role": "user", "content": "hi"}])

        create = client.client.chat.completions.create
        assert create.call_args.kwargs["model"] == "gpt-5.4-nano"


class TestChatReasoningEffort:
    def test_reasoning_effort_sent_when_set(self) -> None:
        from src.finance.openai_client import OpenAIClient

        client = OpenAIClient(model="gpt-5.4-nano", api_key="test-key")
        client.client = MagicMock(name="openai_sdk")

        client.chat([{"role": "user", "content": "hi"}], reasoning_effort="high")

        create = client.client.chat.completions.create
        assert create.call_args.kwargs["reasoning_effort"] == "high"

    def test_reasoning_effort_omitted_when_none(self) -> None:
        from openai import omit

        from src.finance.openai_client import OpenAIClient

        client = OpenAIClient(model="gpt-5.4-nano", api_key="test-key")
        client.client = MagicMock(name="openai_sdk")

        client.chat([{"role": "user", "content": "hi"}])

        create = client.client.chat.completions.create
        # The SDK sentinel means "don't send this param".
        assert create.call_args.kwargs["reasoning_effort"] is omit

    def test_instance_reasoning_effort_used_when_no_per_call(self) -> None:
        # get_ai_client sets the effort on the client; the categorizer then calls
        # chat() with no per-call effort and must still send the configured value.
        from src.finance.openai_client import OpenAIClient

        client = OpenAIClient(model="gpt-5.4-nano", api_key="test-key", reasoning_effort="low")
        client.client = MagicMock(name="openai_sdk")

        client.chat([{"role": "user", "content": "hi"}])

        create = client.client.chat.completions.create
        assert create.call_args.kwargs["reasoning_effort"] == "low"
