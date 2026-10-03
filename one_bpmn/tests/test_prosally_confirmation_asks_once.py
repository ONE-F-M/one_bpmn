# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's confirmation asks its yes/no question once, even when the model repeats it in the summary."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0.prosally_confirmation_asks_once import (
	IMPORT_NEW,
	JOIN_NEW,
	JOIN_OLD,
	with_join_confirmation,
)

CONVERSATION = "_test_prosally_asks_once"
QUESTION = "Shall I go ahead?"
SUMMARY = (
	"I'll draw the Leave Request process: the employee submits and the manager approves.\nShall I go ahead?"
)


class TestJoinConfirmation(FrappeTestCase):
	def test_a_summary_ending_in_the_question_asks_it_once(self):
		reply = helpers.join_confirmation(SUMMARY, QUESTION)
		self.assertEqual(reply.count(QUESTION), 1)
		self.assertTrue(reply.endswith("\n" + QUESTION))

	def test_case_and_punctuation_do_not_matter(self):
		reply = helpers.join_confirmation("I'll draw it. shall i go ahead", QUESTION)
		self.assertEqual(reply, "I'll draw it.\n" + QUESTION)

	def test_a_different_closing_sentence_is_kept(self):
		self.assertEqual(
			helpers.join_confirmation("I'll draw it. Is that right?", QUESTION),
			"I'll draw it. Is that right?\n" + QUESTION,
		)
		self.assertEqual(helpers.join_confirmation("", QUESTION), QUESTION)


class TestScriptsAskOnce(FrappeTestCase):
	"""Runs the live Confirm and Classify Intent Server Scripts; they reach a site with the ProsAlly map by export."""

	def tearDown(self):
		clear_turn(CONVERSATION)

	def _run(self, api_method, turn, model_reply):
		script = frappe.db.get_value("Server Script", {"api_method": api_method}, "script")
		if not script or JOIN_NEW not in script:
			self.skipTest(f"the patched {api_method} script is not on this site")
		set_turn(CONVERSATION, {"user_text": "Draw a leave request process", "current_xml": "", **turn})
		with patch.object(helpers, "complete_sub_prompt", return_value=json.dumps(model_reply)):
			exec(script, {"frappe": frappe, "context_docname": CONVERSATION, "result": {}})
		return get_turn(CONVERSATION)["output"]["response"]

	def test_classify_asks_once(self):
		reply = {"intent": "GENERATE_NEW", "reason": "r", "summary": SUMMARY, "question": QUESTION}
		self.assertEqual(self._run("prosally_tool_classify_intent", {}, reply).count(QUESTION), 1)

	def test_confirm_asks_once(self):
		reply = {"summary": SUMMARY, "question": QUESTION}
		response = self._run("prosally_tool_confirm", {"intent": "GENERATE_NEW"}, reply)
		self.assertEqual(response.count(QUESTION), 1)


class TestPatchTransform(FrappeTestCase):
	SCRIPT = (
		f"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, extract_json\n    {JOIN_OLD}\n"
	)

	def test_the_join_uses_join_confirmation(self):
		script = with_join_confirmation(self.SCRIPT)
		self.assertIn(IMPORT_NEW, script)
		self.assertIn(f"    {JOIN_NEW}\n", script)
		self.assertNotIn(JOIN_OLD, script)

	def test_a_moved_anchor_leaves_the_script_alone(self):
		self.assertIsNone(with_join_confirmation(self.SCRIPT.replace(JOIN_OLD, "response_text = question")))
