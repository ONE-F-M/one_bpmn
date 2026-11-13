import re

from processa.processa_engine.agent_runtime.llm_base import BaseLLMAdapter
from processa.processa_engine.agent_runtime.llm_types import (
	LLMTruncatedError,
	StepResult,
	StepToolCall,
	ToolSpec,
	build_parameter_schema,
)
from processa.processa_engine.agent_runtime.structured_output import anthropic_output_config

_NO_FORCED_TOOL_CHOICE = re.compile(r"-(?:opus|sonnet)-5-5|fable")
_ADAPTIVE_THINKING = re.compile(r"-(?:sonnet|opus|haiku)-5(?:$|[^0-9])|fable")


def _usage_tokens(response) -> tuple:
	"""Real token counts for the turn."""
	usage = getattr(response, "usage", None)
	cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
	cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
	prompt = (getattr(usage, "input_tokens", 0) or 0) + cache_read + cache_write
	return prompt, getattr(usage, "output_tokens", 0) or 0, cache_read, cache_write


def _build_tool_def(tool: ToolSpec) -> dict:
	"""Build an Anthropic tool definition from a ToolSpec."""
	return {
		"name": tool.name,
		"description": tool.description,
		"input_schema": build_parameter_schema(tool),
	}


# Anthropic rejects an empty text or tool_result block with a 400, so empty content is sent as words.
_EMPTY_PLACEHOLDER = "(no content was returned)"


def _nonempty(value) -> str:
	text = "" if value is None else str(value)
	return text if text.strip() else _EMPTY_PLACEHOLDER


async def _forward_text(stream) -> None:
	"""Send each text delta to the chat request waiting on this turn, if any."""
	try:
		from processa.processa_engine.agent_runtime.turn_signal import live_text_sink

		sink = live_text_sink()
	except Exception:
		sink = None
	if sink is None:
		return
	try:
		async for event in stream:
			if getattr(event, "type", None) == "text" and getattr(event, "text", ""):
				sink(event.text)
	except Exception:
		pass


