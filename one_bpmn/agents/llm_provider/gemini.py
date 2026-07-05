import time

from google import genai
from google.genai import types

from .base import BaseLLMAdapter, CompletionResult, ToolCallRecord, ToolSpec, TurnRecord

_MAX_TOOL_TURNS = 10


def _usage_tokens(response) -> tuple:
    usage = getattr(response, "usage_metadata", None)
    return (
        getattr(usage, "prompt_token_count", 0) or 0,
        getattr(usage, "candidates_token_count", 0) or 0,
    )


def _build_fn_decl(tool: ToolSpec) -> types.FunctionDeclaration:
    if not tool.parameters:
        params = None
    else:
        props = {
            name: types.Schema(
                type=types.Type.STRING,
                description=info.get("description", ""),
            )
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
        for _ in range(_MAX_TOOL_TURNS):
            _turn_t0 = time.perf_counter()
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts or []
            fn_call_parts = [p for p in parts if p.function_call]
            prompt_tokens, completion_tokens = _usage_tokens(response)

            if not fn_call_parts:
                content = response.text or ""
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

            # Append model turn
            contents.append(types.Content(role="model", parts=parts))

            # Execute tool calls and collect responses; all calls of this
            # response stay grouped under ONE TurnRecord.
            turn = TurnRecord(
                role="tool",
                content="",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
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
                result_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"output": result},
                        )
                    )
                )
            # API round-trip + inline tool execution = this turn's decision latency
            turn.latency_ms = int((time.perf_counter() - _turn_t0) * 1000)
            trace.append(turn)

            contents.append(types.Content(role="user", parts=result_parts))

        return CompletionResult(text="", trace=trace, hit_turn_cap=True)
