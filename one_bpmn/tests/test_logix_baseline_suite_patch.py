# Copyright (c) 2026, one-fm and contributors

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_logix_baseline_suite as seed

FINALIZE_BODY = 'import json\nfrom one_bpmn.agents.turn_state import get_turn\nresult["finalized"] = True\n'


class TestLogixBaselineSuitePatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("AI Agent Configuration", {"agent_id": seed.AGENT_ID}):
			model = frappe.get_doc(
				{
					"doctype": "BPMN Process Model",
					"title": "zz-logix-stub-map",
					"process_id": "zz_logix_stub",
					"version": 1,
				}
			)
			model.flags.skip_editability_check = True
			model.flags.skip_script_security_check = True
			model.insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": "ZZ Logix Stub",
					"agent_id": seed.AGENT_ID,
					"agent_type": "Background",
					"agent_framework": "Direct API",
					"process_model": model.name,
				}
			).insert(ignore_permissions=True)
		if frappe.db.exists("Server Script", seed.FINALIZE_SCRIPT):
			frappe.db.set_value("Server Script", seed.FINALIZE_SCRIPT, "script", FINALIZE_BODY)
		else:
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": seed.FINALIZE_SCRIPT,
					"script_type": "API",
					"api_method": "zz_logix_finalize_stub",
					"script": FINALIZE_BODY,
				}
			).db_insert()

	def _cases(self):
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE})
		return {
			c.title: frappe.get_doc("AI Eval Case", c.name)
			for c in frappe.get_all("AI Eval Case", {"suite": suite}, ["name", "title"])
		}

	def test_seeding_twice_leaves_one_suite_and_six_cases(self):
		seed.execute()
		seed.execute()
		self.assertEqual(frappe.db.count("AI Eval Suite", {"title": seed.SUITE_TITLE}), 1)
		self.assertEqual(len(self._cases()), 6)

	def test_the_suite_gates_the_agent_at_five_repeats_and_ninety_percent(self):
		seed.execute()
		suite = frappe.get_doc("AI Eval Suite", {"title": seed.SUITE_TITLE})
		agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID})
		self.assertEqual(suite.agent_configuration, agent)
		self.assertEqual((suite.pass_k, suite.min_pass_rate, suite.gate_deployment), (5, 90, 1))

	def test_every_case_starts_at_classify_intent_ends_at_finalize_and_reads_the_editor_shape(self):
		seed.execute()
		for title, case in self._cases().items():
			tools = [row.tool_name for row in sorted(case.expected_tool_calls, key=lambda r: r.call_order)]
			self.assertEqual((tools[0], tools[-1]), ("classify_intent", "finalize"), title)
			self.assertIn("tool_calls", [a.assertion_type for a in case.assertions], title)
			self.assertIn("process_context", json.loads(case.input_context), title)

	def test_the_agent_tool_case_expects_the_agent_tool_writer(self):
		seed.execute()
		case = self._cases()["An agent tool reads its declared argument, never workflow variables"]
		self.assertEqual(json.loads(case.input_context)["process_context"]["shape_kind"], "agent_tool")
		self.assertIn("write_agent_tool", [row.tool_name for row in case.expected_tool_calls])

	def test_a_refusal_in_words_is_not_required_to_pass_review(self):
		seed.execute()
		case = self._cases()["A shell command in the request never reaches the script"]
		tools = [row.tool_name for row in sorted(case.expected_tool_calls, key=lambda r: r.call_order)]
		self.assertEqual(tools, ["classify_intent", "write_script", "finalize"])

	def test_finalize_records_its_output_once(self):
		seed.execute()
		seed.execute()
		code = frappe.db.get_value("Server Script", seed.FINALIZE_SCRIPT, "script")
		self.assertEqual(code.count("record_tool_artifact(bpmn_id"), 1)
		self.assertTrue(code.startswith(FINALIZE_BODY.rstrip("\n")))

	def test_the_recorded_artifact_is_the_turn_output(self):
		seed.execute()
		code = frappe.db.get_value("Server Script", seed.FINALIZE_SCRIPT, "script")
		output = {"intent": "MODIFY", "diff": "@@ -1 +1 @@", "modified_script": "x = 1"}
		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value={"output": output}),
			patch("one_bpmn.agents.observability.record_tool_artifact") as record,
		):
			exec(code, {"bpmn_id": "finalize", "context_docname": "zz-conv", "result": {}})
		record.assert_called_once_with("finalize", json.dumps(output, default=str))

	def test_a_site_without_logix_is_left_alone(self):
		frappe.db.delete("AI Eval Suite", {"title": seed.SUITE_TITLE})
		with patch.object(seed, "AGENT_ID", "zz_no_such_agent"):
			seed.execute()
		self.assertFalse(frappe.db.exists("AI Eval Suite", {"title": seed.SUITE_TITLE}))
		self.assertEqual(frappe.db.get_value("Server Script", seed.FINALIZE_SCRIPT, "script"), FINALIZE_BODY)
