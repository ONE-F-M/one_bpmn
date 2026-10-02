import re

from .base import (
    BaseLLMAdapter,
    LLMTruncatedError,
    StepResult,
    StepToolCall,
    ToolSpec,
    build_parameter_schema,
)
from .structured_output import anthropic_output_config

# Opus 5.5, Sonnet 5.5 and Fable reject a forced tool_choice ("any" or "tool") with a 400.
_NO_FORCED_TOOL_CHOICE = re.compile(r"-(?:opus|sonnet)-5-5|fable")
# The 5-series and Fable choose their own thinking and reject a budget_tokens setting.
_ADAPTIVE_THINKING = re.compile(r"-(?:sonnet|opus|haiku)-5(?:$|[^0-9])|fable")


def _usage_tokens(response) -> tuple:
    """Real token counts for the turn.

    Returns ``(prompt, completion, cache_read, cache_write)``. Anthropic reports
    ``input_tokens`` EXCLUDING the cached portions, so prompt is the sum of all
    three — cache_read/cache_creation tokens ARE consumed context, just billed
    differently. The cache counts are returned alongside (rather than folded in
    and forgotten) so pricing can actually apply the different rates: before
    WI-001643 this function's docstring promised "pricing.py handles the cost
    split" while discarding the only numbers that made it possible, and every
    cached token was billed at the full input rate.
    """
    usage = getattr(response, "usage", None)
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    prompt = (getattr(usage, "input_tokens", 0) or 0) + cache_read + cache_write
    return prompt, getattr(usage, "output_tokens", 0) or 0, cache_read, cache_write


