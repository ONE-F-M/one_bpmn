import json

from .base import BaseLLMAdapter, ToolSpec

_MAX_TOOL_TURNS = 10


def _build_tool_def(tool: ToolSpec) -> dict:
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
    def __init__(self, api_key: str, model: str):
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec] | None = None,
    ) -> str:
        messages = [{"role": "user", "content": user}]
        tool_defs = [_build_tool_def(t) for t in tools] if tools else []
        tool_map = {t.name: t for t in tools} if tools else {}

        kwargs: dict = {"model": self._model, "system": system, "max_tokens": 8192, "messages": messages}
        if tool_defs:
            kwargs["tools"] = tool_defs

        for _ in range(_MAX_TOOL_TURNS):
            response = await self._client.messages.create(**kwargs)

            if response.stop_reason != "tool_use":
                # Collect all text blocks
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_parts)

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            # Execute tool calls
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

            messages.append({"role": "user", "content": tool_results})
            kwargs["messages"] = messages

        return ""
