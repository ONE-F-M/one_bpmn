# Copyright (c) 2026, one-fm and contributors
"""Docu's baseline suite gains its design cases once, beside the cases it already had."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_docu_baseline_cases as seed


class TestSeedDocuBaselineCases(FrappeTestCase):
	def setUp(self):
		self.agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
		model = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not self.agent or not model:
			self.skipTest("Docu or a process model is not on this site")
		frappe.db.set_value("AI Agent Configuration", self.agent, "process_model", model)
		self.suite = frappe.db.get_value(
			"AI Eval Suite", {"agent_configuration": self.agent, "suite_type": "Baseline"}, "name"
		) or frappe.get_doc(
			{
				"doctype": "AI Eval Suite",
				"title": "_Test Docu baseline",
				"eval_type": "Agent",
				"suite_type": "Baseline",
				"agent_configuration": self.agent,
			}
		).insert(ignore_permissions=True, ignore_links=True).name
		self.greeting = frappe.get_doc(
			{"doctype": "AI Eval Case", "title": "_Test greeting", "suite": self.suite, "input_user_prompt": "hi"}
		).insert(ignore_permissions=True, ignore_links=True).name

	def test_the_cases_are_added_to_the_existing_suite_once(self):
		seed.execute()
		seed.execute()

		suites = frappe.get_all(
			"AI Eval Suite", filters={"agent_configuration": self.agent, "suite_type": "Baseline"}, pluck="name"
		)
		self.assertEqual(suites, [self.suite])
		titles = frappe.get_all("AI Eval Case", filters={"suite": self.suite}, pluck="title")
		for spec in seed.CASES:
			self.assertEqual(titles.count(spec["title"]), 1, spec["title"])
		self.assertTrue(frappe.db.exists("AI Eval Case", self.greeting))

	def test_a_design_case_expects_the_full_design_trace(self):
		seed.execute()
		case = frappe.db.get_value("AI Eval Case", {"suite": self.suite, "title": seed.CASES[0]["title"]}, "name")
		tools = frappe.get_all(
			"AI Eval Expected Tool Call", filters={"parent": case}, pluck="tool_name", order_by="call_order asc"
		)
		self.assertEqual(tools, ["classify_intent", "write_schema", "review_schema", "finalize"])
