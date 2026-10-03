# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""An agent's examples carry the tool calls to copy, and a run can become one."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import _EXAMPLE_FIELDS, _clean_example_rows, _rows_for_shape
from one_bpmn.agents.context_assembler import _render_examples
from one_bpmn.agents.eval_case_factory import EXAMPLE_RESULT_CHARS, create_example_from_run
from one_bpmn.tests.test_eval_case_factory import _agent_configuration, _run

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]

THREE_CALLS = [
	{"tool": "classify_intent", "args": {}, "result": '{"intent": "CREATE"}'},
	{"tool": "list_doctypes", "args": {"search": "Leave", "limit": 5}, "result": "Leave Application"},
	{"tool": "write_schema", "args": {"doctype": "Leave Request"}, "result": ""},
]


class TestExamplesShowTheirCalls(FrappeTestCase):
	def test_three_calls_render_in_order_with_their_arguments(self):
		text = _render_examples(
			[
				{
					"input": "I need a leave form",
					"context_summary": "No DocType is open.",
					"trajectory": json.dumps(THREE_CALLS),
					"expected_output": "Here is a Leave Request form.",
					"enabled": 1,
				}
			]
		)
		self.assertIn(
			"Input:\nI need a leave form\nContext: No DocType is open.\nTool calls:\n"
			'-> classify_intent({}) => {"intent": "CREATE"}\n'
			'-> list_doctypes({"limit": 5, "search": "Leave"}) => Leave Application\n'
			'-> write_schema({"doctype": "Leave Request"})\n'
			"Expected output:\nHere is a Leave Request form.",
			text,
		)

	def test_argument_order_does_not_change_the_prompt(self):
		reordered = [dict(THREE_CALLS[1], args={"limit": 5, "search": "Leave"})]
		original = [dict(THREE_CALLS[1], args={"search": "Leave", "limit": 5})]
		self.assertEqual(
			_render_examples([{"input": "x", "trajectory": reordered}]),
			_render_examples([{"input": "x", "trajectory": original}]),
		)

	def test_an_example_without_calls_renders_as_before(self):
		self.assertEqual(
			_render_examples(
				[{"input": "How many on shift?", "expected_output": "14.", "note": "Number only."}]
			),
			"## Examples\n\n### Example 1\nInput:\nHow many on shift?\nExpected output:\n14.\nNote: Number only.",
		)


class TestTheEditorKeepsTheCalls(FrappeTestCase):
	def test_a_save_from_the_editor_keeps_context_and_trajectory(self):
		rows = _clean_example_rows(
			[{"input": "hi", "context_summary": "Form open.", "trajectory": THREE_CALLS, "enabled": 0}]
		)
		self.assertEqual(rows[0]["context_summary"], "Form open.")
		self.assertEqual(json.loads(rows[0]["trajectory"]), THREE_CALLS)

	def test_an_unedited_round_trip_compares_equal(self):
		doc = frappe.get_doc("AI Agent Configuration", _agent_configuration())
		doc.append("examples", {"input": "hi", "trajectory": json.dumps(THREE_CALLS, indent=2), "enabled": 1})
		shape = _rows_for_shape(doc, "examples", _EXAMPLE_FIELDS)
		self.assertEqual(_clean_example_rows(shape), shape)

	def test_an_example_with_no_calls_stores_none(self):
		self.assertIsNone(_clean_example_rows([{"input": "hi", "trajectory": []}])[0]["trajectory"])


class TestCreateExampleFromRun(FrappeTestCase):
	def _run_with_calls(self, status="Success"):
		run = _run(status=status, final_output="Here is the form.")
		frappe.db.set_value("AI Agent Run", run.name, "agent_configuration", _agent_configuration())
		for index, calls in ((3, THREE_CALLS[:2]), (4, [dict(THREE_CALLS[2], result="r" * 400)])):
			step = frappe.get_doc(
				{"doctype": "AI Agent Step", "run": run.name, "step_index": index, "role": "tool", "cost": 0}
			)
			for call in calls:
				step.append(
					"tool_calls",
					{
						"tool_name": call["tool"],
						"tool_args": json.dumps(call["args"]),
						"tool_result": call["result"],
						"status": "Success",
					},
				)
			step.insert(ignore_permissions=True)
		return frappe.get_doc("AI Agent Run", run.name)

	def test_a_successful_run_becomes_a_disabled_example_with_its_calls(self):
		run = self._run_with_calls()
		out = create_example_from_run(run.name)
		example = frappe.get_doc("AI Agent Example", out["example"])
		self.assertEqual(out["configuration"], run.agent_configuration)
		self.assertEqual(example.enabled, 0)
		self.assertEqual(example.input, "usr prompt")
		self.assertEqual(example.expected_output, "Here is the form.")
		calls = json.loads(example.trajectory)
		self.assertEqual([c["tool"] for c in calls], ["classify_intent", "list_doctypes", "write_schema"])
		self.assertEqual(calls[1]["args"], {"search": "Leave", "limit": 5})
		self.assertEqual(calls[2]["result"], "r" * EXAMPLE_RESULT_CHARS + "...")

	def test_a_failed_run_is_refused(self):
		run = self._run_with_calls(status="Error")
		self.assertRaises(frappe.ValidationError, create_example_from_run, run.name)

	def test_a_user_who_cannot_read_the_run_is_refused(self):
		run = self._run_with_calls()
		with self.set_user("Guest"):
			self.assertRaises(frappe.PermissionError, create_example_from_run, run.name)
