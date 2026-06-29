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
    AttemptRecord,
    ErrorCode,
    Executor,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    TokenUsage,
    register_executor,
)


def _strip_code_fences(content: str) -> str:
    """
    Remove a surrounding Markdown code fence from *content*, if present.

    Models (notably Anthropic) frequently wrap JSON responses in ```json …```
    fences even when asked for raw JSON. This strips an opening fence line
    (``` or ```json) and a trailing ``` so the inner payload can be parsed.
    Content without fences is returned stripped but otherwise unchanged.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1:]
        else:
            text = text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503})


class DirectApiExecutor(Executor):
    """Single-call HTTP executor supporting OpenAI-compatible and Anthropic APIs."""

    # Default endpoints per provider type (used when api_endpoint is blank).
    _DEFAULT_ENDPOINTS = {
        "OpenAI": "https://api.openai.com/v1",
        "Anthropic": "https://api.anthropic.com",
        "Google": "https://generativelanguage.googleapis.com/v1beta",
    }

    # Anthropic API version header required by their Messages API.
    _ANTHROPIC_API_VERSION = "2023-06-01"


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

        provider_type = provider.provider_type or "OpenAI"
        endpoint = (provider.api_endpoint or "").rstrip("/")
        if not endpoint:
            endpoint = self._DEFAULT_ENDPOINTS.get(provider_type, "")

        model = config.model or provider.default_model or ""

        if provider_type == "Anthropic":
            url, payload, headers = self._build_anthropic_request(
                endpoint, api_key, model, config,
            )
            parse_fn = self._parse_anthropic_response
        else:
            url, payload, headers = self._build_openai_request(
                endpoint, api_key, model, config, provider_type,
            )
            parse_fn = self._parse_openai_response

        import requests

        attempts = []
        last_error_code = ErrorCode.FAILED_MODEL_CALL
        last_error_message = ""

        for attempt in range(config.max_retries + 1):
            attempt_start = time.time()

            # ── HTTP call ──────────────────────────────────────────
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=config.timeout_seconds,
                )
            except requests.Timeout:
                # Timeouts are not retried — they usually indicate
                # a genuinely slow model, not a transient glitch.
                latency_ms = int((time.time() - attempt_start) * 1000)
                attempts.append(AttemptRecord(
                    attempt_index=attempt,
                    error_code=ErrorCode.TIMEOUT.value,
                    error_message="Request timed out.",
                    latency_ms=latency_ms,
                ))
                return ExecutorResult(
                    error_code=ErrorCode.TIMEOUT,
                    error_message="Request timed out.",
                    attempts=attempts,
                )
            except requests.RequestException as exc:
                latency_ms = int((time.time() - attempt_start) * 1000)
                last_error_code = ErrorCode.FAILED_MODEL_CALL
                last_error_message = str(exc)
                attempts.append(AttemptRecord(
                    attempt_index=attempt,
                    error_code=last_error_code.value,
                    error_message=last_error_message,
                    latency_ms=latency_ms,
                ))
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=last_error_code,
                    error_message=last_error_message,
                    attempts=attempts,
                )

            latency_ms = int((time.time() - attempt_start) * 1000)

            # ── Transient HTTP errors ──────────────────────────────
            if resp.status_code in _TRANSIENT_STATUS_CODES:
                last_error_code = ErrorCode.FAILED_MODEL_CALL
                last_error_message = f"HTTP {resp.status_code}"
                attempts.append(AttemptRecord(
                    attempt_index=attempt,
                    error_code=last_error_code.value,
                    error_message=last_error_message,
                    latency_ms=latency_ms,
                ))
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=last_error_code,
                    error_message=last_error_message,
                    attempts=attempts,
                )

            # ── Non-transient HTTP errors ──────────────────────────
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                # Include the response body for debugging (Anthropic, etc.
                # return detailed error messages in the body).
                body_text = ""
                try:
                    body = resp.json()
                    err = body.get("error", {})
                    body_text = err.get("message") or err.get("type") or resp.text[:500]
                except Exception:
                    body_text = (resp.text or "")[:500]
                error_msg = f"{exc}"
                if body_text:
                    error_msg = f"{exc} — {body_text}"
                attempts.append(AttemptRecord(
                    attempt_index=attempt,
                    error_code=ErrorCode.FAILED_MODEL_CALL.value,
                    error_message=error_msg,
                    latency_ms=latency_ms,
                ))
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=error_msg,
                    attempts=attempts,
                )

            # ── Parse response body ────────────────────────────────
            try:
                data = resp.json()
            except Exception:
                last_error_code = ErrorCode.FAILED_MODEL_CALL
                last_error_message = "Provider returned non-JSON response."
                attempts.append(AttemptRecord(
                    attempt_index=attempt,
                    error_code=last_error_code.value,
                    error_message=last_error_message,
                    latency_ms=latency_ms,
                ))
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=last_error_code,
                    error_message=last_error_message,
                    attempts=attempts,
                )

            # ── Provider-specific response parsing ─────────────────
            content, token_usage, parse_error = parse_fn(data)
            if parse_error:
                last_error_code = parse_error.error_code
                last_error_message = parse_error.error_message
                attempts.append(AttemptRecord(
                    attempt_index=attempt,
                    content=content or "",
                    error_code=last_error_code.value,
                    error_message=last_error_message,
                    token_usage=token_usage,
                    latency_ms=latency_ms,
                ))
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=last_error_code,
                    error_message=last_error_message,
                    attempts=attempts,
                )

            # ── JSON validation (if response_format == "json") ─────
            if config.response_format == "json":
                validation_result = self._validate_json(content, config.response_schema)
                if isinstance(validation_result, ExecutorResult):
                    # Schema validation failed — retryable
                    last_error_code = validation_result.error_code
                    last_error_message = validation_result.error_message
                    attempts.append(AttemptRecord(
                        attempt_index=attempt,
                        content=content or "",
                        error_code=last_error_code.value,
                        error_message=last_error_message,
                        token_usage=token_usage,
                        latency_ms=latency_ms,
                    ))
                    if attempt < config.max_retries:
                        self._sleep_backoff(config, attempt)
                        continue
                    return ExecutorResult(
                        error_code=last_error_code,
                        error_message=last_error_message,
                        attempts=attempts,
                    )
                return ExecutorResult(
                    output=validation_result,
                    token_usage=token_usage,
                    error_code=ErrorCode.SUCCESS,
                    raw=data,
                    attempts=attempts,
                )

            # ── Success (text format) ──────────────────────────────
            return ExecutorResult(
                output=content,
                token_usage=token_usage,
                error_code=ErrorCode.SUCCESS,
                raw=data,
                attempts=attempts,
            )

        # Should not reach here, but safety net
        return ExecutorResult(
            error_code=last_error_code,
            error_message=last_error_message or "Max retries exceeded.",
            attempts=attempts,
        )

    # ------------------------------------------------------------------
    # Request builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_openai_request(
        endpoint: str, api_key: str, model: str, config: ExecutorConfig,
        provider_type: str = "OpenAI",
    ) -> tuple:
        """Build URL, payload, and headers for OpenAI-compatible APIs."""
        url = f"{endpoint}/chat/completions"
        messages = []
        if config.system_prompt:
            messages.append({"role": "system", "content": config.system_prompt})
        messages.append({"role": "user", "content": config.user_prompt})

        payload = {
            "model": model,
            "messages": messages,
        }

        if provider_type == "OpenAI":
            # Native OpenAI: use max_completion_tokens (required by newer
            # models like o1, o3, gpt-5.x). Omit temperature/top_p so
            # reasoning models that only accept default(1) don't error.
            payload["max_completion_tokens"] = config.max_tokens
        else:
            # OpenAI-compatible third-party providers: use the older
            # max_tokens param and always send sampling parameters.
            payload["max_tokens"] = config.max_tokens
            payload["temperature"] = config.temperature
            payload["top_p"] = config.top_p

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return url, payload, headers

    def _build_anthropic_request(
        self, endpoint: str, api_key: str, model: str, config: ExecutorConfig,
    ) -> tuple:
        """Build URL, payload, and headers for Anthropic Messages API."""
        url = f"{endpoint}/v1/messages"

        # Anthropic uses a top-level "system" field, not a system message.
        messages = [{"role": "user", "content": config.user_prompt}]

        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": config.max_tokens,
        }
        if config.system_prompt:
            payload["system"] = config.system_prompt

        # Anthropic does not allow both temperature and top_p simultaneously.
        # Send temperature by default; only send top_p if it was explicitly
        # changed from the default (1.0).
        if config.top_p < 1.0:
            payload["top_p"] = config.top_p
        else:
            payload["temperature"] = config.temperature

        headers = {
            "x-api-key": api_key,
            "anthropic-version": self._ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }
        return url, payload, headers

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    def _parse_openai_response(self, data: dict):
        """Parse an OpenAI-compatible response. Returns (content, token_usage, error_or_None)."""
        choices = data.get("choices") or []
        if not choices:
            return None, None, ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message="Provider returned no choices.",
                raw=data,
            )
        content = (choices[0].get("message") or {}).get("content", "")
        token_usage = self._parse_token_usage(data.get("usage") or {})
        return content, token_usage, None

    def _parse_anthropic_response(self, data: dict):
        """Parse an Anthropic Messages API response. Returns (content, token_usage, error_or_None)."""
        content_blocks = data.get("content") or []
        if not content_blocks:
            return None, None, ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message="Anthropic returned no content blocks.",
                raw=data,
            )
        # Concatenate all text blocks (Anthropic may return multiple).
        text_parts = [
            block.get("text", "") for block in content_blocks
            if block.get("type") == "text"
        ]
        content = "".join(text_parts)
        token_usage = self._parse_token_usage(data.get("usage") or {})
        return content, token_usage, None

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
            parsed = json.loads(_strip_code_fences(content))
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
