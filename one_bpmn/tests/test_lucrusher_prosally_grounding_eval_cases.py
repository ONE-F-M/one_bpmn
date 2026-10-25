# Copyright (c) 2026, one-fm and contributors
"""The five grounding cases in LuCrusher Baseline: what each asks and that seeding twice adds no row."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_lucrusher_eval_suite as suite_seed
from one_bpmn.one_bpmn.patches.v1_0 import seed_lucrusher_prosally_grounding_eval_cases as seed


class TestGroundingEvalCases(FrappeTestCase):
	def test_five_cases_each_read_the_code_then_draft(self):
		self.assertEqual(len(seed.CASES), 5)
		self.assertEqual(len({c["title"] for c in seed.CASES}), 5)
		for case in seed.CASES:
			tools = [(c["tool_name"], c["argument"], c["expected_value"]) for c in case["calls"]]
			self.assertEqual(tools[0][0], "read_doctype_logic", case["title"])
			self.assertEqual(tools[1], ("finalize", "intent", "PROSALLY_PROMPT_DRAFT"), case["title"])
			self.assertIn("llm_judge", [a["assertion_type"] for a in case["assertions"]], case["title"])

	def test_the_lanes_case_offers_a_lucidchart_lane_the_workflow_lacks(self):
		case = next(c for c in seed.CASES if c["title"].startswith("Lanes come from"))
		doc = next(iter(case["context"]["session_state"].values()))
		self.assertIn("Event Creator", doc["swimlanes"])

	def test_the_size_case_has_more_processes_than_one_call_may_draft(self):
		case = next(c for c in seed.CASES if c["title"].startswith("Four processes"))
		state = case["context"]["conversation_messages"][2]["metadata"]
		self.assertEqual(state["topology"]["total_processes"], 4)
		self.assertGreater(len(state["migration_tasks"]["processes"]), 2)

	def test_seeding_twice_adds_each_case_once(self):
		frappe.set_user("Administrator")
		suite_seed.execute()
		suite = frappe.db.get_value("AI Eval Suite", {"title": suite_seed.SUITE_TITLE})
		if not suite:
			self.skipTest("LuCrusher is not on this site")
		seed.execute()
		seed.execute()
		for case in seed.CASES:
			rows = frappe.get_all("AI Eval Case", {"suite": suite, "title": case["title"]}, pluck="name")
			self.assertEqual(len(rows), 1, case["title"])
			doc = frappe.get_doc("AI Eval Case", rows[0])
			self.assertEqual(json.loads(doc.input_context), case["context"])
			self.assertEqual(doc.expected_tool_calls[0].tool_name, "read_doctype_logic")
