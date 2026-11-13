# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The executor interface, its config and result types, and the backend registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# Same default the model adapters declare on complete() and step(); keep the two equal.
DEFAULT_MAX_OUTPUT_TOKENS = 16384

DEFAULT_TIMEOUT_SECONDS = 180

DEFAULT_TEMPERATURE = 0.3

DEFAULT_TOP_P = 1.0

DEFAULT_MAX_RETRIES = 2


class ErrorCode(Enum):
	SUCCESS = "SUCCESS"
	FAILED_MODEL_CALL = "FAILED_MODEL_CALL"
	SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
	PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
	PROVIDER_DISABLED = "PROVIDER_DISABLED"
	MODEL_NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"
	TIMEOUT = "TIMEOUT"
	TURN_CAP_REACHED = "TURN_CAP_REACHED"
	BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
	REPEATED_TOOL_ERROR = "REPEATED_TOOL_ERROR"
	UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
	# Waiting for a person: callers check it before any failure or retry handling.
	SUSPENDED = "SUSPENDED"


@dataclass
class TokenUsage:
	"""Token counts for a run or turn. prompt_tokens includes the cache read and write counts."""

	prompt_tokens: int = 0
	completion_tokens: int = 0
	total_tokens: int = 0
	cache_read_tokens: int = 0
	cache_write_tokens: int = 0

	@property
	def uncached_prompt_tokens(self) -> int:
		"""Prompt tokens billed at the full input rate."""
		return max(
			0,
			int(self.prompt_tokens) - int(self.cache_read_tokens) - int(self.cache_write_tokens),
		)


@dataclass
class AttemptRecord:
	"""Record of a single failed retry attempt."""

	attempt_index: int = 0
	content: str = ""
	error_code: str = ""  # ErrorCode.value or ""
	error_message: str = ""
	token_usage: Optional[TokenUsage] = None
	latency_ms: int = 0


@dataclass
class ExecutorConfig:
	backend: str = "direct_api"
	provider_name: str = ""
	agent_config_name: str = ""
	model: str = ""
	system_prompt: str = ""
	user_prompt: str = ""
	temperature: float = DEFAULT_TEMPERATURE
	top_p: float = DEFAULT_TOP_P
	max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
	# Applies per attempt, so the worst case is timeout x (retries + 1).
	timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
	response_format: str = "text"  # "text" | "json"
	response_schema: Optional[str] = None  # JSON Schema string
	max_retries: int = DEFAULT_MAX_RETRIES
	retry_backoff_ms: int = 1000
	messages: list = field(default_factory=list)
	tools: list | None = None
	max_tool_calls: int | None = None
	tool_result_max_chars: int | None = None
	# Set on resume: the step loop re-enters the checkpointed transcript without re-rendering prompts.
	resume_state: dict | None = None
	# Tools whose call arguments are the reply; "finalize" is always included.
	terminal_tools: list = field(default_factory=lambda: ["finalize"])
	tool_choice: str = "auto"
	parallel_tool_calls: bool = True
	thinking_budget_tokens: int = 0
	loop_compaction_threshold: int = 0
	loop_compaction_keep_turns: int = 8
	compaction_model: str = ""
	run_token_budget: int | None = None
	run_cost_budget: float | None = None


@dataclass
class ExecutorContext:
	context_doctype: str = ""
	context_docname: str = ""
	instance_name: str = ""
	initiated_by: str = ""
	jinja_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutorResult:
	output: Any = None
	token_usage: Optional[TokenUsage] = None
	error_code: ErrorCode = ErrorCode.SUCCESS
	error_message: str = ""
	raw: Any = None
	attempts: list = field(default_factory=list)  # List[AttemptRecord]
	trace: list = field(default_factory=list)
	# Set only when error_code is SUSPENDED; the checkpoint layer persists it.
	suspension: dict | None = None
	hit_turn_cap: bool = False
	no_terminal_tool: bool = False


class Executor(ABC):
	"""Abstract executor. All backends subclass this and implement run()."""

	@abstractmethod
	def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
		"""Execute one AI Agent Task. Must be implemented by every backend."""
		raise NotImplementedError


_REGISTRY: Dict[str, type] = {}


def register_executor(name: str, cls: type) -> None:
	"""Register a backend class under *name*. Called by each backend module."""
	_REGISTRY[name] = cls


def get_executor(backend_name: str) -> type:
	"""Return the Executor subclass registered under *backend_name*."""
	if backend_name not in _REGISTRY:
		raise ValueError(
			f"Unknown executor backend: {backend_name!r}. Registered backends: {sorted(_REGISTRY)}"
		)
	return _REGISTRY[backend_name]
