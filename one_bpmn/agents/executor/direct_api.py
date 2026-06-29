# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Direct API executor backend — single OpenAI-compatible chat/completions call.

Registered as "direct_api". Works with any provider that exposes an
OpenAI-compatible REST endpoint (OpenAI, Anthropic, Google, Bedrock,
self-hosted, etc.).

No SDK dependency: uses requests.post only.
Prompt rendering (Jinja) is performed by the dispatcher BEFORE calling run().
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Optional

import frappe
from frappe.utils.password import get_decrypted_password

from . import (
    ErrorCode,
    Executor,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    TokenUsage,
    register_executor,
)

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503})


class DirectApiExecutor(Executor):
    """Single-call OpenAI-compatible HTTP executor."""

    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
        try:
            provider = frappe.get_doc("AI Provider", config.provider_name)
        except frappe.DoesNotExistError:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_NOT_FOUND,
                error_message=f"AI Provider '{config.provider_name}' not found.",
            )

        if not provider.enabled:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_DISABLED,
                error_message=f"AI Provider '{config.provider_name}' is disabled.",
            )

        try:
            api_key = get_decrypted_password("AI Provider", config.provider_name, "api_key") or ""
        except Exception:
            api_key = ""

        endpoint = (provider.api_endpoint or "").rstrip("/")
        model = config.model or provider.default_model or ""
        provider_type = (provider.provider_type or "").strip()

        # ── Build request based on provider type ──────────────────────────
        if provider_type == "Anthropic":
            url = f"{endpoint}/messages"
            messages = [{"role": "user", "content": config.user_prompt}]
            payload = {
                "model": model,
                "messages": messages,
                "temperature": config.temperature,
                "top_p": config.top_p,
                "max_tokens": config.max_tokens,
            }
            if config.system_prompt:
                payload["system"] = config.system_prompt
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        else:
            # OpenAI-compatible (OpenAI, Google, Bedrock, self-hosted)
            url = f"{endpoint}/chat/completions"
            messages = []
            if config.system_prompt:
                messages.append({"role": "system", "content": config.system_prompt})
            messages.append({"role": "user", "content": config.user_prompt})
            payload = {
                "model": model,
                "messages": messages,
                "temperature": config.temperature,
                "top_p": config.top_p,
                "max_tokens": config.max_tokens,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

        import requests

        last_error = ""
        for attempt in range(config.max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=config.timeout_seconds,
                )
            except requests.Timeout:
                return ExecutorResult(
                    error_code=ErrorCode.TIMEOUT,
                    error_message="Request timed out.",
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=last_error,
                )

            if resp.status_code in _TRANSIENT_STATUS_CODES:
                last_error = f"HTTP {resp.status_code}"
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=last_error,
                )

            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=str(exc),
                )

            try:
                data = resp.json()
            except Exception:
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message="Provider returned non-JSON response.",
                )

            # ── Parse response based on provider type ─────────────────────
            if provider_type == "Anthropic":
                # Anthropic returns: {"content": [{"type": "text", "text": "..."}], "usage": {...}}
                content_blocks = data.get("content") or []
                content = ""
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        content += block.get("text", "")
                if not content:
                    return ExecutorResult(
                        error_code=ErrorCode.FAILED_MODEL_CALL,
                        error_message="Anthropic returned no text content.",
                        raw=data,
                    )
            else:
                # OpenAI-compatible: {"choices": [{"message": {"content": "..."}}]}
                choices = data.get("choices") or []
                if not choices:
                    return ExecutorResult(
                        error_code=ErrorCode.FAILED_MODEL_CALL,
                        error_message="Provider returned no choices.",
                        raw=data,
                    )
                content = (choices[0].get("message") or {}).get("content", "")

            token_usage = self._parse_token_usage(data.get("usage") or {})

            if config.response_format == "json":
                validation_result = self._validate_json(content, config.response_schema)
                if isinstance(validation_result, ExecutorResult):
                    return validation_result
                return ExecutorResult(
                    output=validation_result,
                    token_usage=token_usage,
                    error_code=ErrorCode.SUCCESS,
                    raw=data,
                )

            return ExecutorResult(
                output=content,
                token_usage=token_usage,
                error_code=ErrorCode.SUCCESS,
                raw=data,
            )

        return ExecutorResult(
            error_code=ErrorCode.FAILED_MODEL_CALL,
            error_message=last_error or "Max retries exceeded.",
        )

    @staticmethod
    def _sleep_backoff(config: ExecutorConfig, attempt: int) -> None:
        base_s = (config.retry_backoff_ms / 1000.0) * (2 ** attempt)
        jitter = random.uniform(0, 0.1)
        time.sleep(base_s + jitter)

    @staticmethod
    def _parse_token_usage(usage_raw: dict) -> TokenUsage:
        prompt = usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0
        completion = usage_raw.get("completion_tokens") or usage_raw.get("output_tokens") or 0
        total = usage_raw.get("total_tokens") or (prompt + completion)
        return TokenUsage(
            prompt_tokens=int(prompt),
            completion_tokens=int(completion),
            total_tokens=int(total),
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


register_executor("direct_api", DirectApiExecutor)
