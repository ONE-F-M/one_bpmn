from abc import ABC, abstractmethod

from one_bpmn.processa_engine.agent_runtime.llm_types import CompletionResult, StepResult, ToolSpec


class BaseLLMAdapter(ABC):
	"""Single async entry-point for any LLM provider."""

	async def complete(
		self,
		system: str,
		user: str,
		tools: list[ToolSpec] | None = None,
		max_tokens: int = 16384,
		max_turns: int | None = None,
		temperature: float | None = None,
		top_p: float | None = None,
	) -> CompletionResult:
		"""Run one conversation (with optional multi-step tool calls) and return the final text plus the per-turn
		trace."""
		from one_bpmn.processa_engine.agent_runtime.step_loop import run_nested_loop

		return await run_nested_loop(
			self,
			system=system,
			user=user,
			tools=tools,
			max_tokens=max_tokens,
			max_turns=max_turns or 10,
			temperature=temperature,
			top_p=top_p,
		)

	@abstractmethod
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
		"""Make ONE model call against a provider-agnostic transcript and return its content + requested tool
		calls WITHOUT executing anything."""
