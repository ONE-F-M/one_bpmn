# Copyright (c) 2026, one-fm and contributors
"""A request for a step the sub-process already has is answered with what is there, never with an Apply card."""

import ast
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.prosally_helpers import no_change_reply, similar_steps
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_says_what_is_already_there as already_patch

CONVERSATION = "_test_prosally_already_there"
REQUEST = "Create a sub process for Complete Payroll Clearance: Payroll Operator checks pending salary"
HEAD = '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">'
XML = (
	f'{HEAD}<bpmn:process id="P"><bpmn:subProcess id="payroll" name="Payroll Clearance">'
	'<bpmn:userTask id="a" name="Check Pending Salary Details (From/To Date)"/>'
	'<bpmn:userTask id="b" name="Enter Pending Salary Amount"/>'
	'<bpmn:userTask id="c" name="Check Overtime Availability"/>'
	'</bpmn:subProcess><bpmn:userTask id="d" name="Notify HR"/></bpmn:process></bpmn:definitions>'
)
DRAW_REPLY = {"intent": "MODIFY_EXISTING", "reason": "r", "summary": {"intro": "I'll update it", "steps": [], "settings": []}, "question": "Shall I go ahead?"}


class RecordingAdapter:
	def __init__(self, reply):
		self.reply = reply
		self.prompts = []

	async def complete(self, system, user):
		self.prompts.append(user)
		return SimpleNamespace(text=json.dumps(self.reply))


class TestSimilarSteps(FrappeTestCase):
	def test_the_steps_that_share_the_requests_words_are_named_best_match_first(self):
		found = similar_steps(XML, [REQUEST], "Payroll Clearance")
		self.assertEqual(found, ["Check Pending Salary Details (From/To Date)", "Enter Pending Salary Amount"])

	def test_the_request_is_the_newest_message_that_is_not_a_yes_or_a_no(self):
		found = similar_steps(XML, ["Yes, proceed", REQUEST], "Payroll Clearance")
		self.assertEqual(found[0], "Check Pending Salary Details (From/To Date)")

	def test_a_request_for_something_the_sub_process_lacks_names_nothing(self):
		self.assertEqual(similar_steps(XML, ["Add a step Verify Final Settlement"], "Payroll Clearance"), [])

	def test_one_shared_word_is_not_enough_when_the_request_has_several(self):
		self.assertEqual(similar_steps(XML, ["Add a step that notifies the pending list"], "Payroll Clearance"), [])

	def test_no_request_names_nothing(self):
		self.assertEqual(similar_steps(XML, ["Yes, proceed"], "Payroll Clearance"), [])


class TestNoChangeReply(FrappeTestCase):
	def test_it_names_the_step_that_is_already_there_and_says_what_to_do_next(self):
		text = no_change_reply('the sub-process "Payroll Clearance"', ["Enter Pending Salary Amount"])
		self.assertIn('already has the step "Enter Pending Salary Amount"', text)
		self.assertIn("what else to add or change", text)

	def test_several_steps_are_named_as_steps(self):
		self.assertIn("the steps", no_change_reply("the process", ["A", "B"]))

	def test_without_a_match_it_asks_which_step_and_where(self):
		text = no_change_reply("the process", [])
		self.assertIn("which step to add or change", text)
		self.assertNotIn("already has", text)


class TestClassifierSaysItIsThere(FrappeTestCase):
	def setUp(self):
		already_patch.execute()
		self.script = frappe.db.get_value("Server Script", {"api_method": "prosally_tool_classify_intent"}, "script")
		if not self.script or "resolve_scope(" not in self.script:
			self.skipTest("the patched ProsAlly Classify Intent script is not on this site")
		ast.parse(self.script)

	def tearDown(self):
		clear_turn(CONVERSATION)

	def _classify(self, user_text, scope_id=""):
		set_turn(
			CONVERSATION,
			{"user_text": user_text, "process_name": "P", "current_xml": XML, "scope_id": scope_id, "chat_history": []},
		)
		adapter = RecordingAdapter(DRAW_REPLY)
		with (
			patch("one_bpmn.agents.prosally_helpers.get_llm_adapter_from_settings", return_value=adapter),
			patch("one_bpmn.agents.prosally_helpers.unapplied_proposal", return_value=None),
		):
			exec(self.script, {"frappe": frappe, "context_docname": CONVERSATION, "result": {}})
		return adapter

	def test_the_classifier_is_told_which_step_already_covers_the_request(self):
		adapter = self._classify(REQUEST, scope_id="payroll")
		self.assertIn('already has "Check Pending Salary Details (From/To Date)"', adapter.prompts[0])
		self.assertIn("ask whether to add another one anyway", adapter.prompts[0])

	def test_nothing_is_said_when_no_step_covers_the_request(self):
		adapter = self._classify("Add a step Verify Final Settlement inside Payroll Clearance", scope_id="payroll")
		self.assertNotIn("That sub-process already has", adapter.prompts[0])


class TestModifyScriptShowsNoCardWhenNothingChanged(FrappeTestCase):
	def setUp(self):
		already_patch.execute()
		name = frappe.db.get_value("Server Script", {"name": ["like", "ProsAlly%Tool Modify Process"]}, "name")
		if not name:
			self.skipTest("the ProsAlly Modify Process script is not on this site")
		self.name = name

	def test_an_unchanged_diagram_is_a_plain_reply_with_no_diagram_attached(self):
		script = frappe.db.get_value("Server Script", self.name, "script")
		ast.parse(script)
		changed = ('if "\\n- " in _changes else "CLARIFY"', 'if _changed else "CLARIFY"')
		self.assertTrue(any('"intent": "BPMN_MODIFIED" ' + tail in script for tail in changed))
		self.assertIn('output["bpmn_xml"] = merged_xml', script)

	def test_a_modify_that_changes_nothing_says_what_is_there_and_attaches_no_diagram(self):
		script = frappe.db.get_value("Server Script", self.name, "script")
		set_turn(
			CONVERSATION,
			{
				"user_text": "Yes, proceed",
				"process_name": "P",
				"current_xml": XML,
				"scope_id": "payroll",
				"chat_history": [{"role": "user", "content": REQUEST}],
			},
		)
		result = {}
		with (
			patch("one_bpmn.agents.prosally_helpers.complete_sub_prompt", return_value='{"nodes": [], "flows": []}'),
			patch("one_bpmn.agents.prosally_helpers.splice_subprocess", lambda xml, child, scope_id: xml),
		):
			exec(script, {"frappe": frappe, "context_docname": CONVERSATION, "result": result, "bpmn_id": "x"})
		output = get_turn(CONVERSATION)["output"]
		clear_turn(CONVERSATION)
		self.assertEqual(output["intent"], "CLARIFY")
		self.assertNotIn("bpmn_xml", output)
		self.assertFalse(result["modified"])
		self.assertIn('It already has the steps "Check Pending Salary Details (From/To Date)"', output["response"])

	def test_running_the_patch_again_changes_nothing(self):
		before = frappe.db.get_value("Server Script", self.name, "script")
		already_patch.execute()
		self.assertEqual(frappe.db.get_value("Server Script", self.name, "script"), before)
