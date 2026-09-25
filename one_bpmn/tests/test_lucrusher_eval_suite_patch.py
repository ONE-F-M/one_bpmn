# Copyright (c) 2026, one-fm and contributors

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_lucrusher_eval_suite as seed


class TestLucrusherEvalSuitePatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("AI Agent Configuration", {"agent_id": seed.AGENT_ID}):
			return
		model = frappe.get_doc(
			{"doctype": "BPMN Process Model", "title": "zz-lucrusher-stub-map", "process_id": "zz_lucrusher_stub", "version": 1}
		)
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": "ZZ LuCrusher Stub",
				"agent_id": seed.AGENT_ID,
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"process_model": model.name,
			}
		).insert(ignore_permissions=True)

	def _cases(self):
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE})
		return {c.title: frappe.get_doc("AI Eval Case", c.name) for c in frappe.get_all("AI Eval Case", {"suite": suite}, ["name", "title"])}

	def test_seeding_twice_leaves_one_suite_and_six_cases(self):
		seed.execute()
		seed.execute()
		self.assertEqual(frappe.db.count("AI Eval Suite", {"title": seed.SUITE_TITLE}), 1)
		self.assertEqual(len(self._cases()), 6)

	def test_every_case_checks_the_finalize_intent(self):
		seed.execute()
		for title, case in self._cases().items():
			finalize = [row for row in case.expected_tool_calls if row.tool_name == "finalize"]
			self.assertEqual(len(finalize), 1, title)
			self.assertEqual(finalize[0].argument, "intent", title)
			self.assertIn("tool_calls", [a.assertion_type for a in case.assertions], title)

	def test_the_follow_up_cases_start_from_earlier_turns(self):
		seed.execute()
		cases = self._cases()
		for title in (
			"The same Lucidchart link again uses the fetched copy",
			"A codebase scan after the document is fetched",
			"Confirming the proposed topology",
		):
			context = json.loads(cases[title].input_context)
			types = [m["message_type"] for m in context["conversation_messages"]]
			self.assertEqual(types, ["User", "Bot", "Tool"], title)
			self.assertIn(f"lucid_doc:{seed.LUCID_DOC_ID}", context["session_state"], title)

	def test_the_suite_does_not_block_deploys_before_its_first_run(self):
		seed.execute()
		suite = frappe.get_doc("AI Eval Suite", {"title": seed.SUITE_TITLE})
		self.assertEqual(suite.gate_deployment, 0)
		self.assertEqual((suite.pass_k, suite.min_pass_rate), (seed.PASS_K, seed.MIN_PASS_RATE))

	def test_a_site_without_lucrusher_is_left_alone(self):
		frappe.db.delete("AI Eval Suite", {"title": seed.SUITE_TITLE})
		with patch.object(seed, "AGENT_ID", "zz_no_such_agent"):
			seed.execute()
		self.assertFalse(frappe.db.exists("AI Eval Suite", {"title": seed.SUITE_TITLE}))
