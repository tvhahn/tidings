"""OpenAI access for the finance pipeline, spoken over the Responses API.

Every ``chat()`` call in this app goes to ``/v1/responses``. The GPT-5.6 family
rejects our core request shape on ``/v1/chat/completions``:

    Function tools with reasoning_effort are not supported for gpt-5.6-luna in
    /v1/chat/completions. To use function tools, use /v1/responses or set
    reasoning_effort to 'none'.

That 400 lands on every forced-function-tool call the categorizer and extractor
make — including when the effort is omitted, because the model's own default is
not ``none``. Since ``chat()`` swallows errors and returns ``None``, the failure
was silent: every transaction fell back to "Miscellaneous". Responses accepts
the same request, so the whole surface (tools, text, and vision) moved there —
one code path, not a split by request kind.

The return value is deliberately still shaped like a chat completion
(``.choices[0].message.content`` / ``.tool_calls[i].function.arguments``,
``.usage.prompt_tokens`` …). That shape is a compatibility contract: it is the
structural type behind ``ai_client.AIProviderClient``, which the Codex CLI
client also implements by building the same namespaces, and it is what
``categorizer.extract_function_call_args`` and the eval harness's usage
extraction read. Adapting here keeps every caller untouched.
"""

import logging
from types import SimpleNamespace
from typing import Any, cast

from openai import OpenAI, omit

logger = logging.getLogger(__name__)

# Roles the Responses API accepts verbatim on an input message.
_INPUT_ROLES = frozenset({"system", "developer", "user", "assistant"})

# Content parts already written in Responses vocabulary — forwarded untouched.
_RESPONSES_PART_TYPES = frozenset({"input_text", "input_image"})

# A non-streaming, non-background create() should come back "completed".
# Anything else (incomplete, failed, cancelled, still queued/in_progress) is a
# partial answer, never a result.
_COMPLETED_STATUS = "completed"


class ResponsesAPIError(RuntimeError):
    """A Responses call returned without a usable answer.

    Carries a ``reason`` so ``categorizer._classify_ai_error`` — which reads
    ``.reason`` off any exception before falling back to OpenAI SDK type
    matching — records why in the category audit instead of a generic
    ``api_error``.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# --------------------------------------------------------------------------- #
# Request translation (chat-completions vocabulary -> Responses vocabulary)
# --------------------------------------------------------------------------- #


def translate_content_part(part: Any) -> dict[str, Any]:
    """Translate one chat-completions content part into a Responses input part.

    ``{"type": "text"}`` becomes ``input_text``; ``{"type": "image_url"}``
    becomes ``input_image`` with the URL flattened out of its wrapper object.
    Parts already written as ``input_text`` / ``input_image`` pass through.
    Anything else raises ``ValueError`` — no caller sends it, and guessing a
    translation would send the model something nobody wrote.
    """
    if not isinstance(part, dict):
        raise ValueError(f"Unsupported content part (expected a dict, got {type(part).__name__})")

    part_type = part.get("type")
    if part_type in _RESPONSES_PART_TYPES:
        return part
    if part_type == "text":
        return {"type": "input_text", "text": part.get("text", "")}
    if part_type == "image_url":
        image_url = part.get("image_url")
        if not isinstance(image_url, dict):
            raise ValueError("Unsupported content part: image_url must be an object with a 'url' key")
        translated: dict[str, Any] = {"type": "input_image", "image_url": image_url.get("url")}
        detail = image_url.get("detail")
        if detail is not None:
            translated["detail"] = detail
        return translated
    raise ValueError(f"Unsupported content part type: {part_type!r}")


def translate_message(message: Any) -> dict[str, Any]:
    """Translate one chat message into a Responses input item.

    Supports what this app actually sends: ``system`` / ``developer`` / ``user``
    / ``assistant`` messages whose content is a string or a list of content
    parts. Assistant ``tool_calls`` and ``tool``-role results would need
    ``function_call`` / ``function_call_output`` items; no caller in this repo
    sends a tool result back to the model (every call is single-turn with a
    forced tool), so they raise ``ValueError`` rather than shipping an
    untested translation.
    """
    if not isinstance(message, dict):
        raise ValueError(f"Unsupported message (expected a dict, got {type(message).__name__})")

    role = message.get("role")
    if role == "tool":
        raise ValueError("Unsupported message role 'tool': tool results are not sent by any caller")
    if role not in _INPUT_ROLES:
        raise ValueError(f"Unsupported message role: {role!r}")
    if message.get("tool_calls"):
        raise ValueError("Unsupported message field 'tool_calls': assistant tool calls are not sent by any caller")

    content = message.get("content")
    if isinstance(content, str):
        return {"role": role, "content": content}
    if isinstance(content, list):
        return {"role": role, "content": [translate_content_part(part) for part in content]}
    raise ValueError(f"Unsupported message content (expected str or list, got {type(content).__name__})")


def translate_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate a chat ``messages`` list into a Responses ``input`` list, in order."""
    return [translate_message(message) for message in messages]


