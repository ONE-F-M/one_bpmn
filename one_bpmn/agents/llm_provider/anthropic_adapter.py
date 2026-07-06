import logging
import time

from .base import BaseLLMAdapter, CompletionResult, ToolCallRecord, ToolSpec, TurnRecord

_MAX_TOOL_TURNS = 10

logger = logging.getLogger(__name__)


def _usage_tokens(response) -> tuple:
    """Real prompt/completion counts for the turn. Prompt tokens include the
    cached portions — cache_read/cache_creation tokens ARE consumed context,
    just billed differently; pricing.py handles the cost split."""
    usage = getattr(response, "usage", None)
    prompt = (
        (getattr(usage, "input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    )
    return prompt, getattr(usage, "output_tokens", 0) or 0


def _build_tool_def(tool: ToolSpec) -> dict:
    """Build an Anthropic tool definition from a ToolSpec."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": {
            "type": "object",
            "properties": {
                name: {"type": info.get("type", "string"), "description": info.get("description", "")}
                for name, info in tool.parameters.items()
            },
            "required": tool.required or [],
        },
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
        # ``conv_marker`` tracks the single block that currently carries the
        # moving conversation cache_control marker.  As the conversation grows
        # we relocate this marker to the latest tool_result rather than adding a
        # new one, so the total number of markers stays fixed at 3 (tools +
        # system + conversation) — well within Anthropic's limit of 4.
        conv_marker: dict | None = None
        split_match = re.search(
            r"(\n+(?:User message|User request|User prompt|Request):\s*)(.*)$",
            user,
            re.IGNORECASE | re.DOTALL,
        )
        if split_match:
            prefix_text = user[:split_match.start()].strip()
            suffix_text = (split_match.group(1) + split_match.group(2)).strip()
            if prefix_text:
                conv_marker = {
                    "type": "text",
                    "text": prefix_text,
                    "cache_control": {"type": "ephemeral"},
                }
                user_blocks.append(conv_marker)
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
            prompt_tokens, completion_tokens = _usage_tokens(response)
            text_parts = [b.text for b in response.content if hasattr(b, "text")]

            if response.stop_reason != "tool_use":
                content = "\n".join(text_parts)
                trace.append(
                    TurnRecord(
                        role="assistant",
                        content=content,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=int((time.perf_counter() - _turn_t0) * 1000),
                    )
                )
                return CompletionResult(text=content, trace=trace)

            # Append assistant turn (content includes tool_use blocks)
            messages.append({"role": "assistant", "content": response.content})

            # Execute tool calls and build tool_result blocks; all calls of
            # this response stay grouped under ONE TurnRecord with the turn's
            # real token usage.
            turn_record = TurnRecord(
                role="tool",
                content="\n".join(text_parts),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool = tool_map.get(block.name)
                arguments = dict(block.input or {})
                if tool:
                    try:
                        result = str(tool.fn(**arguments))
                    except Exception as exc:
                        result = f"Error calling {block.name}: {exc}"
                else:
                    result = f"Unknown tool: {block.name}"

                turn_record.tool_calls.append(
                    ToolCallRecord(name=block.name, arguments=arguments, result=result)
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            # API round-trip + inline tool execution = this turn's decision latency
            turn_record.latency_ms = int((time.perf_counter() - _turn_t0) * 1000)
            trace.append(turn_record)

            # Relocate the single conversation cache_control marker to the last
            # tool_result so the entire conversation prefix (tools + system +
            # all prior messages + this tool result) is cached for the next
            # turn.  We remove the marker from its previous location first so
            # markers never accumulate beyond the Anthropic limit of 4.
            if tool_results:
                if conv_marker is not None:
                    conv_marker.pop("cache_control", None)
                tool_results[-1]["cache_control"] = {"type": "ephemeral"}
                conv_marker = tool_results[-1]

            messages.append({"role": "user", "content": tool_results})
            kwargs["messages"] = messages

        return CompletionResult(text="", trace=trace, hit_turn_cap=True)
