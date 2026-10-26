from google import genai
from google.genai import types

from .base import (
    BaseLLMAdapter,
    StepResult,
    StepToolCall,
    ToolSpec,
)


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
    def __init__(self, api_key: str, model: str, timeout_seconds: float | None = None, max_retries: int | None = None):
        # genai takes its timeout in milliseconds and its retries as a count of attempts.
        http_options = types.HttpOptions(
            timeout=int(timeout_seconds * 1000) if timeout_seconds else None,
            retry_options=types.HttpRetryOptions(attempts=max_retries + 1) if max_retries is not None else None,
        )
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._model = model

    async def step(
        self,
        system: str,
        transcript: list,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
        tool_choice: str | None = None,
        parallel_tool_calls: bool = True,
        thinking_budget_tokens: int = 0,
        temperature: float | None = None,
        top_p: float | None = None,
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
            tool_config=_tool_config(tool_choice) if genai_tools else None,
            temperature=temperature,
            top_p=top_p,
            thinking_config=(
                types.ThinkingConfig(thinking_budget=thinking_budget_tokens) if thinking_budget_tokens else None
            ),
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


def _tool_config(tool_choice: str | None) -> types.ToolConfig | None:
    """Gemini's function-calling mode for "required" or a tool name; None leaves it on AUTO."""
    if not tool_choice or tool_choice == "auto":
        return None
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY,
            allowed_function_names=None if tool_choice == "required" else [tool_choice],
        )
    )
