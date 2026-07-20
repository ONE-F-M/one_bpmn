import logging

from .base import (
    BaseLLMAdapter,
    CompletionResult,
    StepResult,
    StepToolCall,
    ToolCallRecord,
    ToolSpec,
    TurnRecord,
    build_parameter_schema,
)

_MAX_TOOL_TURNS = 10

logger = logging.getLogger(__name__)


def _build_tool_def(tool: ToolSpec) -> dict:
    """Build an Anthropic tool definition from a ToolSpec."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": build_parameter_schema(tool),
    }


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

    def __init__(self, api_key: str, model: str):
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
        max_turns: int | None = None,
    ) -> CompletionResult:
        import re

        tool_defs = [_build_tool_def(t) for t in tools] if tools else []
        tool_map = {t.name: t for t in tools} if tools else {}

        # ── Breakpoint 1: Cache tool definitions ──────────────────────────────
        # Tools are static across the entire multi-turn invocation.
        # Placing cache_control on the last tool caches the full tools prefix.
        if tool_defs:
            tool_defs[-1]["cache_control"] = {"type": "ephemeral"}

        # ── Breakpoint 2: Cache system prompt ─────────────────────────────────
        # The system prompt is large (~4-8k tokens) and identical every turn.
        system_blocks = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        # ── Build the initial user message ────────────────────────────────────
        # Split the user prompt into a cacheable context prefix (conversation
        # history + state) and the varying user message.  The context prefix
        # gets its own cache_control so that on a cache miss at the automatic
        # breakpoint, the lookback still finds this earlier write.
        user_blocks = []
        split_match = re.search(
            r"(\n+(?:User message|User request|User prompt|Request):\s*)(.*)$",
            user,
            re.IGNORECASE | re.DOTALL,
        )
        if split_match:
            prefix_text = user[:split_match.start()].strip()
            suffix_text = (split_match.group(1) + split_match.group(2)).strip()
            if prefix_text:
                user_blocks.append({
                    "type": "text",
                    "text": prefix_text,
                    "cache_control": {"type": "ephemeral"},
                })
            user_blocks.append({
                "type": "text",
                "text": suffix_text,
            })
        else:
            user_blocks.append({
                "type": "text",
                "text": user,
            })

        messages = [{"role": "user", "content": user_blocks}]

        # ── Build request kwargs ───────────────────────────────────────────────
        # Explicit cache_control markers are on: (1) last tool def, (2) system
        # prompt, and (3) either user-prefix (turn 0) or last tool_result
        # (turns 1+).  This keeps us at 3 active markers — well within the
        # Anthropic limit of 4.
        kwargs: dict = {
            "model": self._model,
            "system": system_blocks,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs

        trace = []
        for turn in range(max_turns or _MAX_TOOL_TURNS):
            _turn_t0 = time.perf_counter()
            # Use streaming to avoid the Anthropic SDK's 10-minute limit on
            # non-streaming requests.  get_final_message() collects the full
            # response and returns the same Message object as messages.create().
            async with self._client.messages.stream(**kwargs) as stream:
                response = await stream.get_final_message()

            # ── Log cache metrics ─────────────────────────────────────────────
            usage = response.usage
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
            uncached = getattr(usage, "input_tokens", 0) or 0
            logger.debug(
                "Anthropic cache [model=%s turn=%d]: "
                "read=%d write=%d uncached=%d total_in=%d out=%d",
                self._model, turn,
                cache_read, cache_write, uncached,
                cache_read + cache_write + uncached,
                getattr(usage, "output_tokens", 0) or 0,
            )

            if response.stop_reason != "tool_use":
                # Collect all text blocks
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_parts)

            # Append assistant turn (content includes tool_use blocks)
            messages.append({"role": "assistant", "content": response.content})

            # Execute tool calls and build tool_result blocks
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool = tool_map.get(block.name)
                if tool:
                    try:
                        result = str(tool.fn(**block.input))
                    except Exception as exc:
                        result = f"Error calling {block.name}: {exc}"
                else:
                    result = f"Unknown tool: {block.name}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            # Mark the last tool_result with cache_control so the entire
            # conversation prefix (tools + system + all prior messages +
            # this tool result) is cached for the next turn.  This gives
            # the lookback window an explicit write point close to the end
            # of the growing conversation, ensuring cache hits even when
            # the conversation exceeds 20 blocks.
            if tool_results:
                tool_results[-1]["cache_control"] = {"type": "ephemeral"}

            messages.append({"role": "user", "content": tool_results})
            kwargs["messages"] = messages

        return CompletionResult(text="", trace=trace, hit_turn_cap=True)

    async def step(
        self,
        system: str,
        transcript: list,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
    ) -> StepResult:
        """One Messages API call from the provider-agnostic transcript.

        The transcript is rebuilt into wire format on every step (it must be
        JSON-checkpointable, so no SDK objects are retained between steps).
        The same 3 cache breakpoints as complete() apply — tools, system, and
        the LAST tool_result block — so the growing conversation prefix stays
        cached across steps exactly as it did across the internal loop's turns.
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
                    "content": [{"type": "text", "text": entry.get("content", "")}],
                })
            elif role == "assistant":
                blocks = []
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
                        "content": r.get("content", ""),
                    }
                    for r in entry.get("results") or []
                ]
                if blocks:
                    last_tool_result_block = blocks[-1]
                    messages.append({"role": "user", "content": blocks})
        if last_tool_result_block is not None:
            last_tool_result_block["cache_control"] = {"type": "ephemeral"}

        kwargs: dict = {
            "model": self._model,
            "system": system_blocks,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs

        async with self._client.messages.stream(**kwargs) as stream:
            response = await stream.get_final_message()

        prompt_tokens, completion_tokens = _usage_tokens(response)
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
        )
