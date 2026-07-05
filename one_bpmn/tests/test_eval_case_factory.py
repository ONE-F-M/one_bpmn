# Copyright (c) 2026, one-fm and contributors
# WI-001363 (5-03): Create Eval Case from Run action.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_case_factory import create_eval_case_from_run

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]


def _provider():
	name = "Factory Test Provider"
	if not frappe.db.exists("AI Provider", name):
		frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": name,
				"provider_type": "OpenAI",
				"api_key": "x",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	return name


def _instance():
	doc = frappe.get_doc(
		{
			"doctype": "BPMN Process Instance",
			"process_id": f"fac-{frappe.generate_hash(length=6)}",
			"status": "Active",
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.name


def _run(element_type="task", status="Success", final_output="the answer", with_steps=True):
	run = frappe.get_doc(
		{
			"doctype": "AI Agent Run",
			"instance": _instance(),
			"bpmn_id": "Task_1",
			"element_type": element_type,
			"backend": "direct_api",
			"provider": _provider(),
			"model": "m",
			"status": status,
			"started_at": frappe.utils.now_datetime(),
			"final_output": final_output,
		}
	)
	run.insert(ignore_permissions=True)
	if with_steps:
		for idx, (role, content) in enumerate(
			[("system", "sys prompt"), ("user", "usr prompt"), ("assistant", final_output)]
		):
			frappe.get_doc(
				{
					"doctype": "AI Agent Step",
					"run": run.name,
					"step_index": idx,
					"role": role,
					"content": content,
					"cost": 0,
				}
			).insert(ignore_permissions=True)
	return run


class TestEvalCaseFactory(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	# ── Scenario 1: plain task run pre-fills prompts + expected_output ──

	def test_plain_task_run_prefills_case(self):
		run = _run()
		case_name = create_eval_case_from_run(run.name)
		case = frappe.get_doc("AI Eval Case", case_name)
		self.assertEqual(case.source_run, run.name)
		self.assertEqual(case.provider, run.provider)
		self.assertEqual(case.model, "m")
		self.assertEqual(case.input_system_prompt, "sys prompt")
		self.assertEqual(case.input_user_prompt, "usr prompt")
		self.assertEqual(case.expected_output, "the answer")

	def test_error_run_allowed(self):
		run = _run(status="Error")
		case_name = create_eval_case_from_run(run.name)
		self.assertTrue(frappe.db.exists("AI Eval Case", case_name))

	def test_running_run_rejected(self):
		run = _run(status="Running", with_steps=False)
		with self.assertRaises(frappe.ValidationError):
			create_eval_case_from_run(run.name)

	# ── Scenario 2: subprocess run requires a Step choice ──

	def test_subprocess_run_requires_step(self):
		run = _run(element_type="subprocess")
		with self.assertRaises(frappe.ValidationError):
			create_eval_case_from_run(run.name)

	# ── Scenario 3: expected_output pre-filled from the chosen tool call ──

	def test_subprocess_case_from_tool_call(self):
		run = _run(element_type="subprocess", final_output="")
		if not frappe.db.exists("DocType", "AI Agent Tool Call"):
			self.skipTest("AI Agent Tool Call doctype not on this branch")
		step = frappe.get_doc(
			{
				"doctype": "AI Agent Step",
				"run": run.name,
				"step_index": 3,
				"role": "tool",
				"content": "",
				"cost": 0,
			}
		)
		step.append(
			"tool_calls",
			{"tool_name": "lookup", "tool_result": "the tool result", "status": "Success"},
		)
		step.append(
			"tool_calls",
			{"tool_name": "notify", "tool_result": "sent", "status": "Success"},
		)
		step.insert(ignore_permissions=True)

		call = frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": step.name, "tool_name": "lookup"},
			pluck="name",
		)[0]
		case_name = create_eval_case_from_run(run.name, step_name=step.name, tool_call_name=call)
		case = frappe.get_doc("AI Eval Case", case_name)
		self.assertEqual(case.expected_output, "the tool result")

	def test_subprocess_step_with_multiple_calls_requires_pick(self):
		run = _run(element_type="subprocess", final_output="")
		if not frappe.db.exists("DocType", "AI Agent Tool Call"):
			self.skipTest("AI Agent Tool Call doctype not on this branch")
		step = frappe.get_doc(
			{"doctype": "AI Agent Step", "run": run.name, "step_index": 3, "role": "tool", "cost": 0}
		)
		step.append("tool_calls", {"tool_name": "a", "tool_result": "ra", "status": "Success"})
		step.append("tool_calls", {"tool_name": "b", "tool_result": "rb", "status": "Success"})
		step.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			create_eval_case_from_run(run.name, step_name=step.name)  # ambiguous

	# ── Scenario 4: source_run links back ──

	def test_source_run_links_back(self):
		run = _run()
		case_name = create_eval_case_from_run(run.name)
		self.assertEqual(
			frappe.db.get_value("AI Eval Case", case_name, "source_run"), run.name
		)
