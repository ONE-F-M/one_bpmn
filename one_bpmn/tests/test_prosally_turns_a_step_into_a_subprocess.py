# Copyright (c) 2026, one-fm and contributors
"""A request for a sub-process on a step that exists is a modify of that step, never a redraw of the process."""

import ast
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_turns_a_step_into_a_subprocess as step_patch

CONVERSATION = "_test_prosally_turns_a_step"
REQUEST = "Create a sub process for Complete Payroll Clearance: Payroll Operator checks pending salary"
DRAW_REPLY = {
	"intent": "OVERWRITE_EXISTING",
	"reason": "r",
	"summary": {"intro": "I'll redraw the process", "steps": [], "settings": []},
	"question": "Shall I go ahead?",
}


class RecordingAdapter:
	def __init__(self, reply):
		self.reply = reply
		self.prompts = []

	async def complete(self, system, user):
		self.prompts.append(user)
		return SimpleNamespace(text=json.dumps(self.reply))


class TestStepClassification(FrappeTestCase):
	def setUp(self):
		step_patch.execute()
		self.script = frappe.db.get_value("Server Script", {"api_method": "prosally_tool_classify_intent"}, "script")
		if not self.script:
			self.skipTest("the ProsAlly Classify Intent script is not on this site")
		ast.parse(self.script)

	def tearDown(self):
		clear_turn(CONVERSATION)

	def _classify(self, user_text, xml):
		set_turn(
			CONVERSATION,
			{"user_text": user_text, "process_name": "Employee Offboarding", "current_xml": xml, "chat_history": []},
		)
		adapter, result = RecordingAdapter(DRAW_REPLY), {}
		with patch("one_bpmn.agents.prosally_helpers.get_llm_adapter_from_settings", return_value=adapter):
			exec(self.script, {"frappe": frappe, "context_docname": CONVERSATION, "result": result})
		return result, adapter

	def test_a_request_for_a_sub_process_on_an_existing_step_is_a_modify(self):
		result, _ = self._classify(REQUEST, step_patch.fixture_xml())
		self.assertEqual(result["intent"], "MODIFY_EXISTING")

	def test_the_classifier_is_told_to_describe_it_as_turning_that_step_into_a_sub_process(self):
		_, adapter = self._classify(REQUEST, step_patch.fixture_xml())
		self.assertIn("turns it into a sub-process", adapter.prompts[0])
		self.assertIn("Complete Payroll Clearance", adapter.prompts[0])

	def test_a_message_that_names_the_step_but_does_not_ask_for_a_sub_process_is_left_to_the_classifier(self):
		result, _ = self._classify("Rename Complete Payroll Clearance to Payroll done", step_patch.fixture_xml())
		self.assertEqual(result["intent"], "OVERWRITE_EXISTING")

	def test_a_call_activity_is_never_the_target(self):
		result, _ = self._classify("Create a sub process for Call Closure: steps", step_patch.fixture_xml())
		self.assertEqual(result["intent"], "OVERWRITE_EXISTING")

	def test_a_misnamed_step_is_not_confirmed_and_the_closest_name_is_offered(self):
		result, adapter = self._classify(REQUEST.replace("Clearance", "Acceptance"), step_patch.fixture_xml())
		self.assertEqual((result["intent"], result["next"]), ("AMBIGUOUS", "finalize"))
		self.assertIn("Complete Payroll Clearance (step)", result["reason"])
		self.assertIn('no step or sub-process called "Complete Payroll Acceptance"', adapter.prompts[0])

	def test_the_reply_lists_what_exists_and_each_option_is_the_request_with_that_name(self):
		self._classify(REQUEST.replace("Clearance", "Acceptance"), step_patch.fixture_xml())
		output = get_turn(CONVERSATION)["output"]
		self.assertEqual(output["intent"], "CLARIFY")
		self.assertIn('"Complete Payroll Acceptance"', output["response"])
		self.assertIn("Complete Payroll Clearance (step)", output["response"])
		self.assertEqual(output["options"], [REQUEST])

	def test_a_name_with_no_close_match_is_a_new_sub_process_to_add_not_a_redraw(self):
		result, adapter = self._classify(
			"Add a sub process for background checks: verify references", step_patch.fixture_xml()
		)
		self.assertEqual(result["intent"], "MODIFY_EXISTING")
		self.assertIn("NEW sub-process", adapter.prompts[0])
		self.assertNotIn("closest are", adapter.prompts[0])

	def test_asking_for_a_new_sub_process_is_never_answered_with_a_did_you_mean(self):
		request = REQUEST.replace("Create a sub process", "Create a new sub process").replace("Clearance", "Acceptance")
		result, adapter = self._classify(request, step_patch.fixture_xml())
		self.assertEqual(result["intent"], "MODIFY_EXISTING")
		self.assertIn("NEW sub-process", adapter.prompts[0])
		self.assertEqual(get_turn(CONVERSATION)["output"]["intent"], "CONFIRM")

	def test_a_request_to_turn_something_into_a_call_activity_gets_a_plain_answer_not_a_confirmation(self):
		result, _ = self._classify("subporcess as call activity next to payroll clearance", step_patch.fixture_xml())
		self.assertEqual((result["intent"], result["next"]), ("AMBIGUOUS", "finalize"))
		output = get_turn(CONVERSATION)["output"]
		self.assertEqual(output["intent"], "CLARIFY")
		self.assertIn("separate process", output["response"])

	def test_adding_a_call_activity_that_calls_a_named_process_is_left_to_the_classifier(self):
		result, _ = self._classify("Add a call activity that calls Offboarding Closure after the end", step_patch.fixture_xml())
		self.assertEqual(result["intent"], "OVERWRITE_EXISTING")

	def test_a_diagram_without_that_step_is_left_to_the_classifier(self):
		result, _ = self._classify(REQUEST, "")
		self.assertEqual(result["intent"], "OVERWRITE_EXISTING")


