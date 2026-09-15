"""Every case in the worked example must have something to run against."""
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_runner import _execute_memory_case
from one_bpmn.one_bpmn.patches.v1_0 import (
	case_type_example_gets_its_fixtures as heal,
	seed_connector_case_type_suite as seed,
)


def _cases():
	suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE}, "name")
	return frappe.get_all(
		"AI Eval Case", filters={"suite": suite}, fields=["name", "case_type", "input_context"]
	) if suite else []


class TestCaseTypeExampleFixtures(FrappeTestCase):

	def setUp(self):
		if not frappe.db.get_value("AI Agent Configuration", {"agent_name": seed.AGENT}, "name"):
			self.skipTest("the Connector Agent is not on this site")
		heal.execute()

	def test_every_case_names_what_it_runs_against(self):
		"""Seven cases were seeded before the fixtures existed; none may be empty."""
		cases = _cases()
		self.assertEqual(len(cases), 7)
		for case in cases:
			with self.subTest(case["case_type"]):
				ctx = json.loads(case["input_context"] or "{}")
				self.assertTrue(ctx, "case has no input context")
				named = ctx.get("context_docname") or ctx.get("scope_key")
				self.assertTrue(named, "input context names neither a document nor a memory scope")

	def test_the_memory_case_is_scored_by_the_memory_pipeline(self):
		"""It carries a memory spec, not a work order — and it passes."""
		memory = next(c for c in _cases() if c["case_type"] == "Memory")
		ctx = json.loads(memory["input_context"])
		self.assertEqual(ctx["scope"], "Agent")
		self.assertEqual(ctx["query"], "", "a generation case must not also search the store")

		report = _execute_memory_case(frappe.get_doc("AI Eval Case", memory["name"]))
		self.assertEqual(report["status"], "Passed", report.get("actual_output"))
		self.assertEqual(json.loads(report["actual_output"])["measured"], ["generation"])

	def test_healing_twice_changes_nothing(self):
		before = {c["name"]: c["input_context"] for c in _cases()}
		heal.execute()
		self.assertEqual({c["name"]: c["input_context"] for c in _cases()}, before)
