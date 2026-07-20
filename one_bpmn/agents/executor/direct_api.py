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
from typing import Any, ClassVar, Optional

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


def _run_coro_blocking(coro):
    """
    Run *coro* to completion from synchronous code (WI-001356 review fix).

    asyncio.run() raises RuntimeError when the calling thread already has a
    running event loop. Frappe's request handlers and RQ workers are
    synchronous today, but if this executor is ever reached from an async
    context (socketio bridge, future ASGI deployment), fall back to running
    the coroutine on a dedicated thread with its own loop instead of
    crashing.
    """
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


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


def _extract_json_object(text: str) -> Optional[dict]:
    """
    Best-effort recovery of a JSON object embedded in surrounding prose.

    Models sometimes preface the requested JSON with commentary ("Sure!
    Here is the decision: {...}") despite JSON-only instructions. Scan for
    the first parseable object literal and return it, or None.
    """
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
            continue
        if isinstance(obj, dict):
            return obj
        idx = text.find("{", idx + 1)
    return None


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
            provider = frappe.get_doc("AI Provider Credentials", config.provider_name)
        except frappe.DoesNotExistError:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_NOT_FOUND,
                error_message=f"AI Provider Credentials '{config.provider_name}' not found.",
            )

        if not provider.enabled:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_DISABLED,
                error_message=f"AI Provider Credentials '{config.provider_name}' is disabled.",
            )

        try:
            api_key = get_decrypted_password("AI Provider Credentials", config.provider_name, "api_key") or ""
        except Exception:
            api_key = ""

        provider_type = provider.provider_type or "OpenAI"
        endpoint = (provider.api_endpoint or "").rstrip("/")
        if not endpoint:
            endpoint = self._DEFAULT_ENDPOINTS.get(provider_type, "")

        # WI-001655: credentials no longer carry a default model. The model
        # comes from the config (the agent's catalog pick, resolved upstream);
        # the last-resort fallback is any catalog model linked to this record.
        model = config.model or frappe.db.get_value(
            "AI Model", {"ai_provider_credentials": provider.name}, "name"
        ) or ""

        # WI-001356: with tools present, delegate to the matching
        # agents/llm_provider adapter's multi-turn tool-calling loop. With
        # tools=None (the default) the raw HTTP path below is untouched.
        if config.tools:
            return self._run_with_tools(config, provider_type, api_key, model)

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
        last_error_result = None

        for attempt in range(config.max_retries + 1):
            attempt_start = time.time()
            error_result = None
            content = None
            token_usage = None
            data = None

            # ── HTTP request ──────────────────────────────────────
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=config.timeout_seconds,
                )
            except requests.Timeout:
                error_result = ExecutorResult(
                    error_code=ErrorCode.TIMEOUT,
                    error_message="Request timed out.",
                )
            except requests.RequestException as exc:
                error_result = ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=str(exc),
                )

            # ── HTTP status check ─────────────────────────────────
            if error_result is None:
                if resp.status_code in _TRANSIENT_STATUS_CODES:
                    error_result = ExecutorResult(
                        error_code=ErrorCode.FAILED_MODEL_CALL,
                        error_message=f"HTTP {resp.status_code}",
                    )
                else:
                    try:
                        resp.raise_for_status()
                    except requests.HTTPError as exc:
                        # Non-transient HTTP error — not retryable
                        return ExecutorResult(
                            error_code=ErrorCode.FAILED_MODEL_CALL,
                            error_message=str(exc),
                            attempts=list(attempts),
                        )

            # ── Parse response body ───────────────────────────────
            if error_result is None:
                try:
                    data = resp.json()
                except Exception:
                    error_result = ExecutorResult(
                        error_code=ErrorCode.FAILED_MODEL_CALL,
                        error_message="Provider returned non-JSON response.",
                    )

            # ── Provider-specific parsing ─────────────────────────
            if error_result is None:
                content, token_usage, parse_error = parse_fn(data)
                if parse_error:
                    error_result = parse_error

            # ── JSON schema validation ────────────────────────────
            if error_result is None and config.response_format == "json":
                validation_result = self._validate_json(content, config.response_schema)
                if isinstance(validation_result, ExecutorResult):
                    error_result = validation_result
                else:
                    return ExecutorResult(
                        output=validation_result,
                        token_usage=token_usage,
                        error_code=ErrorCode.SUCCESS,
                        raw=data,
                        attempts=list(attempts),
                    )

            # ── Success (text format) ─────────────────────────────
            if error_result is None:
                return ExecutorResult(
                    output=content,
                    token_usage=token_usage,
                    error_code=ErrorCode.SUCCESS,
                    raw=data,
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

    # ------------------------------------------------------------------
    # Request builders
    # ------------------------------------------------------------------

    # Map AI Provider Credentials.provider_type values to agents/llm_provider factory
    # keys. Absence means no adapter exists for that provider type — with
    # tools requested that is an explicit error, never a silent fallback to
    # the tool-less raw HTTP path.
    _ADAPTER_PROVIDERS: ClassVar[dict] = {
        "OpenAI": "openai",
        "Anthropic": "anthropic",
        "Google": "gemini",
    }

    def _run_with_tools(
        self, config: ExecutorConfig, provider_type: str, api_key: str, model: str
    ) -> ExecutorResult:
        """
        Tool-enabled execution path. Since the Durable AI Agent HITL work the
        loop is STEP-DRIVEN and owned by one_bpmn (agents/executor/step_loop):
        the adapter makes single model calls (step()), automatic tools execute
        inline in the loop, and a human tool suspends the run — returned as
        error_code=SUSPENDED with the checkpointable payload in .suspension.

        Automatic-only runs keep the exact WI-001356 contract: same trace
        shape, token accounting, and turn-cap error message.
        """
        from dataclasses import asdict

        from one_bpmn.agents.executor.step_loop import run_agent_loop
        from one_bpmn.agents.llm_provider.factory import get_llm_adapter

        adapter_key = self._ADAPTER_PROVIDERS.get(provider_type)
        if not adapter_key:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_NOT_FOUND,
                error_message=(
                    f"Provider type '{provider_type}' has no agents/llm_provider adapter — "
                    "tool-calling is only available for OpenAI, Anthropic and Google providers."
                ),
            )

        start = time.time()
        try:
            adapter = get_llm_adapter(adapter_key, model, api_key)
            completion, suspension = _run_coro_blocking(
                run_agent_loop(
                    adapter,
                    system=config.system_prompt,
                    user=config.user_prompt,
                    tools=config.tools,
                    max_tokens=config.max_tokens,
                    max_turns=config.max_tool_calls or 10,
                    resume=config.resume_state,
                )
            )
        except Exception as exc:
            return ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message=str(exc),
            )

        if suspension is not None:
            return ExecutorResult(
                error_code=ErrorCode.SUSPENDED,
                token_usage=TokenUsage(
                    prompt_tokens=suspension.prompt_tokens,
                    completion_tokens=suspension.completion_tokens,
                    total_tokens=suspension.prompt_tokens + suspension.completion_tokens,
                ),
                trace=list(suspension.trace),
                suspension=asdict(suspension),
            )

        token_usage = TokenUsage(
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            total_tokens=completion.prompt_tokens + completion.completion_tokens,
        )
        trace = [asdict(turn) for turn in completion.trace]
        latency_ms = int((time.time() - start) * 1000)

        if completion.hit_turn_cap:
            # Partial progress is not lost: the trace collected so far ships
            # with the error result.
            return ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message=(
                    f"Tool-calling loop hit the adapter's turn cap without a final answer "
                    f"({len(trace)} turns recorded)."
                ),
                token_usage=token_usage,
                trace=trace,
                attempts=[
                    AttemptRecord(
                        attempt_index=0,
                        error_code=ErrorCode.FAILED_MODEL_CALL.value,
                        error_message="turn cap exhausted",
                        token_usage=token_usage,
                        latency_ms=latency_ms,
                    )
                ],
            )

        # Honor the declared response format the same way the no-tools path
        # does: a "json" agent must yield a parsed (schema-valid) object, not
        # the raw final text — downstream gateways route on its keys.
        if config.response_format == "json":
            validation_result = self._validate_json(completion.text, config.response_schema)
            if isinstance(validation_result, ExecutorResult):
                validation_result.token_usage = token_usage
                validation_result.trace = trace
                return validation_result
            return ExecutorResult(
                output=validation_result,
                token_usage=token_usage,
                trace=trace,
            )

        return ExecutorResult(
            output=completion.text,
            token_usage=token_usage,
            trace=trace,
        )

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
        # Prior history (if any) precedes the rendered user_prompt. Empty by
        # default, so the payload is identical to before when unused.
        if config.messages:
            messages.extend(config.messages)
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
            # OpenAI-compatible third-party providers (DeepSeek, etc.):
            # use the older max_tokens param and send sampling parameters.
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
        # Prior history (if any) precedes the rendered user_prompt. Empty by
        # default, so the payload is identical to before when unused.
        messages = list(config.messages) if config.messages else []
        messages.append({"role": "user", "content": config.user_prompt})

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
        stripped = _strip_code_fences(content)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            # Fallback: pull the object out of surrounding prose before failing.
            parsed = _extract_json_object(stripped)
            if parsed is None:
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
