"""Unit tests for ``OpenAIClient``, which speaks the Responses API.

The client posts to ``/v1/responses`` (GPT-5.6 rejects function tools combined
with a reasoning effort on ``/v1/chat/completions``) while still handing
callers a chat-completion-shaped object. These tests pin both halves of that
translation, plus the ``store=False`` privacy guarantee and the
"swallow errors, record ``last_error``" contract.

Everything here uses fakes — no network, ever.
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from openai import omit

from src.finance.openai_client import (
    OpenAIClient,
    ResponsesAPIError,
    adapt_response,
    translate_content_part,
    translate_message,
    translate_messages,
    translate_tool,
    translate_tool_choice,
    translate_tools,
)

# --------------------------------------------------------------------------- #
# Fakes shaped like the Responses API
# --------------------------------------------------------------------------- #


def _function_call(name: str, arguments: dict[str, Any], call_id: str = "call_abc") -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        call_id=call_id,
        id="fc_1",
        name=name,
        arguments=json.dumps(arguments),
        status="completed",
    )


def _message(*texts: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="message",
        id="msg_1",
        role="assistant",
        status="completed",
        content=[SimpleNamespace(type="output_text", text=t, annotations=[]) for t in texts],
    )


def _reasoning_item() -> SimpleNamespace:
    return SimpleNamespace(type="reasoning", id="rs_1", summary=[])


def _usage(
    input_tokens: int = 100,
    output_tokens: int = 20,
    reasoning_tokens: int = 8,
    cached_tokens: int = 64,
    total_tokens: int = 120,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
    )


def _response(
    output: list[Any] | None = None,
    status: str | None = "completed",
    error: Any = None,
    usage: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp_1",
        object="response",
        status=status,
        error=error,
        incomplete_details=None,
        output=output if output is not None else [],
        usage=usage,
    )


def _client(model: str = "gpt-5.6-luna", **kwargs: Any) -> OpenAIClient:
    """An OpenAIClient whose SDK handle is a MagicMock — no network is reachable."""
    client = OpenAIClient(model=model, api_key="test-key", **kwargs)
    client.client = MagicMock(name="openai_sdk")
    client.client.responses.create.return_value = _response(output=[_message("ok")])
    return client


def _kwargs(client: OpenAIClient) -> dict[str, Any]:
    return client.client.responses.create.call_args.kwargs  # type: ignore[union-attr]


_CHAT_TOOL = {
    "type": "function",
    "function": {
        "name": "categorize_transaction",
        "description": "Categorize the transaction.",
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": ["category"],
        },
    },
}
_CHAT_TOOL_CHOICE = {"type": "function", "function": {"name": "categorize_transaction"}}


# --------------------------------------------------------------------------- #
# Message translation
# --------------------------------------------------------------------------- #


class TestTranslateMessages:
    def test_string_content_passes_through(self) -> None:
        assert translate_messages([{"role": "user", "content": "hi"}]) == [{"role": "user", "content": "hi"}]

    def test_order_and_roles_preserved(self) -> None:
        messages = [
            {"role": "system", "content": "s"},
            {"role": "developer", "content": "d"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        assert translate_messages(messages) == messages

    def test_text_part_becomes_input_text(self) -> None:
        got = translate_message({"role": "user", "content": [{"type": "text", "text": "read this"}]})
        assert got == {"role": "user", "content": [{"type": "input_text", "text": "read this"}]}

    def test_image_part_becomes_input_image(self) -> None:
        got = translate_content_part({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}})
        assert got == {"type": "input_image", "image_url": "data:image/jpeg;base64,AAA"}

    def test_image_part_keeps_detail(self) -> None:
        got = translate_content_part({"type": "image_url", "image_url": {"url": "https://x/y.png", "detail": "high"}})
        assert got == {"type": "input_image", "image_url": "https://x/y.png", "detail": "high"}

    def test_responses_style_parts_pass_through(self) -> None:
        parts = [
            {"type": "input_text", "text": "already translated"},
            {"type": "input_image", "image_url": "https://x/y.png", "detail": "low"},
        ]
        got = translate_message({"role": "user", "content": parts})
        assert got == {"role": "user", "content": parts}

    def test_receipt_parser_shape_translates(self) -> None:
        # The exact payload _invoke_image_provider builds.
        data_url = "data:image/jpeg;base64,QUJD"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Parse this receipt"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        assert translate_messages(messages) == [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Parse this receipt"},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ]

    def test_unknown_part_type_raises(self) -> None:
        with pytest.raises(ValueError, match="input_audio"):
            translate_content_part({"type": "input_audio", "input_audio": {}})

    def test_image_url_must_be_an_object(self) -> None:
        with pytest.raises(ValueError, match="image_url must be an object"):
            translate_content_part({"type": "image_url", "image_url": "https://x/y.png"})

    def test_tool_role_message_raises(self) -> None:
        with pytest.raises(ValueError, match="role 'tool'"):
            translate_message({"role": "tool", "tool_call_id": "c1", "content": "42"})

    def test_assistant_tool_calls_raise(self) -> None:
        with pytest.raises(ValueError, match="tool_calls"):
            translate_message({"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]})

    def test_unknown_role_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported message role"):
            translate_message({"role": "function", "content": "x"})

    def test_non_string_non_list_content_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported message content"):
            translate_message({"role": "user", "content": None})


# --------------------------------------------------------------------------- #
# Tool / tool_choice translation
# --------------------------------------------------------------------------- #


class TestTranslateTools:
    def test_nested_function_tool_is_flattened(self) -> None:
        assert translate_tool(_CHAT_TOOL) == {
            "type": "function",
            "name": "categorize_transaction",
            "parameters": _CHAT_TOOL["function"]["parameters"],  # type: ignore[index]
            "strict": False,
            "description": "Categorize the transaction.",
        }

    def test_strict_defaults_to_false(self) -> None:
        # Responses defaults function tools to strict mode, which would reject
        # every schema in this repo (no additionalProperties: false, optional
        # properties). The translation must not inherit that default.
        assert translate_tools([_CHAT_TOOL])[0]["strict"] is False

    def test_strict_preserved_when_the_tool_sets_it(self) -> None:
        tool = {"type": "function", "function": {"name": "f", "parameters": {}, "strict": True}}
        assert translate_tool(tool)["strict"] is True

    def test_flat_tool_passes_through(self) -> None:
        flat = {"type": "function", "name": "f", "parameters": {}, "strict": True}
        assert translate_tool(flat) is flat

    def test_builtin_tool_passes_through(self) -> None:
        builtin = {"type": "web_search_preview"}
        assert translate_tool(builtin) is builtin


class TestTranslateToolChoice:
    def test_nested_forced_function_is_flattened(self) -> None:
        assert translate_tool_choice(_CHAT_TOOL_CHOICE) == {"type": "function", "name": "categorize_transaction"}

    @pytest.mark.parametrize("choice", ["auto", "none", "required"])
    def test_string_choices_pass_through(self, choice: str) -> None:
        assert translate_tool_choice(choice) == choice

    def test_flat_choice_passes_through(self) -> None:
        flat = {"type": "function", "name": "f"}
        assert translate_tool_choice(flat) is flat


# --------------------------------------------------------------------------- #
# Request building
# --------------------------------------------------------------------------- #


class TestRequestBuilding:
    def test_forced_tool_call_request(self) -> None:
        client = _client()
        client.chat([{"role": "user", "content": "hi"}], tools=[_CHAT_TOOL], tool_choice=_CHAT_TOOL_CHOICE)

        kwargs = _kwargs(client)
        assert kwargs["model"] == "gpt-5.6-luna"
        assert kwargs["input"] == [{"role": "user", "content": "hi"}]
        assert kwargs["tools"] == [
            {
                "type": "function",
                "name": "categorize_transaction",
                "parameters": _CHAT_TOOL["function"]["parameters"],  # type: ignore[index]
                "strict": False,
                "description": "Categorize the transaction.",
            }
        ]
        assert kwargs["tool_choice"] == {"type": "function", "name": "categorize_transaction"}

    def test_store_is_always_false(self) -> None:
        # Responses persists request+response content server-side by default;
        # this app sends transactions, email bodies and receipt images.
        client = _client()
        client.chat([{"role": "user", "content": "hi"}])
        assert _kwargs(client)["store"] is False

    def test_store_is_false_for_tool_calls_too(self) -> None:
        client = _client()
        client.chat([{"role": "user", "content": "hi"}], tools=[_CHAT_TOOL], tool_choice=_CHAT_TOOL_CHOICE)
        assert _kwargs(client)["store"] is False

    def test_unset_tools_and_tool_choice_use_the_omit_sentinel(self) -> None:
        client = _client()
        client.chat([{"role": "user", "content": "hi"}])
        kwargs = _kwargs(client)
        assert kwargs["tools"] is omit
        assert kwargs["tool_choice"] is omit

    def test_reasoning_omitted_when_unset(self) -> None:
        client = _client()
        client.chat([{"role": "user", "content": "hi"}])
        assert _kwargs(client)["reasoning"] is omit

    def test_instance_reasoning_effort_is_sent(self) -> None:
        client = _client(reasoning_effort="low")
        client.chat([{"role": "user", "content": "hi"}])
        assert _kwargs(client)["reasoning"] == {"effort": "low"}

    def test_per_call_reasoning_effort_wins(self) -> None:
        client = _client(reasoning_effort="low")
        client.chat([{"role": "user", "content": "hi"}], reasoning_effort="high")
        assert _kwargs(client)["reasoning"] == {"effort": "high"}

    def test_model_override_does_not_mutate_instance(self) -> None:
        client = _client(model="text-embedding-3-small")
        client.chat([{"role": "user", "content": "hi"}], model="gpt-5.6-luna")
        assert _kwargs(client)["model"] == "gpt-5.6-luna"
        assert client.model == "text-embedding-3-small"

    def test_defaults_to_instance_model(self) -> None:
        client = _client(model="gpt-5.6-luna")
        client.chat([{"role": "user", "content": "hi"}])
        assert _kwargs(client)["model"] == "gpt-5.6-luna"

    def test_chat_completions_endpoint_is_never_touched(self) -> None:
        client = _client()
        client.chat([{"role": "user", "content": "hi"}], tools=[_CHAT_TOOL], tool_choice=_CHAT_TOOL_CHOICE)
        client.client.chat.completions.create.assert_not_called()  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Response adaptation
# --------------------------------------------------------------------------- #


class TestAdaptResponse:
    def test_single_function_call(self) -> None:
        raw = _response(output=[_function_call("categorize_transaction", {"category": "Groceries"})])
        adapted = adapt_response(raw)

        message = adapted.choices[0].message
        assert message.content is None
        assert len(message.tool_calls) == 1
        call = message.tool_calls[0]
        assert call.id == "call_abc"
        assert call.type == "function"
        assert call.function.name == "categorize_transaction"
        assert json.loads(call.function.arguments) == {"category": "Groceries"}
        assert adapted.raw is raw

    def test_two_function_calls(self) -> None:
        raw = _response(
            output=[
                _function_call("f", {"a": 1}, call_id="call_1"),
                _function_call("g", {"b": 2}, call_id="call_2"),
            ]
        )
        calls = adapt_response(raw).choices[0].message.tool_calls
        assert [c.id for c in calls] == ["call_1", "call_2"]
        assert [c.function.name for c in calls] == ["f", "g"]

    def test_text_only_leaves_tool_calls_none(self) -> None:
        adapted = adapt_response(_response(output=[_message("hello world")]))
        assert adapted.choices[0].message.content == "hello world"
        assert adapted.choices[0].message.tool_calls is None

    def test_multi_part_text_is_concatenated(self) -> None:
        adapted = adapt_response(_response(output=[_message("part one ", "part two")]))
        assert adapted.choices[0].message.content == "part one part two"

    def test_reasoning_items_are_ignored(self) -> None:
        adapted = adapt_response(_response(output=[_reasoning_item(), _message("answer")]))
        assert adapted.choices[0].message.content == "answer"
        assert adapted.choices[0].message.tool_calls is None

    def test_empty_output_gives_none_content_and_none_tool_calls(self) -> None:
        adapted = adapt_response(_response(output=[]))
        assert adapted.choices[0].message.content is None
        assert adapted.choices[0].message.tool_calls is None

    def test_usage_is_mapped_to_chat_names(self) -> None:
        adapted = adapt_response(_response(output=[_message("x")], usage=_usage()))
        usage = adapted.usage
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 20
        assert usage.total_tokens == 120
        assert usage.completion_tokens_details.reasoning_tokens == 8
        assert usage.prompt_tokens_details.cached_tokens == 64

    def test_missing_usage_details_map_to_none(self) -> None:
        bare = SimpleNamespace(input_tokens=5, output_tokens=6, total_tokens=11)
        usage = adapt_response(_response(output=[_message("x")], usage=bare)).usage
        assert usage.prompt_tokens == 5
        assert usage.completion_tokens == 6
        assert usage.completion_tokens_details.reasoning_tokens is None
        assert usage.prompt_tokens_details.cached_tokens is None

    def test_absent_usage_adapts_to_none(self) -> None:
        assert adapt_response(_response(output=[_message("x")])).usage is None

    def test_usage_survives_the_eval_harness_extractor(self) -> None:
        # dev/cli/eval_categorization.py reads these attribute chains.
        from dev.cli.eval_categorization import extract_usage

        adapted = adapt_response(_response(output=[_message("x")], usage=_usage()))
        assert extract_usage(adapted) == {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "reasoning_tokens": 8,
            "cached_tokens": 64,
        }

    @pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
    def test_non_completed_status_raises(self, status: str) -> None:
        with pytest.raises(ResponsesAPIError) as exc:
            adapt_response(_response(output=[_message("half an ans")], status=status))
        assert exc.value.reason == "incomplete_response"

    def test_error_object_raises(self) -> None:
        err = SimpleNamespace(code="server_error", message="boom")
        with pytest.raises(ResponsesAPIError) as exc:
            adapt_response(_response(output=[], error=err))
        assert exc.value.reason == "api_error"

    def test_absent_status_is_accepted(self) -> None:
        adapted = adapt_response(_response(output=[_message("x")], status=None))
        assert adapted.choices[0].message.content == "x"


# --------------------------------------------------------------------------- #
# Error contract
# --------------------------------------------------------------------------- #


class TestErrorContract:
    def test_exception_returns_none_and_records_last_error(self) -> None:
        boom = Exception("Connection timeout")
        client = _client()
        client.client.responses.create.side_effect = boom  # type: ignore[union-attr]

        assert client.chat([{"role": "user", "content": "hi"}]) is None
        assert client.last_error is boom

    def test_last_error_cleared_on_the_next_success(self) -> None:
        client = _client()
        client.last_error = Exception("stale error from a previous call")

        result = client.chat([{"role": "user", "content": "hi"}])
        assert result is not None
        assert client.last_error is None

    def test_incomplete_response_returns_none_with_last_error(self) -> None:
        client = _client()
        client.client.responses.create.return_value = _response(  # type: ignore[union-attr]
            output=[_message("truncated")], status="incomplete"
        )

        assert client.chat([{"role": "user", "content": "hi"}]) is None
        assert isinstance(client.last_error, ResponsesAPIError)
        assert client.last_error.reason == "incomplete_response"

    def test_untranslatable_message_returns_none_with_last_error(self) -> None:
        client = _client()

        assert client.chat([{"role": "tool", "content": "42", "tool_call_id": "c1"}]) is None
        assert isinstance(client.last_error, ValueError)
        client.client.responses.create.assert_not_called()  # type: ignore[union-attr]

    def test_error_classification_still_works_through_the_new_endpoint(self) -> None:
        # categorizer._classify_ai_error matches on OpenAI SDK exception types,
        # which are raised by responses.create exactly as they were by
        # chat.completions.create.
        import httpx
        from openai import RateLimitError

        from src.finance.categorizer import _classify_ai_error

        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        boom = RateLimitError(
            "msg",
            response=httpx.Response(429, request=request),
            body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
        )
        client = _client()
        client.client.responses.create.side_effect = boom  # type: ignore[union-attr]

        assert client.chat([{"role": "user", "content": "hi"}]) is None
        assert _classify_ai_error(client.last_error) == "quota_exceeded"


# --------------------------------------------------------------------------- #
# End-to-end shape contract: real callers, fake transport
# --------------------------------------------------------------------------- #


class TestCallerContract:
    def test_categorize_with_ai_reads_a_responses_backed_client(self) -> None:
        from src.finance.categorizer import categorize_with_ai

        client = _client()
        client.client.responses.create.return_value = _response(  # type: ignore[union-attr]
            output=[_reasoning_item(), _function_call("categorize_transaction", {"category": "Groceries"})],
            usage=_usage(),
        )

        transaction: dict[str, Any] = {"amount": 12.5, "company": "Safeway"}
        assert categorize_with_ai(client, transaction, ["Groceries", "Miscellaneous"]) == "Groceries"
        assert transaction["_category_audit"]["source"] == "ai"

        # And the request that produced it was a forced, non-strict Responses call.
        kwargs = _kwargs(client)
        assert kwargs["tool_choice"] == {"type": "function", "name": "categorize_transaction"}
        assert kwargs["tools"][0]["strict"] is False
        assert kwargs["store"] is False

    def test_categorize_with_ai_falls_back_when_the_response_is_incomplete(self) -> None:
        from src.finance.categorizer import categorize_with_ai

        client = _client()
        client.client.responses.create.return_value = _response(output=[], status="incomplete")  # type: ignore[union-attr]

        transaction: dict[str, Any] = {"amount": 12.5, "company": "Safeway"}
        assert categorize_with_ai(client, transaction, ["Groceries", "Miscellaneous"]) == "Miscellaneous"
        assert transaction["_category_audit"]["fallback_reason"] == "incomplete_response"

    def test_email_is_transaction_alert_reads_a_responses_backed_client(self) -> None:
        from src.finance.categorizer import email_is_transaction_alert

        client = _client()
        client.client.responses.create.return_value = _response(  # type: ignore[union-attr]
            output=[_function_call("detect_if_transaction_alert", {"true_or_false": "True"})]
        )

        assert email_is_transaction_alert(client, [{"role": "user", "content": "You spent $5"}]) is True

    def test_extract_transaction_reads_a_responses_backed_client(self) -> None:
        from src.finance.extractor import extract_transaction

        client = _client()
        client.client.responses.create.return_value = _response(  # type: ignore[union-attr]
            output=[
                _function_call(
                    "extract_transaction",
                    {"amount": "12.50", "company": "Safeway", "transaction_type": "purchase"},
                )
            ]
        )

        result, stage = extract_transaction(client, {"subject": "Alert", "body": "You spent $12.50 at Safeway"})
        assert stage is None
        assert result is not None
        assert result["amount"] == 12.50
        assert result["company"] == "Safeway"