class TestPatchContent(FrappeTestCase):
	def setUp(self):
		step_patch.execute()

	def _prompt(self, sub_agent_id):
		config = frappe.db.get_value("AI Agent Configuration", {"agent_id": step_patch.AGENT_ID}, "name")
		return frappe.db.get_value("AI Agent Sub Prompt", {"parent": config, "sub_agent_id": sub_agent_id}, "prompt_text")

	def test_the_classifier_prompt_carries_the_sub_process_for_a_step_rule(self):
		text = self._prompt("intent_classifier")
		if text is None:
			self.skipTest("ProsAlly is not on this site")
		self.assertIn("sub-process for one step", text)
		self.assertIn("turning that step into a sub-process", text)

	def test_the_modifier_and_generator_know_call_activities(self):
		for sub_agent_id in ("modifier", "process_generator"):
			text = self._prompt(sub_agent_id)
			if text is None:
				self.skipTest("ProsAlly is not on this site")
			self.assertIn("subProcess | callActivity", text)

	def test_the_schema_skill_describes_children_expanded_and_call_activities(self):
		body = frappe.db.get_value("AI Skill", step_patch.SKILL, "body")
		if body is None:
			self.skipTest("the IR schema skill is not on this site")
		for text in ("`children`", '"expanded": true', "calledElement"):
			self.assertIn(text, body)

	def test_running_it_again_adds_no_second_eval_case(self):
		if not frappe.db.exists("AI Eval Suite", {"title": step_patch.SUITE_TITLE}):
			self.skipTest("the Prosally baseline suite is not on this site")
		titles = [case["title"] for case in step_patch.eval_cases()]
		step_patch.execute()
		step_patch.execute()
		for title in titles:
			self.assertEqual(frappe.db.count("AI Eval Case", {"title": title}), 1)

	def test_the_eval_cases_name_the_step_and_check_the_call_activity(self):
		second = step_patch.eval_cases()[1]
		values = " ".join(a["value"] for a in second["assertions"])
		self.assertIn(step_patch.STEP_ID, values)
		self.assertIn("Process_Closure", values)
