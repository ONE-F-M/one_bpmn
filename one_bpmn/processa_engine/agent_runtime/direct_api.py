# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Direct API executor backend: one chat call, or the step loop when the task has tools."""

from __future__ import annotations

import asyncio
import dataclasses
import random
import time
from typing import Any, ClassVar

import frappe
from frappe import _

from one_bpmn.processa_engine.agent_runtime.executor import (
	AttemptRecord,
	ErrorCode,
	Executor,
	ExecutorConfig,
	ExecutorContext,
	ExecutorResult,
	TokenUsage,
	register_executor,
)
from one_bpmn.processa_engine.agent_runtime import structured_output


def run_coro_blocking(coro):
	"""Run *coro* to completion from synchronous code review fix)."""
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


strip_code_fences = structured_output.strip_code_fences
_extract_json_object = structured_output.extract_json_object


_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503})


def supports_temperature(model_name: str) -> bool:
	"""True when the AI Model record says the model accepts temperature and top_p."""
	return bool(model_name and frappe.db.get_value("AI Model", model_name, "support_temperature"))


class DirectApiExecutor(Executor):
	"""Single-call HTTP executor supporting OpenAI-compatible and Anthropic APIs."""

	_DEFAULT_ENDPOINTS = {
		"OpenAI": "https://api.openai.com/v1",
		"Anthropic": "https://api.anthropic.com",
		"Google": "https://generativelanguage.googleapis.com/v1beta",
	}

	_ANTHROPIC_API_VERSION = "2023-06-01"

	def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
		if not frappe.db.exists("AI Provider", config.provider_name):
			return ExecutorResult(
				error_code=ErrorCode.PROVIDER_NOT_FOUND,
				error_message=f"AI Provider '{config.provider_name}' not found.",
			)

		provider_type = self._DIALECTS.get((config.provider_name or "").strip().lower())
		if not provider_type:
			return ExecutorResult(
				error_code=ErrorCode.PROVIDER_NOT_FOUND,
				error_message=(
					f"AI Provider '{config.provider_name}' is not the name of a "
					f"dialect this executor can speak. Name the record for what "
					f"it speaks - Anthropic, OpenAI or Google."
				),
			)

		model_name = config.model or frappe.db.get_value(
			"AI Model", {"provider": config.provider_name, "enable_model": 1}, "name"
		)
		if not model_name:
			return ExecutorResult(
				error_code=ErrorCode.MODEL_NOT_CONFIGURED,
				error_message=_("No model is configured for provider {0}.").format(config.provider_name),
			)

		model_row = frappe.db.get_value(
			"AI Model", model_name, ["enable_model", "api_endpoint"], as_dict=True
		)

		if model_row and not model_row.enable_model:
			return ExecutorResult(
				error_code=ErrorCode.PROVIDER_DISABLED,
				error_message=_("AI Model '{0}' is disabled.").format(model_name),
			)

		try:
			api_key = (
				frappe.utils.password.get_decrypted_password(
					"AI Model", model_name, "api_key", raise_exception=False
				)
				or ""
			)
		except Exception:
			api_key = ""

		if not api_key:
			return ExecutorResult(
				error_code=ErrorCode.PROVIDER_DISABLED,
				error_message=_(
					"AI Model '{0}' has no API key set. Open that record and enter the {1} API key."
				).format(model_name, provider_type),
			)

		endpoint = ((model_row.api_endpoint if model_row else "") or "").rstrip("/")
		if not endpoint:
			endpoint = self._DEFAULT_ENDPOINTS.get(provider_type, "")

		model = frappe.db.get_value("AI Model", model_name, "model_api_name") or model_name

		schema = None
		native = False
		if config.response_format == "json" and config.response_schema:
			try:
				schema = structured_output.normalize_response_schema(config.response_schema)
			except ValueError as exc:
				return ExecutorResult(
					error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
					error_message=f"Response schema is not valid: {exc}",
				)
			native = bool(frappe.db.get_value("AI Model", model_name, "support_structured_output")) and not (
				config.tools and provider_type == "Google"
			)
			config = dataclasses.replace(
				config,
				system_prompt=structured_output.system_prompt_with_format(
					config.system_prompt, schema, native
				),
			)
		native_schema = structured_output.provider_schema(schema) if native else None

		if config.tools:
			return self._run_with_tools(config, provider_type, api_key, model, schema, native_schema)

		if provider_type == "Anthropic":
			url, payload, headers = self._build_anthropic_request(
				endpoint,
				api_key,
				model,
				config,
			)
			parse_fn = self._parse_anthropic_response
		else:
			url, payload, headers = self._build_openai_request(
				endpoint,
				api_key,
				model,
				config,
				provider_type,
			)
			parse_fn = self._parse_openai_response
		if native_schema and provider_type == "Anthropic":
			payload["output_config"] = structured_output.anthropic_output_config(native_schema)
		elif native_schema:
			payload["response_format"] = structured_output.openai_response_format(native_schema)

		import requests

		attempts = []
		last_error_result = None
		attempt = 0
		corrected = False

		while True:
			attempt_start = time.time()
			error_result = None
			content = None
			token_usage = None
			data = None

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
						return ExecutorResult(
							error_code=ErrorCode.FAILED_MODEL_CALL,
							error_message=str(exc),
							attempts=list(attempts),
						)

			if error_result is None:
				try:
					data = resp.json()
				except Exception:
					error_result = ExecutorResult(
						error_code=ErrorCode.FAILED_MODEL_CALL,
						error_message="Provider returned non-JSON response.",
					)

			if error_result is None:
				content, token_usage, parse_error = parse_fn(data)
				if parse_error:
					error_result = parse_error

			if error_result is None and config.response_format == "json":
				try:
					parsed = structured_output.read_json_reply(
						content, schema, self._stop_reason(provider_type, data)
					)
				except structured_output.ReplyRejected as exc:
					if exc.retry and not corrected:
						corrected = True
						attempts.append(
							AttemptRecord(
								attempt_index=attempt,
								content=content or "",
								error_code=ErrorCode.SCHEMA_VALIDATION_FAILED.value,
								error_message=str(exc),
								token_usage=token_usage,
								latency_ms=int((time.time() - attempt_start) * 1000),
							)
						)
						payload = self._with_correction(payload, content, str(exc))
						continue
					return ExecutorResult(
						error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
						error_message=f"The reply is not the declared JSON: {exc}",
						token_usage=token_usage,
						raw=data,
						attempts=list(attempts),
					)
				return ExecutorResult(
					output=parsed,
					token_usage=token_usage,
					error_code=ErrorCode.SUCCESS,
					raw=data,
					attempts=list(attempts),
				)

			if error_result is None:
				return ExecutorResult(
					output=content,
					token_usage=token_usage,
					error_code=ErrorCode.SUCCESS,
					raw=data,
					attempts=list(attempts),
				)

			latency_ms = int((time.time() - attempt_start) * 1000)
			attempts.append(
				AttemptRecord(
					attempt_index=attempt,
					content=content or "",
					error_code=error_result.error_code.value,
					error_message=error_result.error_message,
					token_usage=token_usage,
					latency_ms=latency_ms,
				)
			)
			last_error_result = error_result

			if attempt >= config.max_retries:
				break
			self._sleep_backoff(config, attempt)
			attempt += 1

		last_error_result.attempts = list(attempts)
		return last_error_result

	_DIALECTS: ClassVar[dict] = {
		"openai": "OpenAI",
		"anthropic": "Anthropic",
		"claude": "Anthropic",
		"google": "Google",
		"gemini": "Google",
	}

	_ADAPTER_PROVIDERS: ClassVar[dict] = {
		"OpenAI": "openai",
		"Anthropic": "anthropic",
		"Google": "gemini",
	}

	def _run_with_tools(
		self,
		config: ExecutorConfig,
		provider_type: str,
		api_key: str,
		model: str,
		schema: dict | None = None,
		native_schema: dict | None = None,
	) -> ExecutorResult:
		"""Tool-enabled execution path."""
		from dataclasses import asdict

		from one_bpmn.processa_engine.agent_runtime.step_loop import run_agent_loop
		from one_bpmn.processa_engine.agent_runtime.llm_factory import get_llm_adapter

		adapter_key = self._ADAPTER_PROVIDERS.get(provider_type)
		if not adapter_key:
			return ExecutorResult(
				error_code=ErrorCode.PROVIDER_NOT_FOUND,
				error_message=(
					f"Provider type '{provider_type}' has no model adapter - "
					"tool-calling is only available for OpenAI, Anthropic and Google providers."
				),
			)

		try:
			adapter = get_llm_adapter(
				adapter_key, model, api_key, timeout_seconds=config.timeout_seconds, max_retries=0
			)
			completion, suspension = run_coro_blocking(
				run_agent_loop(
					adapter,
					system=config.system_prompt,
					user=config.user_prompt,
					tools=config.tools,
					max_tokens=config.max_tokens,
					max_turns=config.max_tool_calls or 10,
					budget_notes=bool(config.max_tool_calls),
					resume=config.resume_state,
					timeout_seconds=config.timeout_seconds,
					max_retries=config.max_retries,
					retry_backoff_ms=config.retry_backoff_ms,
					tool_result_max_chars=config.tool_result_max_chars,
					terminal_tools=config.terminal_tools,
					tool_choice=config.tool_choice,
					parallel_tool_calls=config.parallel_tool_calls,
					thinking_budget_tokens=config.thinking_budget_tokens,
					history=config.messages,
					loop_compaction={
						"threshold": config.loop_compaction_threshold,
						"keep_turns": config.loop_compaction_keep_turns,
						"model": config.compaction_model or None,
						"agent_model": config.model,
						"provider": config.provider_name,
					}
					if config.loop_compaction_threshold
					else None,
					response_schema=native_schema,
					check_reply=self._json_reply_check(schema) if config.response_format == "json" else None,
					budget_check=self._budget_check(config),
					**(
						{"temperature": config.temperature, "top_p": config.top_p}
						if supports_temperature(config.model)
						else {}
					),
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

		if completion.budget_exceeded:
			last_tool = next(
				(call["name"] for turn in reversed(trace) for call in reversed(turn.get("tool_calls") or [])),
				"none",
			)
			return ExecutorResult(
				no_terminal_tool=True,
				error_code=ErrorCode.BUDGET_EXCEEDED,
				error_message=f"{completion.budget_exceeded}. Last tool called: {last_tool}.",
				token_usage=token_usage,
				trace=trace,
			)

		if completion.repeated_tool_error:
			return ExecutorResult(
				no_terminal_tool=True,
				error_code=ErrorCode.REPEATED_TOOL_ERROR,
				error_message=completion.repeated_tool_error,
				token_usage=token_usage,
				trace=trace,
			)

		if completion.hit_turn_cap:
			return ExecutorResult(
				hit_turn_cap=True,
				no_terminal_tool=True,
				error_code=ErrorCode.TURN_CAP_REACHED,
				error_message=(
					f"Tool-calling loop hit the adapter's turn cap without a final answer "
					f"({len(trace)} turns recorded)."
				),
				token_usage=token_usage,
				trace=trace,
				attempts=[
					AttemptRecord(
						attempt_index=0,
						error_code=ErrorCode.TURN_CAP_REACHED.value,
						error_message="turn cap exhausted",
					)
				],
			)

		if config.response_format == "json":
			validation_result = self._validate_json(completion.text, schema)
			if isinstance(validation_result, ExecutorResult):
				validation_result.token_usage = token_usage
				validation_result.trace = trace
				said = (completion.text or "").strip()
				executed = [call.get("name") for turn in trace for call in (turn.get("tool_calls") or [])]
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
				no_terminal_tool=completion.no_terminal_tool,
			)

		return ExecutorResult(
			output=completion.text,
			token_usage=token_usage,
			trace=trace,
			no_terminal_tool=completion.no_terminal_tool,
		)

	@staticmethod
	def _build_openai_request(
		endpoint: str,
		api_key: str,
		model: str,
		config: ExecutorConfig,
		provider_type: str = "OpenAI",
	) -> tuple:
		"""Build URL, payload, and headers for OpenAI-compatible APIs."""
		url = f"{endpoint}/chat/completions"
		messages = []
		if config.system_prompt:
			messages.append({"role": "system", "content": config.system_prompt})
		if config.messages:
			messages.extend(config.messages)
		messages.append({"role": "user", "content": config.user_prompt})

		payload = {
			"model": model,
			"messages": messages,
		}

		if provider_type == "OpenAI":
			payload["max_completion_tokens"] = config.max_tokens
			if supports_temperature(config.model):
				payload["temperature"] = config.temperature
				payload["top_p"] = config.top_p
		else:
			payload["max_tokens"] = config.max_tokens
			payload["temperature"] = config.temperature
			payload["top_p"] = config.top_p

		headers = {
			"Authorization": f"Bearer {api_key}",
			"Content-Type": "application/json",
		}
		return url, payload, headers

	def _build_anthropic_request(
		self,
		endpoint: str,
		api_key: str,
		model: str,
		config: ExecutorConfig,
	) -> tuple:
		"""Build URL, payload, and headers for Anthropic Messages API."""
		url = f"{endpoint}/v1/messages"

		messages = list(config.messages) if config.messages else []
		messages.append({"role": "user", "content": config.user_prompt})

		if messages and config.messages:
			idx = len(config.messages) - 1
			last = dict(messages[idx])  # copy - never mutate the caller's dicts
			content = last.get("content")
			if isinstance(content, str):
				last["content"] = [
					{
						"type": "text",
						"text": content,
						"cache_control": {"type": "ephemeral"},
					}
				]
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
			payload["system"] = [
				{
					"type": "text",
					"text": config.system_prompt,
					"cache_control": {"type": "ephemeral"},
				}
			]

		if supports_temperature(config.model):
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

	def _parse_openai_response(self, data: dict):
		"""Parse an OpenAI-compatible response. Returns (content, token_usage, error_or_None)."""
		choices = data.get("choices") or []
		if not choices:
			return (
				None,
				None,
				ExecutorResult(
					error_code=ErrorCode.FAILED_MODEL_CALL,
					error_message="Provider returned no choices.",
					raw=data,
				),
			)
		content = (choices[0].get("message") or {}).get("content", "")
		token_usage = self._parse_token_usage(data.get("usage") or {})
		return content, token_usage, None

	def _parse_anthropic_response(self, data: dict):
		"""Parse an Anthropic Messages API response. Returns (content, token_usage, error_or_None)."""
		content_blocks = data.get("content") or []
		if not content_blocks:
			return (
				None,
				None,
				ExecutorResult(
					error_code=ErrorCode.FAILED_MODEL_CALL,
					error_message="Anthropic returned no content blocks.",
					raw=data,
				),
			)
		text_parts = [block.get("text", "") for block in content_blocks if block.get("type") == "text"]
		content = "".join(text_parts)
		token_usage = self._parse_token_usage(data.get("usage") or {})
		return content, token_usage, None

	@staticmethod
	def _sleep_backoff(config: ExecutorConfig, attempt: int) -> None:
		base_s = (config.retry_backoff_ms / 1000.0) * (2**attempt)
		jitter = random.uniform(0, 0.1)
		time.sleep(base_s + jitter)

	@staticmethod
	def _parse_token_usage(usage_raw: dict) -> TokenUsage:
		"""Normalise a raw provider usage dict into a TokenUsage."""
		prompt = usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0
		anthropic_read = usage_raw.get("cache_read_input_tokens") or 0
		cache_write = usage_raw.get("cache_creation_input_tokens") or 0
		if anthropic_read or cache_write:
			prompt += anthropic_read + cache_write
			cache_read = anthropic_read
		else:
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
	def _validate_json(content: str, schema: dict | None) -> Any:
		try:
			return structured_output.read_json_reply(content, schema)
		except structured_output.ReplyRejected as exc:
			return ExecutorResult(
				error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
				error_message=f"The reply is not the declared JSON: {exc}.",
			)

	@staticmethod
	def _json_reply_check(schema: dict | None):
		"""For the tool loop: the correction to send when a final reply is not the declared JSON."""

		def check(text: str) -> str | None:
			try:
				structured_output.read_json_reply(text, schema)
			except structured_output.ReplyRejected as exc:
				return structured_output.retry_note(str(exc)) if exc.retry else None
			return None

		return check

	@staticmethod
	def _budget_check(config: ExecutorConfig):
		"""For the tool loop: why the run has spent its token or cost budget, or "" while it has not."""
		if not (config.run_token_budget or config.run_cost_budget):
			return None
		from one_bpmn.agents.pricing import compute_token_cost

		def check(trace: list) -> str:
			prompt = sum(t.prompt_tokens for t in trace)
			completion = sum(t.completion_tokens for t in trace)
			tokens = prompt + completion
			if config.run_token_budget and tokens > config.run_token_budget:
				return (
					f"The run passed its token budget of {config.run_token_budget:,} with {tokens:,} tokens"
				)
			if config.run_cost_budget:
				cost = compute_token_cost(
					config.model,
					prompt_tokens=prompt,
					completion_tokens=completion,
					cache_read_tokens=sum(t.cache_read_tokens for t in trace),
					cache_write_tokens=sum(t.cache_write_tokens for t in trace),
				)["total_cost"]
				if cost > config.run_cost_budget:
					return f"The run passed its cost budget of ${config.run_cost_budget:.2f} at ${cost:.2f}"
			return ""

		return check

	@staticmethod
	def _stop_reason(provider_type: str, data: dict) -> str | None:
		if provider_type == "Anthropic":
			return data.get("stop_reason")
		choices = data.get("choices") or [{}]
		return choices[0].get("finish_reason")

	@staticmethod
	def _with_correction(payload: dict, reply: str, error: str) -> dict:
		"""The same request with the rejected reply and the reason it failed appended."""
		messages = [
			*payload["messages"],
			{"role": "assistant", "content": reply or ""},
			{"role": "user", "content": structured_output.retry_note(error)},
		]
		return {**payload, "messages": messages}


register_executor("direct_api", DirectApiExecutor)
