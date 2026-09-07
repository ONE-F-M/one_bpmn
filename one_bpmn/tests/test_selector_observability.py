# Copyright (c) 2026, one-fm and contributors
# WI-001358 (4-01): AI Agent Tool Call child table and Run/Step
# instrumentation for ai_task_selector.

from __future__ import annotations

from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ExecutorConfig
from one_bpmn.agents.observability import (
	finalize_selector_run,
	get_or_create_selector_run,
	record_ai_step,
	record_selector_turns,
)

test_ignore = ["BPMN Process Instance", "BPMN Process Model"]

_instances = {}


def _instance(name="INST-OBS-1"):
	"""A real (minimal) BPMN Process Instance — AI Agent Run links to it."""
	if name not in _instances:
		doc = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"obs-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		_instances[name] = doc
	return _instances[name]


def _config():
	return ExecutorConfig(provider_name="Obs Test Provider", model="obs-model")


TRACE = [
	{
		"role": "tool",
		"content": "",
		"tool_calls": [
			{"name": "task_b", "arguments": {"note": "go"}, "result": "Task 'task_b' will be activated."},
			{"name": "lookup_tool", "arguments": {"q": "x"}, "result": '{"found": true}'},
		],
		"prompt_tokens": 100,
		"completion_tokens": 20,
	},
	{
		"role": "assistant",
		"content": "I selected task_b and looked up x.",
		"tool_calls": [],
		"prompt_tokens": 150,
		"completion_tokens": 30,
		"latency_ms": 2340,
	},
]

SOURCE_MAP = {"task_b": "diagram_task", "lookup_tool": "registry_tool"}


