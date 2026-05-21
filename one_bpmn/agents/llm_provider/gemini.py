from google import genai
from google.genai import types

from .base import BaseLLMAdapter, ToolSpec

_MAX_TOOL_TURNS = 10


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
    ) -> str:
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

        for _ in range(_MAX_TOOL_TURNS):
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts or []
            fn_call_parts = [p for p in parts if p.function_call]

            if not fn_call_parts:
                return response.text or ""

            # Append model turn
            contents.append(types.Content(role="model", parts=parts))

            # Execute tool calls and collect responses
            result_parts = []
            for p in fn_call_parts:
                fc = p.function_call
                tool = tool_map.get(fc.name)
                if tool:
                    args = dict(fc.args) if fc.args else {}
                    try:
                        result = str(tool.fn(**args))
                    except Exception as exc:
                        result = f"Error calling {fc.name}: {exc}"
                else:
                    result = f"Unknown tool: {fc.name}"
                result_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"output": result},
                        )
                    )
                )

            contents.append(types.Content(role="user", parts=result_parts))

        return ""
