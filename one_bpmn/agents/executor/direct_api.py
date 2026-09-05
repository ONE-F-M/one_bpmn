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

import asyncio
import json
import re
import random
import time
from typing import Any, ClassVar, Optional

import frappe

from one_bpmn.agents.context_assembler import build_static_context, build_dynamic_preamble

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

    The fallback copies the caller's contextvars into that thread, or the
    coroutine would run without ``frappe.local`` (site/db/session) — see
    ``turn_state.run_sync``, which carries the same contract for the nested
    call the stage tools make.
    """
    import asyncio
    import concurrent.futures
    import contextvars

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()


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



# Anthropic 5-series ids: claude-sonnet-5, claude-opus-5, claude-haiku-5 and
# their dated variants. Deliberately anchored on "-<tier>-5" so it does NOT
# catch claude-sonnet-4-5 or claude-haiku-4-5, which still accept sampling
# params — verified against the live API.
_NO_SAMPLING_PARAMS = re.compile(r"-(?:sonnet|opus|haiku)-5(?:$|[^0-9])")


def _rejects_sampling_params(model: str) -> bool:
    """True for models whose API refuses temperature / top_p."""
    return bool(_NO_SAMPLING_PARAMS.search((model or "").lower()))


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
        
        # --- Context Assembler logic ---
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
        # -------------------------------
        
        if not frappe.db.exists("AI Provider", config.provider_name):
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_NOT_FOUND,
                error_message=f"AI Provider '{config.provider_name}' not found.",
            )

        # AI Provider holds a name and nothing else, so the name is the dialect.
        provider_type = self._DIALECTS.get(
            (config.provider_name or "").strip().lower()
        )
        if not provider_type:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_NOT_FOUND,
                error_message=(
                    f"AI Provider '{config.provider_name}' is not the name of a "
                    f"dialect this executor can speak. Name the record for what "
                    f"it speaks — Anthropic, OpenAI or Google."
                ),
            )

        # The connection lives on the model now: its own key, its own endpoint,
        # and enable_model as the only on/off switch.
        model_row = frappe.db.get_value(
            "AI Model", config.model, ["enable_model", "api_endpoint"], as_dict=True
        ) if config.model else None

        if model_row and not model_row.enable_model:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_DISABLED,
                error_message=f"AI Model '{config.model}' is disabled.",
            )

        try:
            api_key = frappe.utils.password.get_decrypted_password(
                "AI Model", config.model, "api_key", raise_exception=False
            ) or "" if config.model else ""
        except Exception:
            api_key = ""

        # Fail fast on a missing key: without this guard an empty key is passed
        # straight to the provider SDK/endpoint, which surfaces a cryptic
        # low-level error (e.g. Anthropic's "Could not resolve authentication
        # method"). A clear, actionable message points the operator at the
        # exact record to fix.
        if not api_key:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_DISABLED,
                error_message=(
                    f"AI Model '{config.model}' has no API key set. "
                    f"Open that record and enter the {provider_type} API key."
                ),
            )

        endpoint = ((model_row.api_endpoint if model_row else "") or "").rstrip("/")
        if not endpoint:
            endpoint = self._DEFAULT_ENDPOINTS.get(provider_type, "")

        # The model comes from the config (the agent's catalog pick, resolved
        # upstream); the last-resort fallback is any ENABLED catalog model on
        # this provider. Enabled matters now that the catalog holds models kept
        # only for their rate card — an unpriced, disabled row is not something
        # to fall back onto.
        model = config.model or frappe.db.get_value(
            "AI Model", {"provider": provider.name, "enable_model": 1}, "name"
        ) or ""

        # What the provider's API calls this model, when that differs from the
        # catalog name agents pick.
        if model:
            model = frappe.db.get_value("AI Model", model, "model_api_name") or model

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

    # The AI Provider record's NAME, lowercased, to the dialect this executor
    # builds requests for. Aliases included because people name the record for
    # the vendor as often as for the API.
    _DIALECTS: ClassVar[dict] = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "claude": "Anthropic",
        "google": "Google",
        "gemini": "Google",
    }

    # Map dialects to agents/llm_provider factory keys. Absence means no adapter
    # exists for that dialect — with tools requested that is an explicit error,
    # never a silent fallback to the tool-less raw HTTP path.
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
                    timeout_seconds=config.timeout_seconds,
                    max_retries=config.max_retries,
                    retry_backoff_ms=config.retry_backoff_ms,
                )
            )
        except asyncio.TimeoutError:
            return ExecutorResult(
                error_code=ErrorCode.TIMEOUT,
                error_message=(
                    f"Model call exceeded aiTimeout ({config.timeout_seconds}s) "
                    f"after {config.max_retries} retr{'y' if config.max_retries == 1 else 'ies'}."
                ),
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
                    cache_read_tokens=getattr(suspension, "cache_read_tokens", 0) or 0,
                    cache_write_tokens=getattr(suspension, "cache_write_tokens", 0) or 0,
                ),
                trace=list(suspension.trace),
                suspension=asdict(suspension),
            )

        token_usage = TokenUsage(
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            total_tokens=completion.prompt_tokens + completion.completion_tokens,
            cache_read_tokens=completion.cache_read_tokens,
            cache_write_tokens=completion.cache_write_tokens,
        )
        trace = [asdict(turn) for turn in completion.trace]
        latency_ms = int((time.time() - start) * 1000)

        if completion.hit_turn_cap:
            # Partial progress is not lost: the trace collected so far ships
            # with the error result.
            return ExecutorResult(
                hit_turn_cap=True,
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
                # Say what actually came back. A tool-using agent that narrates
                # instead of answering ("Now I'll add the test cases:") fails
                # here AFTER its tool calls have committed their writes, so the
                # bare parser error left no way to tell a malformed object from
                # ordinary prose — or to see that real work had been done.
                said = (completion.text or "").strip()
                executed = [
                    call.get("name")
                    for turn in trace
                    for call in (turn.get("tool_calls") or [])
                ]
                validation_result.error_message = (
                    f"{validation_result.error_message} "
                    f"Model returned {len(said)} chars of non-JSON text"
                    f"{': ' + repr(said[:160]) if said else ''}."
                    + (
                        f" {len(executed)} tool call(s) had already run this turn "
                        f"({', '.join(dict.fromkeys(executed))}), so their writes are "
                        "committed even though this turn failed."
                        if executed
                        else ""
                    )
                )
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

        # ── Prompt caching (2 explicit breakpoints, max 4 allowed) ────────────
        # Caching is a prefix match on the rendered prompt bytes. AI Agent Task
        # system prompts and stage sub-prompts are identical across every turn
        # of a conversation, so marking them cuts repeat-input cost by ~90%.
        # 1. System prompt — sent as a content block so it can carry
        #    cache_control (a plain string cannot). Prompts below the model's
        #    minimum cacheable length are silently not cached — harmless.
        # 2. Conversation prefix — when prior history is present, the last
        #    history message gets a marker so the whole growing prefix
        #    (system + all prior turns) is a single cache read next turn.
        #    The final user_prompt stays after the marker: it varies per turn.
        if messages and config.messages:
            idx = len(config.messages) - 1
            last = dict(messages[idx])  # copy — never mutate the caller's dicts
            content = last.get("content")
            if isinstance(content, str):
                last["content"] = [{
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }]
                messages[idx] = last
            elif isinstance(content, list) and content and isinstance(content[-1], dict):
                new_content = list(content)
                new_content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
                last["content"] = new_content
                messages[idx] = last

        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": config.max_tokens,
        }
        if config.system_prompt:
            payload["system"] = [{
                "type": "text",
                "text": config.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }]

        # Anthropic does not allow both temperature and top_p simultaneously.
        # Send temperature by default; only send top_p if it was explicitly
        # changed from the default (1.0).
        #
        # The 5-series models reject sampling params outright — the API answers
        # 400 "`temperature` is deprecated for this model" — so they get neither.
        # Sending one anyway does not degrade the call, it fails it, which shows
        # up as an empty AI task output or an eval assertion that never scored.
        if not _rejects_sampling_params(config.model):
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
        """Normalise a raw provider usage dict into a TokenUsage.

        Anthropic reports cached portions separately from ``input_tokens``, so
        they are added to reach the full consumed context. OpenAI-shaped
        payloads already include cached tokens in ``prompt_tokens`` and expose
        the breakdown under ``prompt_tokens_details.cached_tokens`` — so that
        one is read, never added. Either way the cache counts are also carried
        on the TokenUsage so pricing can bill them at their own rates
        (WI-001643); previously they were folded in and discarded, which billed
        every cached token at the full input rate.
        """
        prompt = usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0
        anthropic_read = usage_raw.get("cache_read_input_tokens") or 0
        cache_write = usage_raw.get("cache_creation_input_tokens") or 0
        if anthropic_read or cache_write:
            # Anthropic shape: input_tokens EXCLUDES the cached portions.
            prompt += anthropic_read + cache_write
            cache_read = anthropic_read
        else:
            # OpenAI shape: prompt_tokens already INCLUDES the cached portion.
            details = usage_raw.get("prompt_tokens_details") or {}
            cache_read = (details or {}).get("cached_tokens") or 0
        completion = usage_raw.get("completion_tokens") or usage_raw.get("output_tokens") or 0
        total = usage_raw.get("total_tokens") or (prompt + completion)
        return TokenUsage(
            prompt_tokens=int(prompt),
            completion_tokens=int(completion),
            total_tokens=int(total),
            cache_read_tokens=int(cache_read),
            cache_write_tokens=int(cache_write),
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
