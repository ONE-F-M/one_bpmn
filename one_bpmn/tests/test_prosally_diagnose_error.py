# Copyright (c) 2026, one-fm and contributors
"""ProsAlly diagnoses a pasted error or lint finding and proposes a fix or a fallback."""

import json
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.one_bpmn.patches.v1_0 import prosally_diagnoses_errors as patch
from one_bpmn.one_bpmn.patches.v1_0.prosally_relayouts_and_compares import AGENT_ID

XML = (
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
	'<bpmn:process id="p1"><bpmn:exclusiveGateway id="Gateway_1" name="Approved?"/>'
	'<bpmn:userTask id="Task_1" name="Review"/></bpmn:process></bpmn:definitions>'
)
ERROR = "Expression evaluation error at Gateway_1: name 'amount' is not defined"
LINT = [
	{"id": "Gateway_1", "rule": "frappe/gateway-condition", "message": "No condition", "category": "error"},
	{"id": "Task_1", "rule": "frappe/user-task-missing-assignee", "message": "No assignee", "category": "warn"},
]


def _diagnosis(origin):
	return json.dumps({"origin": origin, "root_cause": "The condition uses an unset value.", "fix_steps": ["Set it"]})


class TestProsAllyDiagnoseError(FrappeTestCase):
	def _output(self, reply):
		with mock_patch.object(helpers, "complete_sub_prompt", return_value=reply), mock_patch.object(
			helpers, "prosally_config", return_value={}
		):
			return helpers.diagnose_output(XML, [ERROR], LINT)

	def test_inputs_carry_only_the_elements_the_error_names(self):
		inputs = helpers.diagnose_inputs(XML, ERROR, LINT)
		self.assertEqual(len(inputs["elements"]), 1)
		self.assertIn("Gateway_1", inputs["elements"][0])
		self.assertEqual([f["id"] for f in inputs["lint_findings"]], ["Gateway_1"])

	def test_map_cause_offers_to_apply_the_fix(self):
		out = self._output(_diagnosis("map"))
		self.assertEqual(out["intent"], "CONFIRM")
		self.assertEqual(out["action_intent"], "MODIFY_EXISTING")
		self.assertIn("Set it", out["response"])

	def test_script_cause_points_to_logix_and_changes_nothing(self):
		out = self._output(_diagnosis("server_script"))
		self.assertEqual(out["intent"], "CLARIFY")
		self.assertNotIn("action_intent", out)
		self.assertIn("Logix", out["response"])

	def test_unparseable_reply_gives_the_fallback(self):
		out = self._output("not json at all")
		self.assertEqual(out["response"], helpers.diagnose_fallback_reply())

	def test_unlisted_origin_gives_the_fallback(self):
		out = self._output(_diagnosis("somewhere"))
		self.assertEqual(out["response"], helpers.diagnose_fallback_reply())

	def test_a_failed_model_call_gives_the_fallback(self):
		with mock_patch.object(helpers, "complete_sub_prompt", side_effect=RuntimeError("down")), mock_patch.object(
			helpers, "prosally_config", return_value={}
		):
			out = helpers.diagnose_output(XML, [ERROR], LINT)
		self.assertEqual(out["response"], helpers.diagnose_fallback_reply())

	def test_patch_teaches_the_classifier_and_adds_the_diagnoser(self):
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if not name:
			self.skipTest("ProsAlly is not on this site")
		patch.execute()
		prompts = {row.sub_agent_id: row.prompt_text for row in frappe.get_doc("AI Agent Configuration", name).sub_prompts}
		self.assertIn(patch.PROMPT_MARKER, prompts["intent_classifier"])
		self.assertIn("server_script", prompts[patch.SUB_AGENT_ID])
