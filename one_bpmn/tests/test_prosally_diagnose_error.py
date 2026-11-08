# Copyright (c) 2026, one-fm and contributors
"""ProsAlly diagnoses a pasted error or lint finding and proposes a fix or a fallback."""

import json
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_registry.definitions.prosally import tools_review
from one_bpmn.one_bpmn.patches.v1_0 import prosally_diagnoses_errors as patch
from one_bpmn.one_bpmn.patches.v1_0 import prosally_draws_none_tasks as none_tasks
from one_bpmn.one_bpmn.patches.v1_0.prosally_relayouts_and_compares import AGENT_ID
from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import with_edits

CLASSIFY_SCRIPT = (
	"from one_bpmn.agents.prosally_helpers import asks_to_make_call_activity, compare_output, relayout_output, other\n"
	'    if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | frozenset({"IRRELEVANT", "RELAYOUT", "COMPARE"})):\n'
	'if confirmed == "RELAYOUT":\n'
	'    if intent == "COMPARE":\n'
)
SCRIPT_TASK_XML = (
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
	' xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
	'<bpmn:process id="p1"><bpmn:scriptTask id="Activity_9" name="Fetch employee"'
	' spiffworkflow:serverScript="Fetch Employee Script"/></bpmn:process></bpmn:definitions>'
)
ENGINE_ERROR = 'BPMN ScriptTask: "Fetch Employee Script" execution failed\nNameError: name employee_id is not defined'

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
		with mock_patch.object(tools_review, "complete_sub_prompt", return_value=reply), mock_patch.object(tools_review, "prosally_config", return_value={}
		):
			return tools_review.diagnose_output(XML, [ERROR], LINT)

	def test_inputs_carry_only_the_elements_the_error_names(self):
		inputs = tools_review.diagnose_inputs(XML, ERROR, LINT)
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
		self.assertEqual(out["response"], tools_review.diagnose_fallback_reply())

	def test_unlisted_origin_gives_the_fallback(self):
		out = self._output(_diagnosis("somewhere"))
		self.assertEqual(out["response"], tools_review.diagnose_fallback_reply())

	def test_a_failed_model_call_gives_the_fallback(self):
		with mock_patch.object(tools_review, "complete_sub_prompt", side_effect=RuntimeError("down")), mock_patch.object(tools_review, "prosally_config", return_value={}
		):
			out = tools_review.diagnose_output(XML, [ERROR], LINT)
		self.assertEqual(out["response"], tools_review.diagnose_fallback_reply())

	def test_script_error_finds_the_task_and_script_source(self):
		with mock_patch.object(frappe.db, "exists", return_value=True), mock_patch.object(
			frappe, "has_permission", return_value=True
		), mock_patch.object(frappe.db, "get_value", return_value="doc = frappe.get_doc(employee_id)"):
			task = tools_review.script_task_for_error(SCRIPT_TASK_XML, ENGINE_ERROR)
		self.assertEqual((task["id"], task["name"]), ("Activity_9", "Fetch employee"))
		self.assertIn("get_doc", task["script"])

	def test_script_source_is_left_out_when_the_user_cannot_read_it(self):
		with mock_patch.object(frappe.db, "exists", return_value=True), mock_patch.object(
			frappe, "has_permission", return_value=False
		):
			task = tools_review.script_task_for_error(SCRIPT_TASK_XML, ENGINE_ERROR)
		self.assertEqual(task["script"], "")

	def test_script_origin_reply_names_the_task_on_the_map(self):
		with mock_patch.object(frappe.db, "exists", return_value=False):
			with mock_patch.object(tools_review, "complete_sub_prompt", return_value=_diagnosis("server_script")), mock_patch.object(tools_review, "prosally_config", return_value={}
			):
				out = tools_review.diagnose_output(SCRIPT_TASK_XML, [ENGINE_ERROR], [])
		self.assertIn("Fetch employee", out["response"])
		self.assertIn("Logix", out["response"])

	def test_an_error_that_names_a_step_by_name_finds_it(self):
		inputs = tools_review.diagnose_inputs(XML, "The step Review failed to start", [])
		self.assertEqual(len(inputs["elements"]), 1)
		self.assertIn("Task_1", inputs["elements"][0])

	def test_the_diagnose_edits_apply_whichever_classifier_patch_ran_first(self):
		def mine(text):
			return patch.apply_edits(text, patch.SCRIPT_EDITS)

		def theirs(text):
			return with_edits(text, none_tasks.CLASSIFY_EDITS)

		for first, second in ((mine, theirs), (theirs, mine)):
			edited = second(first(CLASSIFY_SCRIPT))
			self.assertIsNotNone(edited)
			self.assertIn("diagnose_output", edited)
			self.assertIn("none_tasks_output", edited)

	def test_patch_teaches_the_classifier_and_adds_the_diagnoser(self):
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if not name:
			self.skipTest("ProsAlly is not on this site")
		patch.execute()
		prompts = {row.sub_agent_id: row.prompt_text for row in frappe.get_doc("AI Agent Configuration", name).sub_prompts}
		self.assertIn(patch.PROMPT_MARKER, prompts["intent_classifier"])
		self.assertIn("server_script", prompts[patch.SUB_AGENT_ID])
