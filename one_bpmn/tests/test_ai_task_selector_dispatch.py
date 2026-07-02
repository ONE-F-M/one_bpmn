# Copyright (c) 2026, one-fm and contributors
# WI-001352 (2-02): dispatch_ai_task_selector handler.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import ai_task_selector

FIXTURES = Path(__file__).parent / "fixtures"

SELECTOR_CFG = {
	"serviceType": "ai_task_selector",
	"aiProvider": "Selector Provider",
	"aiModel": "test-model",
	"aiSystemPrompt": "You pick tasks.",
	"aiUserPrompt": "Pick the next task for {{ instance.name }}.",
	"aiToolSources": "diagram",
}


def _bridge_available() -> bool:
	"""ExecutorConfig.tools ships on WI-001356; resolve_tool_pool on WI-001353."""
	from one_bpmn.agents.executor import ExecutorConfig

	try:
		import one_bpmn.agents.tool_pool
	except ImportError:
		return False
	try:
		ExecutorConfig(tools=[])
	except TypeError:
		return False
	return True


def _instance(extensions=None):
	return SimpleNamespace(
		name="INST-TEST-1",
		context_doctype=None,
		context_docname=None,
		process_model="Test Model",
		initiated_by="Administrator",
		_service_task_extensions=extensions or {"AdhocSub_1": dict(SELECTOR_CFG)},
	)


def _adhoc_subworkflow():
	xml = (FIXTURES / "adhoc_three_tasks.bpmn").read_text()
	spec_dict, sp_specs = engine.parse_bpmn(xml, "Process_AdhocThree")
	wf = engine.create_workflow(spec_dict, sp_specs, initial_data={"done": False})
	wf.do_engine_steps()
	sp = next(iter(wf.subprocesses.values()))
	heads = [t for t in sp.get_tasks(state=TaskState.READY) if t.task_spec.name.startswith("task_")]
	return sp, heads


class _FakeExecutor:
	"""Stands in for DirectApiExecutor: replays a scripted LLM decision by
	invoking the selector-provided tool fns the way the adapter loop would."""

	scripted_calls: ClassVar[list] = []  # list of (tool_name, kwargs)
	result_factory = None

	def run(self, config, context):
		from dataclasses import asdict

		from one_bpmn.agents.executor import ExecutorResult, TokenUsage
		from one_bpmn.agents.llm_provider.base import ToolCallRecord, TurnRecord

		if _FakeExecutor.result_factory is not None:
			return _FakeExecutor.result_factory(config, context)

		tool_map = {t.name: t for t in (config.tools or [])}
		turn = TurnRecord(role="tool", prompt_tokens=50, completion_tokens=10)
		for name, kwargs in _FakeExecutor.scripted_calls:
			tool = tool_map.get(name)
			result = tool.fn(**kwargs) if tool else f"Unknown tool: {name}"
			turn.tool_calls.append(ToolCallRecord(name=name, arguments=kwargs, result=result))
		return ExecutorResult(
			output="decision made",
			token_usage=TokenUsage(50, 10, 60),
			trace=[asdict(turn), {"role": "assistant", "content": "decision made", "tool_calls": [], "prompt_tokens": 60, "completion_tokens": 5}],
		)


class TestSelectNextAdhocTaskHook(FrappeTestCase):
	"""engine.select_next_adhoc_task — self-contained on this branch."""

	def tearDown(self):
		engine.adhoc_next_task_decider = None
		super().tearDown()

	def test_no_decider_falls_back_to_diagram_order(self):
		pending = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
		self.assertIs(engine.select_next_adhoc_task(None, pending), pending[0])

	def test_decider_choice_wins(self):
		pending = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
		engine.adhoc_next_task_decider = lambda sp, p: p[1]
		self.assertIs(engine.select_next_adhoc_task(None, pending), pending[1])

	def test_decider_none_falls_back_to_diagram_order(self):
		pending = [SimpleNamespace(name="a")]
		engine.adhoc_next_task_decider = lambda sp, p: None
		self.assertIs(engine.select_next_adhoc_task(None, pending), pending[0])

	def test_no_activation_promotes_nothing(self):
		pending = [SimpleNamespace(name="a")]
		engine.adhoc_next_task_decider = lambda sp, p: engine.NO_ACTIVATION
		self.assertIsNone(engine.select_next_adhoc_task(None, pending))

	def test_decider_exception_is_fail_safe(self):
		pending = [SimpleNamespace(name="a")]

		def broken(sp, p):
			raise RuntimeError("kaboom")

		engine.adhoc_next_task_decider = broken
		# Never silently auto-runs a task the selector was meant to choose.
		self.assertIsNone(engine.select_next_adhoc_task(None, pending))


