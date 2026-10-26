# Copyright (c) 2026, one-fm and contributors
"""Docu's baseline suite gains the list view script cases once, and its probe list script passes the safety gate."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_docu_list_script_cases as seed
from one_bpmn.security.client_script_validator import validate_list_view_script


class TestSeedDocuListScriptCases(FrappeTestCase):
	def setUp(self):
		self.agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
		model = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not self.agent or not model:
			self.skipTest("Docu or a process model is not on this site")
		frappe.db.set_value("AI Agent Configuration", self.agent, "process_model", model)

	def _suite(self):
		return frappe.db.get_value("AI Eval Suite", {"agent_configuration": self.agent, "suite_type": "Baseline"}, "name")

	def _case(self, title):
		return frappe.db.get_value("AI Eval Case", {"suite": self._suite(), "title": title}, "name")

	def test_the_cases_are_added_to_the_suite_once(self):
		seed.execute()
		seed.execute()

		titles = frappe.get_all("AI Eval Case", filters={"suite": self._suite()}, pluck="title")
		for spec in seed.CASES:
			self.assertEqual(titles.count(spec["title"]), 1, spec["title"])

	def test_the_draft_case_expects_the_list_script_stage(self):
		seed.execute()
		tools = frappe.get_all(
			"AI Eval Expected Tool Call",
			filters={"parent": self._case(seed.CASES[0]["title"])},
			pluck="tool_name",
			order_by="call_order asc",
		)
		self.assertEqual(tools, ["classify_intent", "write_list_script"])

	def test_the_field_property_case_forbids_the_list_script_stage(self):
		seed.execute()
		case = frappe.get_doc("AI Eval Case", self._case(seed.CASES[-1]["title"]))
		forbidden = [a.value for a in case.assertions if a.assertion_type == "no_tool_call"]
		self.assertEqual(forbidden, ["write_list_script"])

	def test_the_probe_gets_one_list_script_that_passes_the_gate(self):
		seed.execute()
		seed.execute()

		scripts = frappe.get_all("Client Script", filters={"dt": seed.PROBE, "view": "List"}, fields=["script"])
		self.assertEqual(len(scripts), 1)
		self.assertEqual(validate_list_view_script(seed.PROBE, scripts[0].script), [])
