import json
import frappe

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


def _build_tool_def(tool: ToolSpec) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": build_parameter_schema(tool),
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
        max_turns: int | None = None,
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
        for _ in range(max_turns or _MAX_TOOL_TURNS):
            _turn_t0 = time.perf_counter()
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

        return CompletionResult(text="", trace=trace, hit_turn_cap=True)

    async def step(
        self,
        system: str,
        transcript: list,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
    ) -> StepResult:
        messages = [{"role": "system", "content": system}]
        for entry in transcript:
            role = entry.get("role")
            if role == "user":
                messages.append({"role": "user", "content": entry.get("content", "")})
            elif role == "assistant":
                msg = {"role": "assistant", "content": entry.get("content") or None}
                calls = entry.get("tool_calls") or []
                if calls:
                    msg["tool_calls"] = [
                        {
                            "id": c.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": c.get("name", ""),
                                "arguments": json.dumps(c.get("arguments") or {}),
                            },
                        }
                        for c in calls
                    ]
                messages.append(msg)
            elif role == "tool_results":
                for r in entry.get("results") or []:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": r.get("id", ""),
                        "content": r.get("content", ""),
                    })

        kwargs: dict = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            kwargs["tools"] = [_build_tool_def(t) for t in tools]

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        prompt_tokens, completion_tokens = _usage_tokens(response)

        tool_calls = []
        if choice.finish_reason == "tool_calls":
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    StepToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )
        elif choice.finish_reason == "length":
            frappe.log_error(
                title="OpenAI Adapter — output truncated (max_tokens)",
                message=(
                    f"model={self._model}  finish_reason=length  max_tokens={max_tokens}  "
                    f"content_len={len(choice.message.content or '')}"
                ),
            )

        return StepResult(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
