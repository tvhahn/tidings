import logging
from typing import Any, cast

from openai import OpenAI, omit

logger = logging.getLogger(__name__)


class OpenAIClient:
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
        """Post a chat completion.

        ``model`` overrides ``self.model`` for this single call only, without
        mutating instance state — safe for a shared client whose default model
        is not chat-capable (e.g. an embedding model). Existing callers pass
        nothing and keep using ``self.model``.

        ``reasoning_effort`` (``None`` = fall back to the instance default, then
        the model default) is a passthrough OpenAI param — only sent when
        resolved to a value, so existing callers are unaffected.
        """
        self.last_error = None
        effort = reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        try:
            # Cast through Any: OpenAI SDK uses TypedDict param types
            # (ChatCompletionMessageParam et al). Our callers assemble plain
            # dicts, which are structurally compatible at runtime.
            return self.client.chat.completions.create(
                model=model if model is not None else self.model,
                messages=cast("Any", messages),
                tools=cast("Any", tools) if tools is not None else omit,
                tool_choice=cast("Any", tool_choice) if tool_choice is not None else omit,
                reasoning_effort=cast("Any", effort) if effort is not None else omit,
            )
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