class TestSelectorObservability(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("AI Provider", "Obs Test Provider"):
			frappe.get_doc(
				{
					"doctype": "AI Provider",
					"provider": "Obs Test Provider",
					"provider_type": "OpenAI",
					"api_key": "test-key-not-real",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		_instances.clear()

	# ── Scenario 1: schema — Tool Call child table + Step tool_calls field ──

	def test_schema_migrated(self):
		self.assertTrue(frappe.db.exists("DocType", "AI Agent Tool Call"))
		meta = frappe.get_meta("AI Agent Tool Call")
		self.assertTrue(meta.istable)
		fieldnames = {f.fieldname for f in meta.fields}
		self.assertTrue(
			{"tool_name", "tool_source", "tool_args", "tool_result", "status"} <= fieldnames
		)
		step_meta = frappe.get_meta("AI Agent Step")
		tool_calls_field = step_meta.get_field("tool_calls")
		self.assertIsNotNone(tool_calls_field)
		self.assertEqual(tool_calls_field.options, "AI Agent Tool Call")

	# ── Scenario 2: one Run per subprocess instance, element_type=subprocess ──

	def test_creates_subprocess_run(self):
		run = get_or_create_selector_run(_instance(), "AdhocSub_1", _config())
		self.assertFalse(getattr(run, "stub", False))
		self.assertEqual(run.element_type, "subprocess")
		self.assertEqual(run.status, "Running")

	# ── Scenario 3: later decision points reuse the same Run ──

	def test_reuses_open_run_across_decisions(self):
		instance = _instance("INST-OBS-REUSE")
		first = get_or_create_selector_run(instance, "AdhocSub_1", _config())
		second = get_or_create_selector_run(instance, "AdhocSub_1", _config())
		self.assertEqual(first.name, second.name)

	def test_different_subprocess_gets_its_own_run(self):
		instance = _instance("INST-OBS-TWO")
		first = get_or_create_selector_run(instance, "AdhocSub_1", _config())
		other = get_or_create_selector_run(instance, "AdhocSub_2", _config())
		self.assertNotEqual(first.name, other.name)

	# ── Scenarios 4/5: one Step per turn; tool rows grouped under the turn ──

	def test_records_turns_with_grouped_tool_calls(self):
		run = get_or_create_selector_run(_instance("INST-OBS-TURNS"), "AdhocSub_1", _config())
		recorded = record_selector_turns(run, TRACE, SOURCE_MAP)
		self.assertEqual(recorded, 2)

		steps = frappe.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			fields=["name", "role", "content", "prompt_tokens", "completion_tokens", "step_index"],
			order_by="step_index asc",
		)
		self.assertEqual([s.role for s in steps], ["tool", "assistant"])
		self.assertEqual(steps[0].prompt_tokens, 100)
		self.assertEqual(steps[1].completion_tokens, 30)

		calls = frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": steps[0].name},
			fields=["tool_name", "tool_source", "tool_result", "status"],
			order_by="idx asc",
		)
		self.assertEqual(len(calls), 2)
		self.assertEqual(calls[0].tool_name, "task_b")
		self.assertEqual(calls[0].tool_source, "diagram_task")
		self.assertEqual(calls[1].tool_source, "registry_tool")
		self.assertTrue(all(c.status == "Success" for c in calls))

		# Final-answer Step has no Tool Call rows (Scenario 5).
		final_calls = frappe.get_all("AI Agent Tool Call", filters={"parent": steps[1].name})
		self.assertEqual(final_calls, [])

	def test_failed_tool_call_marked_error(self):
		run = get_or_create_selector_run(_instance("INST-OBS-ERR"), "AdhocSub_1", _config())
		trace = [
			{
				"role": "tool",
				"content": "",
				"tool_calls": [{"name": "ghost", "arguments": {}, "result": "Unknown tool: ghost"}],
				"prompt_tokens": 10,
				"completion_tokens": 2,
			}
		]
		record_selector_turns(run, trace, {})
		step = frappe.get_all("AI Agent Step", filters={"run": run.name}, pluck="name")[0]
		call = frappe.get_all(
			"AI Agent Tool Call", filters={"parent": step}, fields=["status"]
		)[0]
		self.assertEqual(call.status, "Error")

	def test_step_indices_continue_across_decisions(self):
		run = get_or_create_selector_run(_instance("INST-OBS-IDX"), "AdhocSub_1", _config())
		record_selector_turns(run, TRACE, SOURCE_MAP)
		record_selector_turns(run, TRACE, SOURCE_MAP)
		indices = frappe.get_all(
			"AI Agent Step", filters={"run": run.name}, pluck="step_index", order_by="step_index asc"
		)
		self.assertEqual(indices, [1, 2, 3, 4])

	# ── Scenario 6: finalized exactly once, final_output = last assistant ──

	def test_finalize_sets_rollups_and_final_output(self):
		run = get_or_create_selector_run(_instance("INST-OBS-FIN"), "AdhocSub_1", _config())
		record_selector_turns(run, TRACE, SOURCE_MAP)
		finalize_selector_run(run)

		saved = frappe.get_doc("AI Agent Run", run.name)
		self.assertEqual(saved.status, "Success")
		self.assertIsNotNone(saved.ended_at)
		self.assertEqual(saved.final_output, "I selected task_b and looked up x.")
		self.assertEqual(saved.total_tokens, 100 + 20 + 150 + 30)

	def test_finalize_is_idempotent(self):
		run = get_or_create_selector_run(_instance("INST-OBS-ONCE"), "AdhocSub_1", _config())
		record_selector_turns(run, TRACE, SOURCE_MAP)
		finalize_selector_run(run)
		first_ended = frappe.db.get_value("AI Agent Run", run.name, "ended_at")

		run.status = "Success"  # reflect the finalized state
		finalize_selector_run(run)  # second call must be a no-op
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "ended_at"), first_ended
		)

	# ── Scenario 7: instrumentation failures never block dispatch ──

	def test_stub_run_swallows_everything(self):
		stub = SimpleNamespace(stub=True, status="Running")
		self.assertEqual(record_selector_turns(stub, TRACE, SOURCE_MAP), 0)
		finalize_selector_run(stub)  # must not raise
		self.assertIsNone(record_ai_step(stub, 0, "assistant", "x"))


