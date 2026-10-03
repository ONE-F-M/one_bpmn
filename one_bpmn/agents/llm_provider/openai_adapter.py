import json

import frappe

from .base import (
    BaseLLMAdapter,
    StepResult,
    StepToolCall,
    ToolSpec,
    build_parameter_schema,
)
from .structured_output import openai_response_format


# OpenAI's reasoning families reject `max_tokens` outright — the request 400s with
# "Unsupported parameter: 'max_tokens' is not supported with this model. Use
# 'max_completion_tokens' instead." Sending the wrong one makes EVERY call fail, so
# the token cap has to be named per model family, not once for the provider.
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").strip().lower()
    return any(name.startswith(prefix) for prefix in _REASONING_MODEL_PREFIXES)


def _token_cap(model: str, max_tokens: int) -> dict:
    """The output-cap kwarg under the name this model actually accepts."""
    key = "max_completion_tokens" if _is_reasoning_model(model) else "max_tokens"
    return {key: max_tokens}


def _usage_tokens(response) -> tuple:
    """Returns ``(prompt, completion, cache_read, cache_write)``.

    Unlike Anthropic, OpenAI's ``prompt_tokens`` ALREADY includes the cached
    portion, so cache_read is read out of ``prompt_tokens_details`` purely as a
    breakdown — nothing is added to the prompt total. OpenAI does not bill a
    cache-write premium, so cache_write is always 0 (WI-001643).
    """
    usage = getattr(response, "usage", None)
    details = getattr(usage, "prompt_tokens_details", None)
    cache_read = getattr(details, "cached_tokens", 0) or 0
    return (
        getattr(usage, "prompt_tokens", 0) or 0,
        getattr(usage, "completion_tokens", 0) or 0,
        cache_read,
        0,
    )


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
    def __init__(self, api_key: str, model: str, timeout_seconds: float | None = None, max_retries: int | None = None):
        from openai import AsyncOpenAI

        # Same defaults and the same None-means-forever trap as the Anthropic SDK.
        client_kwargs = {"api_key": api_key}
        if timeout_seconds:
            client_kwargs["timeout"] = timeout_seconds
        if max_retries is not None:
            client_kwargs["max_retries"] = max_retries
        self._client = AsyncOpenAI(**client_kwargs)
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

        kwargs: dict = {"model": self._model, "messages": messages}
        kwargs.update(_token_cap(self._model, max_tokens))
        if tools:
            kwargs["tools"] = [_build_tool_def(t) for t in tools]
            if tool_choice and tool_choice != "auto":
                kwargs["tool_choice"] = (
                    "required" if tool_choice == "required"
                    else {"type": "function", "function": {"name": tool_choice}}
                )
            if not parallel_tool_calls:
                kwargs["parallel_tool_calls"] = False
        if response_schema:
            kwargs["response_format"] = openai_response_format(response_schema)

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        prompt_tokens, completion_tokens, cache_read, cache_write = _usage_tokens(response)

        tool_calls = []
        # A forced tool_choice ends with finish_reason "stop" although the message carries tool calls.
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    StepToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )
        if choice.finish_reason == "length":
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
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
