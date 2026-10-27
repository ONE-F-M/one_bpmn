# Copyright (c) 2026, one-fm and contributors
"""Docu's baseline suite gains the help text and child table cases once, and the child table probe exists."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_docu_help_text_and_child_table_cases as seed


class TestSeedDocuHelpTextAndChildTableCases(FrappeTestCase):
	def setUp(self):
		self.agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
		model = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not self.agent or not model:
			self.skipTest("Docu or a process model is not on this site")
		frappe.db.set_value("AI Agent Configuration", self.agent, "process_model", model)

	def _suite(self):
		return frappe.db.get_value("AI Eval Suite", {"agent_configuration": self.agent, "suite_type": "Baseline"}, "name")

	def test_the_cases_are_added_to_the_suite_once(self):
		seed.execute()
		seed.execute()

		titles = frappe.get_all("AI Eval Case", filters={"suite": self._suite()}, pluck="title")
		for spec in seed.CASES:
			self.assertEqual(titles.count(spec["title"]), 1, spec["title"])

	def test_the_child_table_case_runs_on_a_probe_whose_table_has_the_old_columns(self):
		seed.execute()

		table = frappe.get_meta(seed.TABLE_PROBE).get_field("items")
		self.assertEqual(table.options, seed.TABLE_PROBE_CHILD)
		self.assertEqual({f.fieldname for f in frappe.get_meta(seed.TABLE_PROBE_CHILD).fields}, {"part", "qty"})

	def test_both_cases_expect_the_design_trace(self):
		seed.execute()

		for spec in seed.CASES:
			case = frappe.db.get_value("AI Eval Case", {"suite": self._suite(), "title": spec["title"]}, "name")
			tools = frappe.get_all(
				"AI Eval Expected Tool Call", filters={"parent": case}, pluck="tool_name", order_by="call_order asc"
			)
			self.assertEqual(tools, ["classify_intent", "write_schema", "review_schema", "finalize"])
