# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Antigravity SDK executor backend.

Registered as "antigravity". Runs one Gemini turn through the google-antigravity
SDK with every builtin tool, sub-agent and MCP server switched off.
"""
from __future__ import annotations

import asyncio
import random
import tempfile
import time

import frappe
from frappe import _

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
from .direct_api import DirectApiExecutor, _run_coro_blocking
from one_bpmn.agents.llm_provider import structured_output


class AntigravityExecutor(Executor):
    """Single-turn Google Antigravity SDK executor."""

    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
        try:
            from google import antigravity as sdk
            from google.antigravity.hooks import policy
        except ImportError:
            return ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message=_(
                    "The google-antigravity SDK is not installed on this bench. Run bench setup requirements."
                ),
            )

        if DirectApiExecutor._DIALECTS.get((config.provider_name or "").strip().lower()) != "Google":
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_NOT_FOUND,
                error_message=_(
                    "The Antigravity backend runs Gemini models only, so the AI Provider must be Google, not '{0}'."
                ).format(config.provider_name),
            )

        model_name = config.model or frappe.db.get_value(
            "AI Model", {"provider": config.provider_name, "enable_model": 1}, "name"
        )
        if not model_name or not frappe.db.get_value("AI Model", model_name, "enable_model"):
            return ExecutorResult(
                error_code=ErrorCode.MODEL_NOT_CONFIGURED,
                error_message=_("No enabled Google model is configured for this agent."),
            )
        api_key = frappe.utils.password.get_decrypted_password(
            "AI Model", model_name, "api_key", raise_exception=False
        )
        if not api_key:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_DISABLED,
                error_message=_(
                    "AI Model '{0}' has no API key set. Open that record and enter the Gemini API key."
                ).format(model_name),
            )
        model = frappe.db.get_value("AI Model", model_name, "model_api_name") or model_name

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

        def agent_config(workspace: str):
            return sdk.LocalAgentConfig(
                model=model,
                api_key=api_key,
                system_instructions=system_prompt or None,
                capabilities=sdk.CapabilitiesConfig(enabled_tools=[], enable_subagents=False),
                policies=[policy.deny_all()],
                workspaces=[workspace],
                save_dir=workspace,
                app_data_dir=workspace,
            )

        attempts = []
        last_error_result = None
        for attempt in range(config.max_retries + 1):
            attempt_start = time.time()
            try:
                return _run_coro_blocking(
                    asyncio.wait_for(
                        _one_turn(sdk, agent_config, config.user_prompt, config.response_format, schema, attempts),
                        timeout=config.timeout_seconds,
                    )
                )
            except Exception as exc:
                last_error_result = ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=str(exc) or type(exc).__name__,
                )

            attempts.append(AttemptRecord(
                attempt_index=attempt,
                error_code=last_error_result.error_code.value,
                error_message=last_error_result.error_message,
                latency_ms=int((time.time() - attempt_start) * 1000),
            ))
            if attempt < config.max_retries:
                time.sleep((config.retry_backoff_ms / 1000.0) * (2 ** attempt) + random.uniform(0, 0.1))

        last_error_result.attempts = list(attempts)
        return last_error_result


async def _one_turn(sdk, agent_config, user_prompt: str, response_format: str, schema, attempts: list) -> ExecutorResult:
    """Open a tool-less session, send the prompt and read the reply, asking once more when JSON can be corrected."""
    with tempfile.TemporaryDirectory(prefix="antigravity_") as workspace:
        async with sdk.Agent(agent_config(workspace)) as agent:
            response = await agent.chat(user_prompt)
            content = await response.text()
            token_usage = _usage(response.usage_metadata)
            if response_format != "json":
                return ExecutorResult(
                    output=content, token_usage=token_usage, error_code=ErrorCode.SUCCESS, attempts=list(attempts)
                )

            try:
                parsed = structured_output.read_json_reply(content, schema)
            except structured_output.ReplyRejected as exc:
                if not exc.retry:
                    return _schema_failure(exc, token_usage, attempts)
                retry = await agent.chat(structured_output.retry_note(str(exc)))
                try:
                    parsed = structured_output.read_json_reply(await retry.text(), schema)
                except structured_output.ReplyRejected as retry_exc:
                    return _schema_failure(retry_exc, token_usage, attempts)
            return ExecutorResult(
                output=parsed, token_usage=token_usage, error_code=ErrorCode.SUCCESS, attempts=list(attempts)
            )


def _schema_failure(exc, token_usage, attempts: list) -> ExecutorResult:
    return ExecutorResult(
        error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
        error_message=f"The reply is not the declared JSON: {exc}",
        token_usage=token_usage,
        attempts=list(attempts),
    )


def _usage(meta) -> TokenUsage:
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    completion = int(getattr(meta, "candidates_token_count", 0) or 0) + int(
        getattr(meta, "thoughts_token_count", 0) or 0
    )
    total = int(getattr(meta, "total_token_count", 0) or 0) or prompt + completion
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_read_tokens=int(getattr(meta, "cached_content_token_count", 0) or 0),
    )


register_executor("antigravity", AntigravityExecutor)
