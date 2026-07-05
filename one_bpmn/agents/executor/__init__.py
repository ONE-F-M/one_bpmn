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


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


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
