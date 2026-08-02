# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
agents/executor — shared interface and typed data structures for AI Agent Tasks.

This package is a pure interface layer. It declares:
  - Executor      : abstract base class all backends implement
  - ExecutorConfig: per-task configuration (backend, provider, prompts, limits)
  - ExecutorContext: runtime context (doctype/docname, instance, jinja context)
  - ExecutorResult: structured result (output, token usage, error code)
  - TokenUsage    : prompt/completion/total token counts
  - ErrorCode     : named error states shared by all backends
  - get_executor(): backend registry look-up

It makes NO LLM calls and has NO dependency on agents/llm_provider/,
agents/google_adk/, or any external LLM SDK.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class ErrorCode(Enum):
    SUCCESS = "SUCCESS"
    FAILED_MODEL_CALL = "FAILED_MODEL_CALL"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    TIMEOUT = "TIMEOUT"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
    # Durable AI Agent HITL: the model selected a human tool — the run is
    # neither success nor failure; it is waiting for a person. Callers MUST
    # branch on this before any failure/retry handling: a suspension never
    # consumes a retry and never writes error variables.
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    """Token counts for a run or turn.

    ``prompt_tokens`` is the FULL consumed input context and is inclusive of
    ``cache_read_tokens`` and ``cache_write_tokens`` — the cache fields are a
    breakdown of it, never an addition to it. Keeping the invariant means
    ``total_tokens`` and every existing consumer stay correct while cost can
    now be split by billing rate (WI-001643): cache reads bill at a fraction
    of the input rate and cache writes at a premium, so charging every prompt
    token at the full input rate overstates spend on cached workloads.

    ``uncached_prompt_tokens`` is the part billed at the standard input rate.
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def uncached_prompt_tokens(self) -> int:
        """Prompt tokens billed at the full input rate.

        Clamped at 0: a provider that reports cache counts NOT included in its
        prompt total would otherwise drive this negative.
        """
        return max(
            0,
            int(self.prompt_tokens) - int(self.cache_read_tokens) - int(self.cache_write_tokens),
        )


@dataclass
class AttemptRecord:
    """Record of a single failed retry attempt."""
    attempt_index: int = 0
    content: str = ""
    error_code: str = ""       # ErrorCode.value or ""
    error_message: str = ""
    token_usage: Optional[TokenUsage] = None
    latency_ms: int = 0


@dataclass
class ExecutorConfig:
    backend: str = "direct_api"
    provider_name: str = ""
    model: str = ""
    system_prompt: str = ""
    user_prompt: str = ""
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 1024
    timeout_seconds: int = 30
    response_format: str = "text"        # "text" | "json"
    response_schema: Optional[str] = None  # JSON Schema string
    max_retries: int = 2
    retry_backoff_ms: int = 1000
    # Optional prior message history to prime the call, same {role, content, ...}
    # shape as the conversation store. Provisional — the multi-turn loop may
    # revise this. When empty, executor behaviour is byte-for-byte unchanged.
    messages: list = field(default_factory=list)
    # WI-001356: optional list[ToolSpec]. None (default) keeps the raw HTTP
    # path byte-for-byte unchanged; when set, DirectApiExecutor delegates to
    # the matching agents/llm_provider adapter's multi-turn tool loop.
    tools: list | None = None
    # WI-001422: cap on tool-calling turns ("Maximum model calls" in Camunda);
    # None uses the adapter default. dispatch_ai_agent sets it from aiMaxToolCalls.
    max_tool_calls: int | None = None
    # Durable AI Agent HITL: persisted AgentSuspension fields + "human_result".
    # When set, the step loop re-enters the checkpointed conversation instead
    # of starting fresh (system_prompt/user_prompt are NOT re-rendered — the
    # transcript already contains the rendered originals).
    resume_state: dict | None = None


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
    # WI-001356: full turn-by-turn trace (list[TurnRecord] from
    # agents/llm_provider/base.py) when tools were used — one entry per real
    # LLM turn, each carrying its tool calls and that turn's token usage.
    # Plain dataclass field: no doctype/database migration involved.
    trace: list = field(default_factory=list)
    # Durable AI Agent HITL: JSON-serializable AgentSuspension payload, set
    # if and only if error_code == ErrorCode.SUSPENDED. This is what the
    # checkpoint layer persists.
    suspension: dict | None = None


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class Executor(ABC):
    """
    Abstract executor. All backends subclass this and implement run().

    run() must be synchronous and return an ExecutorResult for every
    possible outcome — it must never raise an exception to the caller.
    """

    @abstractmethod
    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
        """Execute one AI Agent Task. Must be implemented by every backend."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Backend registry (WI-001134)
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, type] = {}


def register_executor(name: str, cls: type) -> None:
    """Register a backend class under *name*. Called by each backend module."""
    _REGISTRY[name] = cls


def get_executor(backend_name: str) -> type:
    """
    Return the Executor subclass registered under *backend_name*.

    Raises:
        ValueError: if the name is not in the registry.
    """
    if backend_name not in _REGISTRY:
        raise ValueError(
            f"Unknown executor backend: {backend_name!r}. "
            f"Registered backends: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[backend_name]
