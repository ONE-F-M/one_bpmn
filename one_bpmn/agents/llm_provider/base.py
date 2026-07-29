from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolSpec:
    """Provider-agnostic tool definition.

    parameters: JSON Schema "properties" dict — {param_name: {type, description}}
    required:   list of required parameter names
    human:      a human-in-the-loop tool (a User/Manual shape). The step-driven
                loop never executes it inline — selecting it suspends the agent
                until a person completes the spawned task and the loop resumes
                with their output as the tool result. fn is never called.
    """
    fn: Callable
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    required: list = field(default_factory=list)
    human: bool = False


def build_parameter_schema(tool: "ToolSpec") -> dict:
    """Provider-agnostic JSON Schema ``parameters`` object for a tool spec.

    Passes each parameter's schema through as-is (enum, items, etc. included)
    rather than keeping only type/description — a shape's aiToolParams may
    document constraints (e.g. an enum of allowed doctypes) that the LLM
    needs in order to call the tool correctly.
    """
    return {
        "type": "object",
        "properties": {
            name: {"type": "string", **info}
            for name, info in tool.parameters.items()
        },
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
    """One tool call requested by a single model call in the step-driven loop.

    id is the provider's tool-call id (synthesized for providers without one,
    e.g. Gemini) — the loop echoes it back in the matching tool result.
    """
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class StepResult:
    """Return value of BaseLLMAdapter.step() — ONE model call, no tool
    execution. The externally-driven loop (agents/executor/step_loop.py)
    decides what happens to each requested call: execute it inline, or —
    for a human tool — suspend the agent."""
    content: str = ""
    tool_calls: list = field(default_factory=list)  # list[StepToolCall]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Breakdown of prompt_tokens by billing rate (WI-001643) — see TurnRecord.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class TurnRecord:
    """One real LLM turn (WI-001356).

    A single turn can contain several tool calls — they stay grouped under
    the turn that produced them, with one shared token figure for the turn
    (never a fabricated per-call cost). role is "tool" for turns that made
    tool calls and "assistant" for the final-answer turn, matching the AI
    Agent Step role options (WI-001358 builds one Step per TurnRecord).
    """
    role: str
    content: str = ""
    tool_calls: list = field(default_factory=list)  # list[ToolCallRecord]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Breakdown of prompt_tokens by billing rate (WI-001643). INCLUSIVE: these
    # are part of prompt_tokens, not extra on top of it, so the turn's consumed
    # context stays one number while cost can be split three ways (uncached
    # input / cache read / cache write). Providers that charge nothing extra for
    # cache writes (OpenAI, Gemini) report reads only and leave writes at 0.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Wall-clock for this turn: the provider API round-trip plus any inline
    # tool executions. Decision latency — NOT the runtime of an activated
    # diagram task (that happens later in the engine).
    latency_ms: int = 0


@dataclass
class CompletionResult:
    """Return value of BaseLLMAdapter.complete().

    text is the final answer (empty when the tool loop hit its turn cap —
    hit_turn_cap distinguishes that from a legitimately empty answer);
    trace is the full turn-by-turn record, one TurnRecord per real LLM turn.
    """
    text: str = ""
    trace: list = field(default_factory=list)  # list[TurnRecord]
    hit_turn_cap: bool = False

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


class BaseLLMAdapter(ABC):
    """Single async entry-point for any LLM provider.

    Each provider subclass handles its own tool-calling loop internally.
    complete() returns a CompletionResult carrying both the final answer
    text and the full turn-by-turn trace — earlier versions returned a bare
    string and discarded every intermediate turn's tool calls and token
    usage (contract change made explicitly in scope by WI-001356).
    """

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
        max_turns: int | None = None,
    ) -> CompletionResult:
        """Run one conversation (with optional multi-step tool calls) and
        return the final text plus the per-turn trace."""

    async def step(
        self,
        system: str,
        transcript: list,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16384,
    ) -> StepResult:
        """Make ONE model call against a provider-agnostic transcript and
        return its content + requested tool calls WITHOUT executing anything.

        The transcript is a JSON-serializable list (it must survive a DB
        checkpoint round-trip) of entries::

            {"role": "user",         "content": str}
            {"role": "assistant",    "content": str,
             "tool_calls": [{"id": str, "name": str, "arguments": dict}]}
            {"role": "tool_results", "results":
             [{"id": str, "name": str, "content": str}]}

        Each adapter converts this to its wire format. complete() keeps its
        adapter-internal loop for existing callers; the AI Agent Task's
        step-driven loop (agents/executor/step_loop.py) uses step() only.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement step()")