def _build_tool_def(tool: ToolSpec) -> dict:
    """Build an Anthropic tool definition from a ToolSpec."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": build_parameter_schema(tool),
    }


# Anthropic rejects an empty text or tool_result block outright:
#   400 invalid_request_error: "messages: text content blocks must be non-empty"
#
# An empty block is a normal thing to end up with, not a programming error. A
# delegated worker that stops at its turn cap returns no text, so its answer
# arrives here as "", and on resume that becomes an empty tool_result — killing
# the whole turn with an opaque 400 instead of letting the model read "the
# specialist returned nothing" and say so. Seen exactly that way: two
# orchestrator runs failed with 0 tokens while every uncapped run succeeded.
#
# Saying so in words is strictly better than crashing, and the model can act on
# it. Applied to user text and tool results, the two places content arrives from
# outside this module; assistant text is already guarded by a truthiness check,
# because a tool-call-only turn legitimately has none.
_EMPTY_PLACEHOLDER = "(no content was returned)"


def _nonempty(value) -> str:
    text = "" if value is None else str(value)
    return text if text.strip() else _EMPTY_PLACEHOLDER


async def _forward_text(stream) -> None:
    """Send each text delta to the chat request waiting on this turn, if any.

    The SDK already streams the reply; this reads it as it arrives instead of
    only at the end, so the first words reach the reader while the model is
    still writing. Progress is an accelerator: a failure here is swallowed so
    it can never fail the model call itself.
    """
    try:
        from one_bpmn.agents.turn_signal import live_text_sink

        sink = live_text_sink()
    except Exception:
        sink = None
    if sink is None:
        return
    try:
        async for event in stream:
            if getattr(event, "type", None) == "text" and getattr(event, "text", ""):
                sink(event.text)
    except Exception:
        pass


class AnthropicAdapter(BaseLLMAdapter):
    """
    Anthropic Messages API adapter with prompt caching.

    Caching strategy (3 explicit breakpoints, max 4 allowed by Anthropic):
      1. **Tools**  – ``cache_control`` on the last tool definition caches
         the entire tool-definition prefix.  Tools never change within a
         single ``complete()`` invocation, so this is always a cache hit
         from turn 2 onwards.
      2. **System prompt** – ``cache_control`` on the system text block.
         The system prompt is identical across every turn within a call.
      3. **Conversation prefix** – On the first turn, if the user prompt
         can be split into a context prefix and a request suffix, the
         prefix gets ``cache_control``.  On subsequent tool-result turns,
         the last ``tool_result`` block gets ``cache_control`` instead,
         caching the entire growing conversation prefix for the next turn.

    This keeps us at 3 active markers per request (tools + system +
    one conversation marker), safely within the Anthropic limit of 4.

    Cache metrics are logged at DEBUG level for diagnostics.
    """

    def __init__(self, api_key: str, model: str, timeout_seconds: float | None = None, max_retries: int | None = None):
        import anthropic

        # The SDK's own defaults are a 600 s read timeout and two retries. Both
        # are overridden here, never passed as None — to this client None means
        # "wait forever". Calls are streamed, so the timeout is the longest the
        # stream may fall silent, which is the bound actually wanted.
        client_kwargs = {"api_key": api_key}
        if timeout_seconds:
            client_kwargs["timeout"] = timeout_seconds
        if max_retries is not None:
            client_kwargs["max_retries"] = max_retries
        self._client = anthropic.AsyncAnthropic(**client_kwargs)
        self._model = model

    async def step(
        self,
        system: str,
        transcript: list,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
        response_schema: dict | None = None,
        tool_choice: str | None = None,
        parallel_tool_calls: bool = True,
        thinking_budget_tokens: int = 0,
    ) -> StepResult:
        """One Messages API call from the provider-agnostic transcript.

        The transcript is rebuilt into wire format on every step (it must be
        JSON-checkpointable, so no SDK objects are retained between steps).
        Three cache breakpoints: tools, system, and the LAST tool_result block,
        or a split-off user context prefix before the first tool result.
        """
        tool_defs = [_build_tool_def(t) for t in tools] if tools else []
        if tool_defs:
            tool_defs[-1]["cache_control"] = {"type": "ephemeral"}

        system_blocks = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

        messages = []
        last_tool_result_block = None
        for entry in transcript:
            role = entry.get("role")
            if role == "user":
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _nonempty(entry.get("content"))}
                    ],
                })
            elif role == "assistant":
                blocks = list(entry.get("thinking") or [])
                if entry.get("content"):
                    blocks.append({"type": "text", "text": entry["content"]})
                for c in entry.get("tool_calls") or []:
                    blocks.append({
                        "type": "tool_use",
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "input": c.get("arguments") or {},
                    })
                messages.append({"role": "assistant", "content": blocks})
            elif role == "tool_results":
                blocks = [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.get("id", ""),
                        "content": _nonempty(r.get("content")),
                    }
                    for r in entry.get("results") or []
                ]
                if blocks:
                    last_tool_result_block = blocks[-1]
                    messages.append({"role": "user", "content": blocks})
        if last_tool_result_block is not None:
            last_tool_result_block["cache_control"] = {"type": "ephemeral"}
        elif messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = _split_cacheable_prefix(messages[-1]["content"][0]["text"])

        thinking = bool(thinking_budget_tokens) and not _ADAPTIVE_THINKING.search(self._model.lower())
        kwargs: dict = {
            "model": self._model,
            "system": system_blocks,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs
            choice = _tool_choice(tool_choice, forced_allowed=not thinking and not _NO_FORCED_TOOL_CHOICE.search(self._model.lower()))
            if not parallel_tool_calls:
                choice["disable_parallel_tool_use"] = True
            if choice != {"type": "auto"}:
                kwargs["tool_choice"] = choice
        if thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget_tokens}
        if response_schema:
            kwargs["output_config"] = anthropic_output_config(response_schema)

        async with self._client.messages.stream(**kwargs) as stream:
            await _forward_text(stream)
            response = await stream.get_final_message()

        # A reply cut off at the token ceiling ends mid-token, so its JSON and tool arguments are unusable.
        if response.stop_reason == "max_tokens":
            raise LLMTruncatedError(
                f"The model hit its {max_tokens}-token output limit before "
                "finishing. Raise Max Tokens on the agent configuration (or "
                "the task shape) and try again."
            )

        prompt_tokens, completion_tokens, cache_read, cache_write = _usage_tokens(response)
        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        tool_calls = [
            StepToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in response.content
            if b.type == "tool_use"
        ]

        return StepResult(
            content="\n".join(text_parts),
            tool_calls=tool_calls if response.stop_reason == "tool_use" else [],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            thinking=[_thinking_block(b) for b in response.content if b.type in ("thinking", "redacted_thinking")],
        )


def _tool_choice(tool_choice: str | None, *, forced_allowed: bool) -> dict:
    """The Anthropic tool_choice for "auto", "required" or a tool name; "auto" where forcing is refused."""
    if not tool_choice or tool_choice == "auto" or not forced_allowed:
        return {"type": "auto"}
    if tool_choice == "required":
        return {"type": "any"}
    return {"type": "tool", "name": tool_choice}


def _thinking_block(block) -> dict:
    if block.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}


def _split_cacheable_prefix(user: str) -> list:
    """Split a user prompt into a cached context prefix and the request after it, when it has both."""
    match = re.search(
        r"(\n+(?:User message|User request|User prompt|Request):\s*)(.*)$",
        user,
        re.IGNORECASE | re.DOTALL,
    )
    if not match or not user[: match.start()].strip():
        return [{"type": "text", "text": _nonempty(user)}]
    return [
        {"type": "text", "text": user[: match.start()].strip(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": (match.group(1) + match.group(2)).strip()},
    ]
