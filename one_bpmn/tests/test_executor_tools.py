# Copyright (c) 2026, one-fm and contributors
# WI-001356 (3-03): bridge agents/executor to agents/llm_provider tool-calling.

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorContext
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.agents.llm_provider.base import (
	CompletionResult,
	ToolCallRecord,
	ToolSpec,
	TurnRecord,
)


def _provider(name, provider_type):
	if not frappe.db.exists("AI Provider", name):
		frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": name,
				"provider_type": provider_type,
				"api_key": "test-key-not-real",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	return name


def _tool(fn=None):
	return ToolSpec(
		fn=fn or (lambda **kw: "ok"),
		name="echo_tool",
		description="Echoes.",
		parameters={"text": {"type": "string", "description": "Text"}},
		required=["text"],
	)


class _FakeAdapter:
	def __init__(self, completion):
		self._completion = completion
		self.calls = []

	async def complete(self, system, user, tools=None, max_tokens=16384):
		self.calls.append({"system": system, "user": user, "tools": tools, "max_tokens": max_tokens})
		return self._completion


class TestExecutorToolBridge(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.openai_provider = _provider("Bridge OpenAI Provider", "OpenAI")
		cls.unsupported_provider = _provider("Bridge Bedrock Provider", "Bedrock")

	def _run(self, provider, tools, completion=None):
		config = ExecutorConfig(
			provider_name=provider,
			model="test-model",
			system_prompt="sys",
			user_prompt="usr",
			tools=tools,
		)
		fake = _FakeAdapter(completion or CompletionResult(text="done", trace=[]))
		with patch(
			"one_bpmn.agents.llm_provider.factory.get_llm_adapter", return_value=fake
		) as factory:
			result = DirectApiExecutor().run(config, ExecutorContext())
		return result, fake, factory

	# ── Scenario 2: tools present → delegate to the matching adapter ──

	def test_delegates_to_adapter_with_tools(self):
		tools = [_tool()]
		result, fake, factory = self._run(self.openai_provider, tools)
		factory.assert_called_once()
		self.assertEqual(factory.call_args[0][0], "openai")
		self.assertIs(fake.calls[0]["tools"], tools)
		self.assertEqual(result.error_code, ErrorCode.SUCCESS)
		self.assertEqual(result.output, "done")

	# ── Scenario 4: ExecutorResult populated from the trace ──

	def test_result_maps_output_usage_and_trace(self):
		completion = CompletionResult(
			text="final answer",
			trace=[
				TurnRecord(
					role="tool",
					content="",
					tool_calls=[ToolCallRecord(name="echo_tool", arguments={"text": "a"}, result="ok")],
					prompt_tokens=100,
					completion_tokens=20,
				),
				TurnRecord(role="assistant", content="final answer", prompt_tokens=150, completion_tokens=30),
			],
		)
		result, _, _ = self._run(self.openai_provider, [_tool()], completion)
		self.assertEqual(result.output, "final answer")
		self.assertEqual(result.token_usage.prompt_tokens, 250)
		self.assertEqual(result.token_usage.completion_tokens, 50)
		self.assertEqual(result.token_usage.total_tokens, 300)
		self.assertEqual(len(result.trace), 2)
		self.assertEqual(result.trace[0]["role"], "tool")
		self.assertEqual(result.trace[0]["tool_calls"][0]["name"], "echo_tool")
		json.dumps(result.trace)  # trace must be JSON-safe for observability

	# ── Scenario 5: turn cap → FAILED_MODEL_CALL naming the cause, trace kept ──

	def test_turn_cap_returns_failed_model_call_with_trace(self):
		completion = CompletionResult(
			text="",
			trace=[TurnRecord(role="tool", prompt_tokens=10, completion_tokens=5)],
			hit_turn_cap=True,
		)
		result, _, _ = self._run(self.openai_provider, [_tool()], completion)
		self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
		self.assertIn("turn cap", result.error_message)
		self.assertEqual(len(result.trace), 1)

	# ── Scenario 6: no adapter for provider type → explicit error ──

	def test_unsupported_provider_type_errors(self):
		result, _, factory = self._run(self.unsupported_provider, [_tool()])
		self.assertEqual(result.error_code, ErrorCode.PROVIDER_NOT_FOUND)
		self.assertIn("no agents/llm_provider adapter", result.error_message)
		factory.assert_not_called()

	# ── Scenario 1: tools=None default keeps the raw HTTP path ──

	def test_tools_default_is_none(self):
		self.assertIsNone(ExecutorConfig().tools)

	def test_no_tools_never_touches_adapter_factory(self):
		config = ExecutorConfig(provider_name="No Such Provider 404")
		with patch("one_bpmn.agents.llm_provider.factory.get_llm_adapter") as factory:
			result = DirectApiExecutor().run(config, ExecutorContext())
		factory.assert_not_called()
		self.assertEqual(result.error_code, ErrorCode.PROVIDER_NOT_FOUND)

	# ── Review fix: safe when the calling thread already has an event loop ──

	def test_run_with_tools_inside_running_event_loop(self):
		async def call_from_async_context():
			# asyncio.run() would raise RuntimeError here; the executor must
			# fall back to a dedicated thread instead of crashing.
			result, _, _ = self._run(self.openai_provider, [_tool()])
			return result

		result = asyncio.run(call_from_async_context())
		self.assertEqual(result.error_code, ErrorCode.SUCCESS)
		self.assertEqual(result.output, "done")


class TestOpenAIAdapterTrace(FrappeTestCase):
	"""Drive the real OpenAIAdapter loop against a stubbed SDK client."""

	def _adapter(self, responses):
		try:
			from one_bpmn.agents.llm_provider.openai_adapter import OpenAIAdapter
		except ImportError:
			self.skipTest("openai SDK not installed")
		adapter = OpenAIAdapter.__new__(OpenAIAdapter)
		adapter._model = "test-model"
		queue = list(responses)

		async def create(**kwargs):
			return queue.pop(0)

		adapter._client = SimpleNamespace(
			chat=SimpleNamespace(completions=SimpleNamespace(create=create))
		)
		return adapter

	@staticmethod
	def _tool_call_response(name, arguments, prompt=100, completion=10):
		tc = SimpleNamespace(
			id="call_1",
			function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
		)
		message = SimpleNamespace(content=None, tool_calls=[tc])
		return SimpleNamespace(
			choices=[SimpleNamespace(finish_reason="tool_calls", message=message)],
			usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
		)

	@staticmethod
	def _final_response(text, prompt=120, completion=15):
		message = SimpleNamespace(content=text, tool_calls=None)
		return SimpleNamespace(
			choices=[SimpleNamespace(finish_reason="stop", message=message)],
			usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
		)

	# ── Scenario 3: per-turn records with grouped tool calls + real usage ──

	def test_trace_records_each_turn_with_tool_calls_and_usage(self):
		seen = []

		def tool_fn(**kwargs):
			seen.append(kwargs)
			return "tool says hi"

		adapter = self._adapter(
			[
				self._tool_call_response("echo_tool", {"text": "ping"}),
				self._final_response("all done"),
			]
		)
		completion = asyncio.run(
			adapter.complete(system="s", user="u", tools=[_tool(tool_fn)])
		)

		self.assertEqual(completion.text, "all done")
		self.assertFalse(completion.hit_turn_cap)
		self.assertEqual(seen, [{"text": "ping"}])

		self.assertEqual(len(completion.trace), 2)
		tool_turn, final_turn = completion.trace
		self.assertEqual(tool_turn.role, "tool")
		self.assertEqual(len(tool_turn.tool_calls), 1)
		self.assertEqual(tool_turn.tool_calls[0].name, "echo_tool")
		self.assertEqual(tool_turn.tool_calls[0].arguments, {"text": "ping"})
		self.assertEqual(tool_turn.tool_calls[0].result, "tool says hi")
		self.assertEqual(tool_turn.prompt_tokens, 100)
		self.assertEqual(tool_turn.completion_tokens, 10)
		self.assertEqual(final_turn.role, "assistant")
		self.assertEqual(final_turn.content, "all done")
		self.assertEqual(final_turn.prompt_tokens, 120)

	def test_turn_cap_sets_flag_and_keeps_partial_trace(self):
		responses = [
			self._tool_call_response("echo_tool", {"text": str(i)}) for i in range(10)
		]
		adapter = self._adapter(responses)
		completion = asyncio.run(adapter.complete(system="s", user="u", tools=[_tool()]))
		self.assertTrue(completion.hit_turn_cap)
		self.assertEqual(completion.text, "")
		self.assertEqual(len(completion.trace), 10)

	def test_no_tools_single_assistant_turn(self):
		adapter = self._adapter([self._final_response("plain answer")])
		completion = asyncio.run(adapter.complete(system="s", user="u"))
		self.assertEqual(completion.text, "plain answer")
		self.assertEqual(len(completion.trace), 1)
		self.assertEqual(completion.trace[0].role, "assistant")
