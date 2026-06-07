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


class BaseLLMAdapter(ABC):
    """Single async entry-point for any LLM provider.

    Each provider subclass handles its own tool-calling loop internally so
    callers always receive a plain text string back.
    """

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec] | None = None,
    ) -> str:
        """Run one conversation turn (with optional multi-step tool calls) and
        return the final text response."""
