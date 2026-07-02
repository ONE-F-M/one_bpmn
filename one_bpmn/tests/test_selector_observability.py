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
					"provider_name": "Obs Test Provider",
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
		self.assertEqual(indices, [0, 1, 2, 3])

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
