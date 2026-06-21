import json
import logging

from .base import BaseLLMAdapter, ToolSpec

_MAX_TOOL_TURNS = 10

logger = logging.getLogger(__name__)


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

    Caching strategy (3 explicit breakpoints, max 4 allowed):
      1. **Tools**  – ``cache_control`` on the last tool definition caches
         the entire tool-definition prefix.  Tools never change within a
         single ``complete()`` invocation, so this is always a cache hit
         from turn 2 onwards.
      2. **System prompt** – ``cache_control`` on the system text block.
         The system prompt is identical across every turn within a call.
      3. **Automatic (top-level)** – ``cache_control`` at the request
         level causes the API to place a breakpoint on the last cacheable
         block in ``messages``.  As the conversation grows with
         assistant+tool_result turns, the breakpoint advances
         automatically, caching the entire growing prefix.

    On each tool-result turn the last ``tool_result`` block also gets an
    explicit ``cache_control`` marker so that the *next* LLM call within
    the same invocation benefits from the lookback window even when the
    message count exceeds 20 blocks.

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
    ) -> str:
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

        # ── Breakpoint 3: Top-level automatic caching ─────────────────────────
        # The API automatically places the breakpoint on the last cacheable
        # block in each request.  As tool turns are appended, the breakpoint
        # advances with the growing conversation — no manual management needed.
        kwargs: dict = {
            "model": self._model,
            "system": system_blocks,
            "max_tokens": max_tokens,
            "messages": messages,
            "cache_control": {"type": "ephemeral"},
        }
        if tool_defs:
            kwargs["tools"] = tool_defs

        for turn in range(_MAX_TOOL_TURNS):
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

        return ""