def translate_tool(tool: Any) -> dict[str, Any]:
    """Flatten a chat-completions function tool into a Responses function tool.

    ``{"type": "function", "function": {...}}`` becomes a flat
    ``{"type": "function", "name", "description", "parameters", "strict"}``.

    ``strict`` defaults to ``False``, not to the API's default of ``True``:
    strict mode requires ``additionalProperties: false`` plus every property
    listed in ``required``, and this repo's schemas were written for
    non-strict chat completions. Defaulting to ``False`` preserves their
    meaning; a tool that opts into strict keeps its own value.

    Tools already in Responses shape (flat, or a built-in tool type) pass
    through untouched.
    """
    if not isinstance(tool, dict):
        raise ValueError(f"Unsupported tool (expected a dict, got {type(tool).__name__})")

    function = tool.get("function")
    if not isinstance(function, dict):
        return tool

    translated: dict[str, Any] = {
        "type": "function",
        "name": function.get("name"),
        "parameters": function.get("parameters"),
        "strict": function.get("strict", False),
    }
    description = function.get("description")
    if description is not None:
        translated["description"] = description
    return translated


def translate_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate a chat ``tools`` list into a Responses ``tools`` list."""
    return [translate_tool(tool) for tool in tools]


def translate_tool_choice(tool_choice: str | dict[str, Any]) -> str | dict[str, Any]:
    """Flatten a forced-function tool choice; pass strings and flat dicts through."""
    if isinstance(tool_choice, dict):
        function = tool_choice.get("function")
        if isinstance(function, dict):
            return {"type": "function", "name": function.get("name")}
    return tool_choice


# --------------------------------------------------------------------------- #
# Response adaptation (Responses object -> chat-completion shape)
# --------------------------------------------------------------------------- #


def _adapt_usage(usage: Any) -> Any:
    """Map Responses token counters onto the chat-completions names.

    ``input_tokens`` -> ``prompt_tokens``, ``output_tokens`` ->
    ``completion_tokens``, and the two detail objects likewise. Missing
    counters become ``None`` throughout (the eval harness coerces per-field and
    tolerates it), and a response with no usage at all adapts to ``None``.
    """
    if usage is None:
        return None
    output_details = getattr(usage, "output_tokens_details", None)
    input_details = getattr(usage, "input_tokens_details", None)
    return SimpleNamespace(
        prompt_tokens=getattr(usage, "input_tokens", None),
        completion_tokens=getattr(usage, "output_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=getattr(output_details, "reasoning_tokens", None)),
        prompt_tokens_details=SimpleNamespace(cached_tokens=getattr(input_details, "cached_tokens", None)),
    )


def adapt_response(response: Any) -> Any:
    """Adapt a Responses object into the chat-completion shape callers read.

    Raises ``ResponsesAPIError`` when the response carries an error or did not
    reach ``completed`` — a truncated or failed generation must not be handed
    to a caller as if it were an answer.

    ``tool_calls`` is ``None`` (not ``[]``) when the model called nothing and
    ``content`` is ``None`` (not ``""``) when it wrote no text, because every
    caller branches on truthiness and chat completions behaved that way.
    """
    error = getattr(response, "error", None)
    if error is not None:
        raise ResponsesAPIError("api_error", f"The Responses API returned an error: {error}")

    status = getattr(response, "status", None)
    if status is not None and status != _COMPLETED_STATUS:
        detail = getattr(response, "incomplete_details", None)
        raise ResponsesAPIError(
            "incomplete_response",
            f"The Responses API returned status {status!r} (incomplete_details={detail!r})",
        )

    tool_calls: list[Any] = []
    texts: list[str] = []
    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type == "function_call":
            tool_calls.append(
                SimpleNamespace(
                    id=getattr(item, "call_id", None),
                    type="function",
                    function=SimpleNamespace(
                        name=getattr(item, "name", None),
                        arguments=getattr(item, "arguments", None),
                    ),
                )
            )
        elif item_type == "message":
            texts.extend(
                getattr(part, "text", "") or ""
                for part in getattr(item, "content", None) or []
                if getattr(part, "type", None) == "output_text"
            )
        # Reasoning items (and any other non-message, non-call item) carry no
        # caller-visible payload.

    message = SimpleNamespace(
        role="assistant",
        content="".join(texts) if texts else None,
        tool_calls=tool_calls or None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, message=message)],
        usage=_adapt_usage(getattr(response, "usage", None)),
        # The untouched Responses object, for debugging and for anything that
        # needs a field the chat-completion shape has no room for.
        raw=response,
    )


class OpenAIClient:
    """OpenAI client for the finance pipeline: Responses for chat, plus embeddings.

    ``chat()`` posts to ``/v1/responses`` because the GPT-5.6 family refuses
    function tools with a reasoning effort on ``/v1/chat/completions`` (see the
    module docstring), and returns a chat-completion-shaped adapter object so
    no caller — nor the ``AIProviderClient`` protocol the Codex client also
    satisfies — has to change.

    Every request is sent with ``store=False``. The Responses API persists
    request and response content server-side by default (chat completions did
    not); this app sends bank-transaction details, raw email bodies and receipt
    images, so the endpoint move must not quietly widen what leaves the
    machine.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        organization: str | None = None,
        reasoning_effort: str | None = None,
    ):
        self.model = model
        # Instance-level reasoning-effort default (None = model default). Lets a
        # caller that only holds the client and calls chat() with no per-call
        # override — e.g. the categorizer via get_ai_client — still apply the
        # configured effort. A per-call reasoning_effort on chat() wins.
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI(api_key=api_key, organization=organization)
        # Last exception raised by chat(), or None after a successful call.
        # chat() swallows errors and returns None to keep callers crash-free;
        # this lets a caller (e.g. the categorizer) recover *why* the call
        # failed and record it in the audit instead of a generic fallback.
        self.last_error: Exception | None = None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> Any:
        """Post a request to the Responses API, in chat-completions clothing.

        Arguments are the chat-completions vocabulary callers already speak —
        ``messages``, nested function ``tools``, a nested ``tool_choice`` — and
        are translated to Responses ``input`` / flat tools / flat tool choice on
        the way out. The result is adapted back, so callers keep reading
        ``.choices[0].message.content``, ``.tool_calls[i].function.arguments``
        and ``.usage.*``; the untouched Responses object is available as
        ``.raw``. The endpoint moved because GPT-5.6 rejects function tools
        combined with a reasoning effort on ``/v1/chat/completions``.

        ``store=False`` is sent on every call: Responses stores request and
        response content server-side by default, and this app's payloads are
        financial data, email bodies and receipt images.

        ``model`` overrides ``self.model`` for this single call only, without
        mutating instance state — safe for a shared client whose default model
        is not chat-capable (e.g. an embedding model). Existing callers pass
        nothing and keep using ``self.model``.

        ``reasoning_effort`` (``None`` = fall back to the instance default, then
        the model default) is sent as ``reasoning={"effort": ...}``, and only
        when it resolves to a value.

        Returns ``None`` on any failure — including a response that came back
        ``incomplete``/``failed`` — with the exception recorded on
        ``last_error``.
        """
        self.last_error = None
        effort = reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        try:
            # Cast through Any: the SDK types these params as TypedDicts
            # (ResponseInputParam, ToolParam et al). Our translations produce
            # plain dicts, which are structurally compatible at runtime.
            response = self.client.responses.create(
                model=model if model is not None else self.model,
                input=cast("Any", translate_messages(messages)),
                tools=cast("Any", translate_tools(tools)) if tools is not None else omit,
                tool_choice=cast("Any", translate_tool_choice(tool_choice)) if tool_choice is not None else omit,
                reasoning=cast("Any", {"effort": effort}) if effort is not None else omit,
                # Never persist financial data, email bodies or receipt images
                # on OpenAI's side — Responses would default this to True.
                store=False,
            )
            return adapt_response(response)
        except Exception as e:
            logger.exception("An error occurred during API call.")
            self.last_error = e
            return None

    def embed(self, texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
        """Batch-embed texts using OpenAI's embedding API.

        Returns a list of embedding vectors (one per input text).
        Returns an empty list on error.
        """
        try:
            response = self.client.embeddings.create(model=model, input=texts)
            return [item.embedding for item in response.data]
        except Exception:
            logger.exception("Embedding API call failed.")
            return []
