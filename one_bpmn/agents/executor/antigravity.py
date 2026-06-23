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
from typing import Any, Optional

from . import (
    ErrorCode,
    Executor,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    TokenUsage,
    register_executor,
)


class AntigravityExecutor(Executor):
    """Single-call Google Antigravity SDK executor."""

    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
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

            if config.response_format == "json":
                validation_result = self._validate_json(content, config.response_schema)
                if isinstance(validation_result, ExecutorResult):
                    return validation_result
                return ExecutorResult(
                    output=validation_result,
                    token_usage=token_usage,
                    error_code=ErrorCode.SUCCESS,
                )

            return ExecutorResult(
                output=content,
                token_usage=token_usage,
                error_code=ErrorCode.SUCCESS,
            )

        except Exception as exc:
            return ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message=str(exc),
            )

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
