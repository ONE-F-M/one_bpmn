import json
import time

import frappe

from .base import BaseLLMAdapter, CompletionResult, ToolCallRecord, ToolSpec, TurnRecord

_MAX_TOOL_TURNS = 10


def _usage_tokens(response) -> tuple:
    usage = getattr(response, "usage", None)
    return (
        getattr(usage, "prompt_tokens", 0) or 0,
        getattr(usage, "completion_tokens", 0) or 0,
    )


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
    ) -> CompletionResult:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        tool_defs = [_build_tool_def(t) for t in tools] if tools else []
        tool_map = {t.name: t for t in tools} if tools else {}

        kwargs: dict = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if tool_defs:
            kwargs["tools"] = tool_defs

        trace = []
        for _ in range(_MAX_TOOL_TURNS):
            _turn_t0 = time.perf_counter()
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            prompt_tokens, completion_tokens = _usage_tokens(response)

            if choice.finish_reason != "tool_calls":
                content = choice.message.content or ""
                if choice.finish_reason == "length":
                    frappe.log_error(
                        title="OpenAI Adapter — output truncated (max_tokens)",
                        message=(
                            f"model={self._model}  finish_reason=length  max_tokens={max_tokens}  "
                            f"content_len={len(content)}"
                        ),
                    )
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

            # Append assistant turn
            messages.append(choice.message)

            # Execute tool calls; all calls of this response stay grouped
            # under ONE TurnRecord with the turn's real token usage.
            turn = TurnRecord(
                role="tool",
                content=choice.message.content or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            for tc in choice.message.tool_calls:
                tool = tool_map.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {"_raw": tc.function.arguments}
                if tool:
                    try:
                        result = str(tool.fn(**args))
                    except Exception as exc:
                        result = f"Error calling {tc.function.name}: {exc}"
                else:
                    result = f"Unknown tool: {tc.function.name}"

                turn.tool_calls.append(
                    ToolCallRecord(name=tc.function.name, arguments=args, result=result)
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            # API round-trip + inline tool execution = this turn's decision latency
            turn.latency_ms = int((time.perf_counter() - _turn_t0) * 1000)
            trace.append(turn)

            kwargs["messages"] = messages

        return CompletionResult(text="", trace=trace, hit_turn_cap=True)