class AnthropicAdapter(BaseLLMAdapter):
	"""Anthropic Messages API adapter with prompt caching."""

	def __init__(
		self, api_key: str, model: str, timeout_seconds: float | None = None, max_retries: int | None = None
	):
		import anthropic

		# Set the timeout and retries explicitly: to this client None means wait forever.
		client_kwargs = {"api_key": api_key}
		if timeout_seconds:
			client_kwargs["timeout"] = timeout_seconds
		if max_retries is not None:
			client_kwargs["max_retries"] = max_retries
		self._client = anthropic.AsyncAnthropic(**client_kwargs)
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
		temperature: float | None = None,
		top_p: float | None = None,
	) -> StepResult:
		"""One Messages API call from the provider-agnostic transcript."""
		tool_defs = [_build_tool_def(t) for t in tools] if tools else []
		if tool_defs:
			tool_defs[-1]["cache_control"] = {"type": "ephemeral"}

		system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

		first_result = next(
			(i for i, e in enumerate(transcript) if e.get("role") == "tool_results"), len(transcript)
		)
		turn_at = max(
			(i for i, e in enumerate(transcript[:first_result]) if e.get("role") == "user"), default=0
		)
		messages = []
		last_tool_result_block = None
		last_history_message = None
		for index, entry in enumerate(transcript):
			if index == turn_at and messages:
				last_history_message = messages[-1]
			role = entry.get("role")
			if role == "user":
				messages.append(
					{
						"role": "user",
						"content": [{"type": "text", "text": _nonempty(entry.get("content"))}],
					}
				)
			elif role == "assistant":
				blocks = list(entry.get("thinking") or [])
				if entry.get("content"):
					blocks.append({"type": "text", "text": entry["content"]})
				for c in entry.get("tool_calls") or []:
					blocks.append(
						{
							"type": "tool_use",
							"id": c.get("id", ""),
							"name": c.get("name", ""),
							"input": c.get("arguments") or {},
						}
					)
				messages.append({"role": "assistant", "content": blocks})
			elif role == "tool_results":
				blocks = [
					{
						"type": "tool_result",
						"tool_use_id": r.get("id", ""),
						"content": _nonempty(r.get("content")),
					}
					for r in entry.get("results") or []
				]
				if blocks:
					last_tool_result_block = blocks[-1]
					messages.append({"role": "user", "content": blocks})
		if last_history_message is not None and last_history_message["content"]:
			last_history_message["content"][-1]["cache_control"] = {"type": "ephemeral"}
		if last_tool_result_block is not None:
			last_tool_result_block["cache_control"] = {"type": "ephemeral"}
		elif messages and messages[-1]["role"] == "user":
			messages[-1]["content"] = _split_cacheable_prefix(messages[-1]["content"][0]["text"])

		thinking = bool(thinking_budget_tokens) and not _ADAPTIVE_THINKING.search(self._model.lower())
		kwargs: dict = {
			"model": self._model,
			"system": system_blocks,
			"max_tokens": max_tokens,
			"messages": messages,
		}
		if tool_defs:
			kwargs["tools"] = tool_defs
			choice = _tool_choice(
				tool_choice,
				forced_allowed=not thinking and not _NO_FORCED_TOOL_CHOICE.search(self._model.lower()),
			)
			if not parallel_tool_calls:
				choice["disable_parallel_tool_use"] = True
			if choice != {"type": "auto"}:
				kwargs["tool_choice"] = choice
		if thinking:
			kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget_tokens}
		elif top_p is not None and top_p < 1.0:
			kwargs["top_p"] = top_p
		elif temperature is not None:
			kwargs["temperature"] = temperature
		if response_schema:
			kwargs["output_config"] = anthropic_output_config(response_schema)

		async with self._client.messages.stream(**kwargs) as stream:
			await _forward_text(stream)
			response = await stream.get_final_message()

		if response.stop_reason == "max_tokens":
			raise LLMTruncatedError(
				f"The model hit its {max_tokens}-token output limit before "
				"finishing. Raise Max Tokens on the agent configuration (or "
				"the task shape) and try again."
			)

		prompt_tokens, completion_tokens, cache_read, cache_write = _usage_tokens(response)
		text_parts = [b.text for b in response.content if hasattr(b, "text")]
		tool_calls = [
			StepToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
			for b in response.content
			if b.type == "tool_use"
		]

		return StepResult(
			content="\n".join(text_parts),
			tool_calls=tool_calls if response.stop_reason == "tool_use" else [],
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			cache_read_tokens=cache_read,
			cache_write_tokens=cache_write,
			thinking=[
				_thinking_block(b) for b in response.content if b.type in ("thinking", "redacted_thinking")
			],
		)


def _tool_choice(tool_choice: str | None, *, forced_allowed: bool) -> dict:
	"""The Anthropic tool_choice for "auto", "required" or a tool name; "auto" where forcing is refused."""
	if not tool_choice or tool_choice == "auto" or not forced_allowed:
		return {"type": "auto"}
	if tool_choice == "required":
		return {"type": "any"}
	return {"type": "tool", "name": tool_choice}


def _thinking_block(block) -> dict:
	if block.type == "redacted_thinking":
		return {"type": "redacted_thinking", "data": block.data}
	return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}


def _split_cacheable_prefix(user: str) -> list:
	"""Split a user prompt into a cached context prefix and the request after it, when it has both."""
	match = re.search(
		r"(\n+(?:User message|User request|User prompt|Request):\s*)(.*)$",
		user,
		re.IGNORECASE | re.DOTALL,
	)
	if not match or not user[: match.start()].strip():
		return [{"type": "text", "text": _nonempty(user)}]
	return [
		{"type": "text", "text": user[: match.start()].strip(), "cache_control": {"type": "ephemeral"}},
		{"type": "text", "text": (match.group(1) + match.group(2)).strip()},
	]
