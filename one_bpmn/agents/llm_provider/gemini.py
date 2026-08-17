import time

from google import genai
from google.genai import types

from .base import (
    BaseLLMAdapter,
    CompletionResult,
    StepResult,
    StepToolCall,
    ToolCallRecord,
    ToolSpec,
    TurnRecord,
)

_MAX_TOOL_TURNS = 10


def _usage_tokens(response) -> tuple:
    """Returns ``(prompt, completion, cache_read, cache_write)``.

    Like OpenAI (and unlike Anthropic), Gemini's ``prompt_token_count`` already
    includes the cached portion, so ``cached_content_token_count`` is a
    breakdown of it, not an addition. Gemini bills context-cache storage by
    time rather than per write token, so cache_write is always 0 (WI-001643).
    """
    usage = getattr(response, "usage_metadata", None)
    return (
        getattr(usage, "prompt_token_count", 0) or 0,
        getattr(usage, "candidates_token_count", 0) or 0,
        getattr(usage, "cached_content_token_count", 0) or 0,
        0,
    )


_JSON_TYPE_TO_GEMINI = {
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _property_to_gemini_schema(info: dict) -> types.Schema:
    """Convert one JSON Schema property (type/description/enum/items) to a
    Gemini Schema — preserves enum and array item types instead of
    flattening everything to a bare string."""
    json_type = info.get("type", "string")
    kwargs = {
        "type": _JSON_TYPE_TO_GEMINI.get(json_type, types.Type.STRING),
        "description": info.get("description", ""),
    }
    if info.get("enum"):
        kwargs["enum"] = info["enum"]
    if json_type == "array":
        kwargs["items"] = _property_to_gemini_schema(info.get("items") or {"type": "string"})
    return types.Schema(**kwargs)


def _build_fn_decl(tool: ToolSpec) -> types.FunctionDeclaration:
    if not tool.parameters:
        params = None
    else:
        props = {
            name: _property_to_gemini_schema(info)
            for name, info in tool.parameters.items()
        }
        params = types.Schema(
            type=types.Type.OBJECT,
            properties=props,
            required=tool.required or [],
        )
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters=params,
    )


class GeminiAdapter(BaseLLMAdapter):
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def complete(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
        max_turns: int | None = None,
    ) -> CompletionResult:
        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=user)])
        ]

        genai_tools = None
        tool_map: dict[str, ToolSpec] = {}
        if tools:
            genai_tools = [
                types.Tool(function_declarations=[_build_fn_decl(t) for t in tools])
            ]
            tool_map = {t.name: t for t in tools}

        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=genai_tools,
        )

        trace = []
        for _ in range(max_turns or _MAX_TOOL_TURNS):
            _turn_t0 = time.perf_counter()
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts or []
            fn_call_parts = [p for p in parts if p.function_call]
            prompt_tokens, completion_tokens, cache_read, cache_write = _usage_tokens(response)

            if not fn_call_parts:
                content = response.text or ""
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

            # Append model turn
            contents.append(types.Content(role="model", parts=parts))

            # Execute tool calls and collect responses; all calls of this
            # response stay grouped under ONE TurnRecord.
            turn = TurnRecord(
                role="tool",
                content="",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            )
            result_parts = []
            for p in fn_call_parts:
                fc = p.function_call
                tool = tool_map.get(fc.name)
                args = dict(fc.args) if fc.args else {}
                if tool:
                    try:
                        result = str(tool.fn(**args))
                    except Exception as exc:
                        result = f"Error calling {fc.name}: {exc}"
                else:
                    result = f"Unknown tool: {fc.name}"
                turn.tool_calls.append(
                    ToolCallRecord(name=fc.name, arguments=args, result=result)
                )
                # WI-001840 AC1: same marking as the other adapters, so the
                # guard rail means the same thing whichever provider an agent
                # happens to run on.
                from one_bpmn.security.provenance import wrap_tool_result

                result_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"output": wrap_tool_result(result, fc.name, args)},
                        )
                    )
                )
            # API round-trip + inline tool execution = this turn's decision latency
            turn.latency_ms = int((time.perf_counter() - _turn_t0) * 1000)
            trace.append(turn)

            contents.append(types.Content(role="user", parts=result_parts))

        return CompletionResult(text="", trace=trace, hit_turn_cap=True)

    async def step(
        self,
        system: str,
        transcript: list,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
    ) -> StepResult:
        """One generate_content call from the provider-agnostic transcript.

        Gemini has no wire-level tool-call ids: FunctionResponse is matched
        to FunctionCall by NAME. step() synthesizes ids ("<name>::<n>") so
        the loop's id-based bookkeeping works; when rebuilding the wire
        conversation the ids are dropped and results are sent by name.
        """
        contents: list[types.Content] = []
        for entry in transcript:
            role = entry.get("role")
            if role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=entry.get("content", ""))])
                )
            elif role == "assistant":
                parts = []
                if entry.get("content"):
                    parts.append(types.Part(text=entry["content"]))
                for c in entry.get("tool_calls") or []:
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=c.get("name", ""), args=c.get("arguments") or {}
                            )
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool_results":
                parts = [
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=r.get("name", ""),
                            response={"output": r.get("content", "")},
                        )
                    )
                    for r in entry.get("results") or []
                ]
                if parts:
                    contents.append(types.Content(role="user", parts=parts))

        genai_tools = None
        if tools:
            genai_tools = [
                types.Tool(function_declarations=[_build_fn_decl(t) for t in tools])
            ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=genai_tools,
        )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0]
        parts = candidate.content.parts or []
        fn_call_parts = [p for p in parts if p.function_call]
        prompt_tokens, completion_tokens, cache_read, cache_write = _usage_tokens(response)

        tool_calls = [
            StepToolCall(
                id=f"{p.function_call.name}::{i}",
                name=p.function_call.name,
                arguments=dict(p.function_call.args) if p.function_call.args else {},
            )
            for i, p in enumerate(fn_call_parts)
        ]

        text_parts = [p.text for p in parts if getattr(p, "text", None)]
        return StepResult(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
