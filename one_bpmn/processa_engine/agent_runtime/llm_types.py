from dataclasses import dataclass, field
from typing import Callable


class LLMTruncatedError(RuntimeError):
	"""The model stopped because it hit its output-token ceiling."""


@dataclass
class ToolSpec:
	"""Provider-agnostic tool definition. A human tool suspends the loop and its fn is never called."""

	fn: Callable
	name: str
	description: str
	parameters: dict = field(default_factory=dict)
	required: list = field(default_factory=list)
	human: bool = False

	def __post_init__(self):
		"""Wrap ``fn`` with the two controls every tool call passes through."""
		if self.human:
			return

		def already(marker):
			fn, hops = self.fn, 0
			while fn is not None and hops < 10:
				if getattr(fn, marker, None) is not None:
					return True
				fn = getattr(fn, "__policy_guarded__", None) or getattr(fn, "__pii_wrapped__", None)
				hops += 1
			return False

		# The policy guard is the inner wrapper, so it sees the values after PII restoration.
		if not already("__policy_guarded__"):
			try:
				from one_bpmn.ai_agent_guardrails.tool_policy import guard

				object.__setattr__(self, "fn", guard(self.fn, self.name))
			except Exception:
				# A broken import must not make every tool unconstructable.
				pass

		if not already("__pii_wrapped__"):
			try:
				from one_bpmn.ai_agent_security.screening.pii import wrap_tool

				object.__setattr__(self, "fn", wrap_tool(self.fn))
			except Exception:
				# A broken import must not make every tool unconstructable.
				pass


def build_parameter_schema(tool: "ToolSpec") -> dict:
	"""Provider-agnostic JSON Schema ``parameters`` object for a tool spec."""
	return {
		"type": "object",
		"properties": {name: {"type": "string", **info} for name, info in tool.parameters.items()},
		"required": tool.required or [],
	}


@dataclass
class ToolCallRecord:
	"""One tool call made within a single LLM turn."""

	name: str
	arguments: dict = field(default_factory=dict)
	result: str = ""


@dataclass
class StepToolCall:
	"""One tool call requested by a single model call in the step-driven loop."""

	id: str
	name: str
	arguments: dict = field(default_factory=dict)


@dataclass
class StepResult:
	"""Return value of BaseLLMAdapter.step(): one model call and the tool calls it asked for.
	step_loop.py decides whether each call runs inline or, for a human tool, suspends the agent."""

	content: str = ""
	tool_calls: list = field(default_factory=list)  # list[StepToolCall]
	prompt_tokens: int = 0
	completion_tokens: int = 0
	cache_read_tokens: int = 0
	cache_write_tokens: int = 0
	thinking: list = field(default_factory=list)


@dataclass
class TurnRecord:
	"""One real LLM turn."""

	role: str
	content: str = ""
	tool_calls: list = field(default_factory=list)  # list[ToolCallRecord]
	prompt_tokens: int = 0
	completion_tokens: int = 0
	# Part of prompt_tokens, not added to it.
	cache_read_tokens: int = 0
	cache_write_tokens: int = 0
	latency_ms: int = 0
	model_latency_ms: int = 0
	turn_no: int = 0
	started_at: str = ""
	ended_at: str = ""


@dataclass
class CompletionResult:
	"""Return value of BaseLLMAdapter.complete(). text is empty when the turn cap ended the loop.
	no_terminal_tool is True when text is the model's own narration, not a terminal tool's reply."""

	text: str = ""
	trace: list = field(default_factory=list)  # list[TurnRecord]
	hit_turn_cap: bool = False
	no_terminal_tool: bool = False
	budget_exceeded: str = ""
	repeated_tool_error: str = ""

	@property
	def prompt_tokens(self) -> int:
		return sum(t.prompt_tokens for t in self.trace)

	@property
	def completion_tokens(self) -> int:
		return sum(t.completion_tokens for t in self.trace)

	@property
	def cache_read_tokens(self) -> int:
		return sum(getattr(t, "cache_read_tokens", 0) or 0 for t in self.trace)

	@property
	def cache_write_tokens(self) -> int:
		return sum(getattr(t, "cache_write_tokens", 0) or 0 for t in self.trace)
