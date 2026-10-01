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

import random
import time

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
from one_bpmn.agents.llm_provider import structured_output


class AntigravityExecutor(Executor):
    """Single-call Google Antigravity SDK executor."""

    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
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

        schema = None
        system_prompt = config.system_prompt
        if config.response_format == "json" and config.response_schema:
            try:
                schema = structured_output.normalize_response_schema(config.response_schema)
            except ValueError as exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"Response schema is not valid: {exc}",
                )
            system_prompt = structured_output.system_prompt_with_format(system_prompt, schema, native=False)

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
                    system_prompt=system_prompt,
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
                return self._json_result(agent, content, schema, token_usage, attempts)

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
    def _json_result(agent, content: str, schema: dict | None, token_usage, attempts: list) -> ExecutorResult:
        """Parse the reply, asking the same agent once more with the error when it can be corrected."""
        try:
            parsed = structured_output.read_json_reply(content, schema)
        except structured_output.ReplyRejected as exc:
            if not exc.retry:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"The reply is not the declared JSON: {exc}",
                    token_usage=token_usage,
                    attempts=list(attempts),
                )
            try:
                retry_text = getattr(agent.send(structured_output.retry_note(str(exc))), "text", "") or ""
            except Exception as send_exc:
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=str(send_exc),
                    token_usage=token_usage,
                    attempts=list(attempts),
                )
            try:
                parsed = structured_output.read_json_reply(retry_text, schema)
            except structured_output.ReplyRejected as retry_exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"The reply is not the declared JSON: {retry_exc}",
                    token_usage=token_usage,
                    attempts=list(attempts),
                )
        return ExecutorResult(
            output=parsed,
            token_usage=token_usage,
            error_code=ErrorCode.SUCCESS,
            attempts=list(attempts),
        )

register_executor("antigravity", AntigravityExecutor)

