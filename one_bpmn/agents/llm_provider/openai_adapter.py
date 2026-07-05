import json
import frappe

from .base import BaseLLMAdapter, ToolSpec

_MAX_TOOL_TURNS = 10


def _build_tool_def(tool: ToolSpec) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {
                    name: {"type": info.get("type", "string"), "description": info.get("description", "")}
                    for name, info in tool.parameters.items()
                },
                "required": tool.required or [],
            },
        },
    }


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
    ) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        tool_defs = [_build_tool_def(t) for t in tools] if tools else []
        tool_map = {t.name: t for t in tools} if tools else {}

        kwargs: dict = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if tool_defs:
            kwargs["tools"] = tool_defs

        for _ in range(_MAX_TOOL_TURNS):
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]

            if choice.finish_reason != "tool_calls":
                if choice.finish_reason == "length":
                    content = choice.message.content or ""
                    frappe.log_error(
                        title="OpenAI Adapter — output truncated (max_tokens)",
                        message=(
                            f"model={self._model}  finish_reason=length  max_tokens={max_tokens}  "
                            f"content_len={len(content)}"
                        ),
                    )
                return choice.message.content or ""

            # Append assistant turn
            messages.append(choice.message)

            # Execute tool calls
            for tc in choice.message.tool_calls:
                tool = tool_map.get(tc.function.name)
                if tool:
                    try:
                        args = json.loads(tc.function.arguments)
                        result = str(tool.fn(**args))
                    except Exception as exc:
                        result = f"Error calling {tc.function.name}: {exc}"
                else:
                    result = f"Unknown tool: {tc.function.name}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            kwargs["messages"] = messages

        return ""
