import json
import time

import frappe

from .base import (
    BaseLLMAdapter,
    CompletionResult,
    StepResult,
    StepToolCall,
    StreamEvent,
    ToolCallRecord,
    ToolSpec,
    TurnRecord,
    build_parameter_schema,
)

_MAX_TOOL_TURNS = 10


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

        kwargs: dict = {"model": self._model, "messages": messages}
        kwargs.update(_token_cap(self._model, max_tokens))
        if tool_defs:
            kwargs["tools"] = tool_defs

        trace = []
        for _ in range(max_turns or _MAX_TOOL_TURNS):
            _turn_t0 = time.perf_counter()
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            prompt_tokens, completion_tokens, cache_read, cache_write = _usage_tokens(response)

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
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
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
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
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
                # The model reads tool output through the same
                # channel as its own instructions, so it is marked with the tool
                # that produced it — that marker is what the seeded guard rail
                # refers to. The ToolCallRecord above keeps the raw result; the
                # wrapper is for the model, not the audit trail.
                from one_bpmn.security.provenance import wrap_tool_result

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": wrap_tool_result(result, tc.function.name, args),
                })
            # API round-trip + inline tool execution = this turn's decision latency
            turn.latency_ms = int((time.perf_counter() - _turn_t0) * 1000)
            trace.append(turn)

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

        kwargs: dict = {"model": self._model, "messages": messages}
        kwargs.update(_token_cap(self._model, max_tokens))
        if tools:
            kwargs["tools"] = [_build_tool_def(t) for t in tools]

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        prompt_tokens, completion_tokens, cache_read, cache_write = _usage_tokens(response)

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
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )

    async def stream(
        self,
        system: str,
        transcript: list,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
    ):
        """Incremental sibling of step(): the same wire request as step(),
        with ``stream=True`` so content and tool-call fragments arrive as
        chunks instead of one blocking response.

        OpenAI sends tool-call arguments as a running string split across
        many chunks, indexed by position in the call list \u2014 there is no
        signal that a call is COMPLETE other than the stream ending (or the
        next chunk starting a new index), so tool_call_start/end are both
        emitted only once every chunk has been folded into the accumulator
        below, exactly like the non-streaming parse.
        """
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

        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        kwargs.update(_token_cap(self._model, max_tokens))
        if tools:
            kwargs["tools"] = [_build_tool_def(t) for t in tools]

        content_parts: list[str] = []
        # index -> {"id", "name", "arguments"} accumulator.
        call_accum: dict[int, dict] = {}
        finish_reason = None
        prompt_tokens = completion_tokens = cache_read = 0

        response_stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in response_stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                details = getattr(usage, "prompt_tokens_details", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                cache_read = getattr(details, "cached_tokens", 0) or 0
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta
            if delta and delta.content:
                content_parts.append(delta.content)
                yield StreamEvent(type="text_delta", delta=delta.content)
            for tc_delta in delta.tool_calls or []:
                slot = call_accum.setdefault(
                    tc_delta.index, {"id": "", "name": "", "arguments": ""}
                )
                if tc_delta.id:
                    slot["id"] = tc_delta.id
                if tc_delta.function and tc_delta.function.name:
                    slot["name"] = tc_delta.function.name
                if tc_delta.function and tc_delta.function.arguments:
                    slot["arguments"] += tc_delta.function.arguments

        tool_calls = []
        if finish_reason == "tool_calls":
            for slot in call_accum.values():
                try:
                    args = json.loads(slot["arguments"]) if slot["arguments"] else {}
                except Exception:
                    args = {"_raw": slot["arguments"]}
                call = StepToolCall(id=slot["id"], name=slot["name"], arguments=args)
                tool_calls.append(call)
                yield StreamEvent(type="tool_call_start", tool_call=call)
                yield StreamEvent(type="tool_call_end", tool_call=call)

        yield StreamEvent(
            type="done",
            step=StepResult(
                content="".join(content_parts),
                tool_calls=tool_calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=0,
            ),
        )
