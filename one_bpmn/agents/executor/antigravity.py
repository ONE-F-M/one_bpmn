# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Antigravity SDK executor backend.

Registered as "antigravity". Wraps the google-antigravity SDK in
single-call (no tools, no multi-turn) mode.

If the SDK is not installed the executor returns FAILED_MODEL_CALL with a
clear message — the bench continues to function for all other task types.
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Optional

from . import (
    AttemptRecord,
    ErrorCode,
    Executor,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    TokenUsage,
    register_executor,
)
from one_bpmn.agents.context_assembler import build_static_context, build_dynamic_preamble


class AntigravityExecutor(Executor):
    """Single-call Google Antigravity SDK executor."""

    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
        # ── Context Assembler logic ────────────────────────────────
        static_ctx = ""
        dynamic_pre = ""
        
        if config.agent_config_name:
            static_ctx = build_static_context(config.agent_config_name)
        if config.active_skill_name:
            dynamic_pre = build_dynamic_preamble(config.active_skill_name)
            
        system_prompt = config.system_prompt
        if dynamic_pre:
            system_prompt = f"{dynamic_pre}\n\n{system_prompt}"
        if static_ctx:
            system_prompt = f"{system_prompt}\n\n{static_ctx}"
            
        config.system_prompt = system_prompt
        
        # ── Feature-detect the SDK ──────────────────────────────────
        # NOTE: Python ships a stdlib module named "antigravity", so a bare
        # `import antigravity` always succeeds. Verify the real SDK API
        # (the Agent class) is present before using it.
        try:
            import antigravity as _sdk
        except ImportError:
            _sdk = None
        if _sdk is None or not hasattr(_sdk, "Agent"):
            return ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message=(
                    "google-antigravity SDK is not installed. "
                    "Run: pip install google-antigravity"
                ),
            )

        attempts = []
        last_error_result = None

        for attempt in range(config.max_retries + 1):
            attempt_start = time.time()
            error_result = None
            content = None
            token_usage = None

            try:
                agent = _sdk.Agent(
                    model=config.model,
                    system_prompt=config.system_prompt,
                )
                response = agent.send(config.user_prompt)
                content = getattr(response, "text", "") or str(response)

                usage_obj = getattr(response, "usage", None)
                token_usage = TokenUsage(
                    prompt_tokens=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage_obj, "completion_tokens", 0) or 0),
                    total_tokens=int(getattr(usage_obj, "total_tokens", 0) or 0),
                )
                if not token_usage.total_tokens:
                    token_usage.total_tokens = (
                        token_usage.prompt_tokens + token_usage.completion_tokens
                    )
            except Exception as exc:
                error_result = ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=str(exc),
                )

            # ── JSON validation ───────────────────────────────────
            if error_result is None and config.response_format == "json":
                validation_result = self._validate_json(content, config.response_schema)
                if isinstance(validation_result, ExecutorResult):
                    error_result = validation_result
                else:
                    return ExecutorResult(
                        output=validation_result,
                        token_usage=token_usage,
                        error_code=ErrorCode.SUCCESS,
                        attempts=list(attempts),
                    )

            # ── Success (text format) ─────────────────────────────
            if error_result is None:
                return ExecutorResult(
                    output=content,
                    token_usage=token_usage,
                    error_code=ErrorCode.SUCCESS,
                    attempts=list(attempts),
                )

            # ── Record failed attempt and retry ───────────────────
            latency_ms = int((time.time() - attempt_start) * 1000)
            attempts.append(AttemptRecord(
                attempt_index=attempt,
                content=content or "",
                error_code=error_result.error_code.value,
                error_message=error_result.error_message,
                token_usage=token_usage,
                latency_ms=latency_ms,
            ))
            last_error_result = error_result

            if attempt < config.max_retries:
                self._sleep_backoff(config, attempt)

        # All retries exhausted
        last_error_result.attempts = list(attempts)
        return last_error_result

    @staticmethod
    def _sleep_backoff(config: ExecutorConfig, attempt: int) -> None:
        base_s = (config.retry_backoff_ms / 1000.0) * (2 ** attempt)
        jitter = random.uniform(0, 0.1)
        time.sleep(base_s + jitter)

    @staticmethod
    def _validate_json(content: str, schema_str: Optional[str]) -> Any:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            return ExecutorResult(
                error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                error_message=f"Model returned invalid JSON: {exc}",
            )

        if schema_str:
            try:
                import jsonschema
                schema = json.loads(schema_str)
                jsonschema.validate(parsed, schema)
            except ImportError:
                pass
            except json.JSONDecodeError as exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"Response schema is not valid JSON: {exc}",
                )
            except Exception as exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"JSON schema validation failed: {exc}",
                )

        return parsed


register_executor("antigravity", AntigravityExecutor)