class TestSelectorRunRollups(FrappeTestCase):
	"""record_selector_turns must keep the Run's token/cost/duration rollups
	live while the subprocess is still Running — previously they stayed at
	zero until finalize, so the instance page showed no usage data."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("AI Provider", "Obs Test Provider"):
			frappe.get_doc(
				{
					"doctype": "AI Provider",
					"provider": "Obs Test Provider",
					"provider_type": "OpenAI",
					"api_key": "test-key-not-real",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def test_rollups_update_after_each_decision(self):
		run = get_or_create_selector_run(_instance("INST-OBS-ROLLUP"), "AdhocSub_1", _config())
		record_selector_turns(run, TRACE, SOURCE_MAP)

		run.reload()
		self.assertEqual(run.status, "Running")  # not finalized yet
		self.assertEqual(run.total_prompt_tokens, 250)
		self.assertEqual(run.total_completion_tokens, 50)
		self.assertEqual(run.total_tokens, 300)

		# A second decision accumulates on top
		record_selector_turns(run, TRACE, SOURCE_MAP)
		run.reload()
		self.assertEqual(run.total_tokens, 600)


class TestTurnLatency(FrappeTestCase):
	"""Per-turn decision latency (adapter API round-trip + inline tool
	execution) flows from the executor trace onto AI Agent Step.latency_ms."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("AI Provider", "Obs Test Provider"):
			frappe.get_doc(
				{
					"doctype": "AI Provider",
					"provider": "Obs Test Provider",
					"provider_type": "OpenAI",
					"api_key": "test-key-not-real",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def test_trace_latency_recorded_on_steps(self):
		run = get_or_create_selector_run(_instance("INST-OBS-LAT"), "AdhocSub_1", _config())
		record_selector_turns(run, TRACE, SOURCE_MAP)

		steps = frappe.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			fields=["role", "latency_ms"],
			order_by="step_index asc",
		)
		by_role = {s.role: s.latency_ms for s in steps}
		# tool turn in TRACE has no latency_ms → defaults to 0
		self.assertEqual(by_role["tool"], 0)
		self.assertEqual(by_role["assistant"], 2340)

	def test_turnrecord_serializes_latency(self):
		from dataclasses import asdict

		from one_bpmn.agents.llm_provider.base import TurnRecord

		turn = asdict(TurnRecord(role="assistant", content="x", latency_ms=875))
		self.assertEqual(turn["latency_ms"], 875)


class TestActivationOutcome(FrappeTestCase):
	"""record_activation_outcome attaches the real-world result to the
	diagram-task tool call that activated it, without touching tool_result
	(the transcript of what the model was told)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("AI Provider", "Obs Test Provider"):
			frappe.get_doc(
				{
					"doctype": "AI Provider",
					"provider": "Obs Test Provider",
					"provider_type": "OpenAI",
					"api_key": "test-key-not-real",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def _tool_call_row(self, run, tool_name):
		return frappe.db.sql(
			"""
			select tc.name, tc.tool_result, tc.outcome
			from `tabAI Agent Tool Call` tc
			join `tabAI Agent Step` s on tc.parent = s.name
			where s.run = %s and tc.tool_name = %s
			""",
			(run.name, tool_name),
			as_dict=True,
		)

	def test_outcome_lands_on_diagram_task_call(self):
		from one_bpmn.agents.observability import record_activation_outcome

		instance = _instance("INST-OBS-OUTCOME")
		run = get_or_create_selector_run(instance, "AdhocSub_1", _config())
		record_selector_turns(run, TRACE, SOURCE_MAP)

		updated = record_activation_outcome(
			instance.name, "task_b", 'Completed 13:22:40 — set HD Ticket.status = "X"'
		)
		self.assertTrue(updated)

		rows = self._tool_call_row(run, "task_b")
		self.assertEqual(len(rows), 1)
		self.assertIn("set HD Ticket.status", rows[0].outcome)
		# transcript untouched
		self.assertIn("will be activated", rows[0].tool_result)

	def test_registry_tools_and_unknown_tasks_are_noops(self):
		from one_bpmn.agents.observability import record_activation_outcome

		instance = _instance("INST-OBS-OUTCOME2")
		run = get_or_create_selector_run(instance, "AdhocSub_1", _config())
		record_selector_turns(run, TRACE, SOURCE_MAP)

		# lookup_tool is a registry tool — its result is already real
		self.assertFalse(record_activation_outcome(instance.name, "lookup_tool", "x"))
		self.assertFalse(record_activation_outcome(instance.name, "no_such_task", "x"))
		self.assertFalse(record_activation_outcome(instance.name, "task_b", ""))
