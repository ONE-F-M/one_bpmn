# Copyright (c) 2026, one-fm and contributors
# Tests for the dispatcher memory wiring (mocked executor): disabled = no
# change, long-term memory search + injection, auto-write with source_run,
# empty search = no injection, and the executor messages slot.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import (
	ErrorCode,
	Executor,
	ExecutorConfig,
	ExecutorResult,
	TokenUsage,
	register_executor,
)
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D

_CAPTURED = {}


class _FakeExecutor(Executor):
	def run(self, config, context):
		_CAPTURED["config"] = config
		return ExecutorResult(
			output="agent output", token_usage=TokenUsage(1, 2, 3), error_code=ErrorCode.SUCCESS
		)


register_executor("faketest", _FakeExecutor)


def _instance():
	return SimpleNamespace(
		name="INST-X", context_doctype="", context_docname="", process_model="", initiated_by="Administrator"
	)


def _task(bpmn="Act_1"):
	return SimpleNamespace(data={}, task_spec=SimpleNamespace(bpmn_id=bpmn, name=bpmn))


class TestDispatcherMemory(FrappeTestCase):
	def setUp(self):
		_CAPTURED.clear()
		# Isolate the dispatcher from observability DB writes; return a non-stub
		# run so source_run is set. Neutralise the label lookup and the commit
		# the observability block performs (keeps FrappeTestCase rollback intact).
		patches = [
			patch(
				"one_bpmn.agents.observability.create_ai_run",
				return_value=SimpleNamespace(name="RUN-FAKE", stub=False),
			),
			patch("one_bpmn.agents.observability.record_ai_step"),
			patch("one_bpmn.agents.observability.finalize_ai_run"),
			patch("one_bpmn.agents.observability.finalize_ai_run_on_exception"),
			patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="AI Task"),
			patch("frappe.db.commit"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_disabled_no_injection_no_write(self):
		with patch("one_bpmn.agents.memory.tools.memory_search") as ms, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_instance(), _task(), {"aiBackend": "faketest", "aiSystemPrompt": "SYS", "aiUserPrompt": "U"}, "Act_1"
			)
		ms.assert_not_called()
		mw.assert_not_called()
		self.assertEqual(_CAPTURED["config"].system_prompt, "SYS")
		self.assertEqual(_CAPTURED["config"].messages, [])

	def test_long_term_memory_search_and_injection(self):
		with patch(
			"one_bpmn.agents.memory.tools.memory_search", return_value=[{"content": "net-30 rule"}]
		) as ms, patch("one_bpmn.agents.memory.tools.memory_write"):
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_9"),
				{
					"aiBackend": "faketest",
					"aiLongTermMemory": "enabled",
					"aiMemoryScope": "Agent",
					"aiSystemPrompt": "SYS",
					"aiUserPrompt": "handle order",
				},
				"Act_9",
			)
		ms.assert_called_once()
		args, _ = ms.call_args
		self.assertEqual(args[0], "Agent")   # scope
		self.assertEqual(args[1], "Act_9")   # scope key defaults to bpmn_id
		sp = _CAPTURED["config"].system_prompt
		self.assertIn("Relevant memory:", sp)
		self.assertIn("net-30 rule", sp)

	def test_empty_search_no_injection(self):
		with patch("one_bpmn.agents.memory.tools.memory_search", return_value=[]), patch(
			"one_bpmn.agents.memory.tools.memory_write"
		):
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_E"),
				{
					"aiBackend": "faketest",
					"aiLongTermMemory": "1",
					"aiMemoryScope": "Agent",
					"aiSystemPrompt": "SYS",
					"aiUserPrompt": "q",
				},
				"Act_E",
			)
		self.assertEqual(_CAPTURED["config"].system_prompt, "SYS")
		self.assertNotIn("Relevant memory:", _CAPTURED["config"].system_prompt)

	def test_raw_write_mode_stores_output_verbatim(self):
		with patch("one_bpmn.agents.memory.tools.memory_write") as mw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_W"),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "raw",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_W",
			)
		mw.assert_called_once()
		args, kwargs = mw.call_args
		self.assertEqual(args[0], "Agent")
		self.assertEqual(args[1], "Act_W")
		self.assertEqual(args[2], "agent output")          # content = output verbatim
		self.assertEqual(kwargs.get("source_run"), "RUN-FAKE")

	def test_distilled_write_mode_enqueues_distillation(self):
		# distilled is the new default path: the raw output is NOT stored; a
		# distill job is dispatched instead (run inline under tests).
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_D"),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "distilled",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_D",
			)
		mw.assert_not_called()
		dw.assert_called_once()
		kwargs = dw.call_args.kwargs
		self.assertEqual(kwargs["scope"], "Agent")
		self.assertEqual(kwargs["scope_key"], "Act_D")
		self.assertEqual(kwargs["agent_output"], "agent output")
		self.assertEqual(kwargs["source_run"], "RUN-FAKE")
		self.assertEqual(kwargs["backend"], "faketest")

	def test_legacy_autowrite_defaults_to_distilled(self):
		# Back-compat: an existing element with aiMemoryAutoWrite on and no mode
		# now distils rather than dumping the reply verbatim.
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_L"),
				{
					"aiBackend": "faketest",
					"aiMemoryAutoWrite": "enabled",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_L",
			)
		dw.assert_called_once()

	def test_write_mode_off_writes_nothing(self):
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as dw, patch(
			"one_bpmn.agents.memory.tools.memory_write"
		) as mw:
			D.dispatch_ai_agent(
				_instance(),
				_task("Act_O"),
				{
					"aiBackend": "faketest",
					"aiMemoryWriteMode": "off",
					"aiMemoryScope": "Agent",
					"aiUserPrompt": "q",
				},
				"Act_O",
			)
		dw.assert_not_called()
		mw.assert_not_called()


class TestExecutorMessagesSlot(FrappeTestCase):
	def test_openai_empty_is_system_then_user(self):
		_, payload, _ = DirectApiExecutor()._build_openai_request(
			"http://x", "k", "m", ExecutorConfig(system_prompt="S", user_prompt="U"), "Other"
		)
		self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])

	def test_openai_history_precedes_user(self):
		cfg = ExecutorConfig(system_prompt="S", user_prompt="U", messages=[{"role": "assistant", "content": "prior"}])
		_, payload, _ = DirectApiExecutor()._build_openai_request("http://x", "k", "m", cfg, "Other")
		self.assertEqual([m["role"] for m in payload["messages"]], ["system", "assistant", "user"])

	def test_anthropic_history_and_empty(self):
		ex = DirectApiExecutor()
		cfg = ExecutorConfig(system_prompt="S", user_prompt="U", messages=[{"role": "assistant", "content": "prior"}])
		_, payload, _ = ex._build_anthropic_request("http://x", "k", "m", cfg)
		self.assertEqual([m["role"] for m in payload["messages"]], ["assistant", "user"])
		self.assertEqual(payload.get("system"), "S")
		_, empty, _ = ex._build_anthropic_request(
			"http://x", "k", "m", ExecutorConfig(system_prompt="S", user_prompt="U")
		)
		self.assertEqual([m["role"] for m in empty["messages"]], ["user"])
