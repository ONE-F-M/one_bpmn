from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolSpec:
    """Provider-agnostic tool definition.

    parameters: JSON Schema "properties" dict — {param_name: {type, description}}
    required:   list of required parameter names
    """
    fn: Callable
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    required: list = field(default_factory=list)


@dataclass
class ToolCallRecord:
    """One tool call made within a single LLM turn."""
    name: str
    arguments: dict = field(default_factory=dict)
    result: str = ""


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
    ) -> CompletionResult:
        """Run one conversation (with optional multi-step tool calls) and
        return the final text plus the per-turn trace."""
