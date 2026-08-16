# Copyright (c) 2026, one-fm and contributors
# WI-001360 (4-03): Insights dashboard support for ad-hoc/selector runs.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.insights_api import (
	get_agent_overview,
	get_run_steps,
	get_run_totals_crosscheck,
)

test_ignore = ["BPMN Process Instance", "BPMN Process Model"]


def _tool_call_available():
	return frappe.db.exists("DocType", "AI Agent Tool Call")


class TestInsightsSelectorSupport(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"ins-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		instance.flags.ignore_mandatory = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)

		cls.ai_run = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": instance.name,
				"bpmn_id": "AdhocSub_1",
				"element_type": "subprocess",
				"backend": "direct_api",
				"model": "ins-model",
				"status": "Success",
				"started_at": frappe.utils.now_datetime(),
				"total_tokens": 180,
				"estimated_cost": 0.0,
			}
		)
		cls.ai_run.insert(ignore_permissions=True)

		for index, payload in enumerate(
			[
				{"role": "tool", "prompt_tokens": 100, "completion_tokens": 20},
				{"role": "assistant", "prompt_tokens": 50, "completion_tokens": 10, "content": "done"},
			]
		):
			step = frappe.get_doc(
				{
					"doctype": "AI Agent Step",
					"run": cls.ai_run.name,
					"step_index": index,
					"cost": 0,
					**payload,
				}
			)
			if index == 0 and _tool_call_available():
				step.append(
					"tool_calls",
					{
						"tool_name": "task_b",
						"tool_source": "diagram_task",
						"tool_result": "activated",
						"status": "Success",
					},
				)
			step.insert(ignore_permissions=True)

	# ── Scenario 1: subprocess runs included, Steps never counted as runs ──

	def test_overview_counts_subprocess_run_once(self):
		overview = get_agent_overview(days=1)
		self.assertGreaterEqual(overview["runs_today"], 1)
		# Steps contribute tokens through the Run rollup, not as extra runs:
		# the overview token total must include this run's rolled-up figure.
		self.assertGreaterEqual(overview["total_tokens"], 180)

	# ── Scenario 2: Run → Steps → expandable Tool Call rows ──

	def test_run_steps_include_tool_calls(self):
		if not _tool_call_available():
			self.skipTest("AI Agent Tool Call doctype not on this branch")
		steps = get_run_steps(self.ai_run.name)
		self.assertEqual(len(steps), 2)
		self.assertEqual(steps[0]["role"], "tool")
		self.assertEqual(len(steps[0]["tool_calls"]), 1)
		self.assertEqual(steps[0]["tool_calls"][0]["tool_name"], "task_b")
		self.assertEqual(steps[0]["tool_calls"][0]["tool_source"], "diagram_task")
		self.assertEqual(steps[1]["tool_calls"], [])

	# ── Scenario 4: totals cross-checked against Step sums ──

	def test_totals_crosscheck_matches(self):
		result = get_run_totals_crosscheck(self.ai_run.name)
		self.assertEqual(result["step_total_tokens"], 180)
		self.assertTrue(result["tokens_match"])
		self.assertTrue(result["cost_match"])

	def test_totals_crosscheck_detects_drift(self):
		self.ai_run.db_set("total_tokens", 999)
		result = get_run_totals_crosscheck(self.ai_run.name)
		self.assertFalse(result["tokens_match"])
		self.ai_run.db_set("total_tokens", 180)