class TestDispatchAiTaskSelector(FrappeTestCase):
	def setUp(self):
		super().setUp()
		if not _bridge_available():
			self.skipTest("WI-001353/WI-001356 modules not on this branch")
		_FakeExecutor.scripted_calls = []
		_FakeExecutor.result_factory = None
		self._patch = patch(
			"one_bpmn.agents.executor.get_executor", return_value=_FakeExecutor
		)
		self._patch.start()

	def tearDown(self):
		self._patch.stop()
		super().tearDown()

	# ── Scenario 1: prompts rendered with the dispatch_ai_agent context ──

	def test_prompts_jinja_rendered(self):
		sp, _ = _adhoc_subworkflow()
		captured = {}

		def factory(config, context):
			from one_bpmn.agents.executor import ExecutorResult, TokenUsage

			captured["user_prompt"] = config.user_prompt
			return ExecutorResult(output="", token_usage=TokenUsage(), trace=[])

		_FakeExecutor.result_factory = factory
		ai_task_selector.dispatch_ai_task_selector(
			_instance(), sp, dict(SELECTOR_CFG), "AdhocSub_1"
		)
		self.assertEqual(captured["user_prompt"], "Pick the next task for INST-TEST-1.")

	# ── Scenario 2: diagram-task selection → activation, args merged ──

	def test_diagram_task_selection_activates_with_arguments(self):
		sp, _ = _adhoc_subworkflow()
		_FakeExecutor.scripted_calls = [("task_b", {"note": "chosen"})]

		action, chosen, args = ai_task_selector.dispatch_ai_task_selector(
			_instance(), sp, dict(SELECTOR_CFG), "AdhocSub_1"
		)
		self.assertEqual(action, "activate")
		self.assertEqual(chosen, "task_b")
		self.assertEqual(args, {"note": "chosen"})

	def test_only_first_selection_wins(self):
		sp, _ = _adhoc_subworkflow()
		_FakeExecutor.scripted_calls = [("task_b", {}), ("task_c", {})]
		action, chosen, _ = ai_task_selector.dispatch_ai_task_selector(
			_instance(), sp, dict(SELECTOR_CFG), "AdhocSub_1"
		)
		self.assertEqual((action, chosen), ("activate", "task_b"))

	# ── Scenario 4: unknown tool → fail-safe, logged, nothing activated ──

	def test_unknown_tool_is_fail_safe(self):
		sp, _ = _adhoc_subworkflow()
		_FakeExecutor.scripted_calls = [("no_such_tool", {})]
		with patch.object(frappe, "log_error") as log_error:
			action, _, _ = ai_task_selector.dispatch_ai_task_selector(
				_instance(), sp, dict(SELECTOR_CFG), "AdhocSub_1"
			)
		self.assertEqual(action, "idle")
		titles = [c.kwargs.get("title", "") for c in log_error.call_args_list]
		self.assertTrue(any("unknown tool" in t for t in titles))

	# ── Scenario 5: executor failure → dispatch_ai_agent error pattern ──

	def test_executor_failure_writes_error_fields(self):
		sp, _ = _adhoc_subworkflow()

		def factory(config, context):
			from one_bpmn.agents.executor import ErrorCode, ExecutorResult

			return ExecutorResult(
				error_code=ErrorCode.FAILED_MODEL_CALL, error_message="boom"
			)

		_FakeExecutor.result_factory = factory
		with patch.object(frappe, "log_error"):
			action, _, _ = ai_task_selector.dispatch_ai_task_selector(
				_instance(), sp, dict(SELECTOR_CFG), "AdhocSub_1"
			)
		self.assertEqual(action, "error")
		self.assertEqual(sp.data["AdhocSub_1_error_code"], "FAILED_MODEL_CALL")
		self.assertEqual(sp.data["AdhocSub_1_error_message"], "boom")

	# ── Decider wiring: choice mapped onto the pending task ──

	def test_decider_maps_choice_to_pending_task(self):
		sp, heads = _adhoc_subworkflow()
		instance = _instance()
		decider = ai_task_selector.make_adhoc_decider(instance, None)

		with patch.object(
			ai_task_selector,
			"dispatch_ai_task_selector",
			return_value=("activate", "task_b", {"x": 1}),
		):
			chosen = decider(sp, heads)
		self.assertEqual(chosen.task_spec.name, "task_b")
		self.assertEqual(chosen.data.get("x"), 1)

	def test_decider_idle_returns_no_activation(self):
		sp, heads = _adhoc_subworkflow()
		decider = ai_task_selector.make_adhoc_decider(_instance(), None)
		with patch.object(
			ai_task_selector, "dispatch_ai_task_selector", return_value=("idle", None, None)
		):
			self.assertIs(decider(sp, heads), engine.NO_ACTIVATION)

	def test_decider_ignores_non_selector_subprocesses(self):
		sp, heads = _adhoc_subworkflow()
		decider = ai_task_selector.make_adhoc_decider(_instance(extensions={}), None)
		self.assertIsNone(decider(sp, heads))
